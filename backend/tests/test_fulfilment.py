"""F4: Safe re-pay, tracking registration, gating, idempotency (PayPal mocked with respx)."""
from __future__ import annotations

import copy
import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.deps import get_ai_provider_factory, get_paypal_client
from app.models import AIExtraction, AuditLog, Order, Remediation, Shipment, Upload
from app.services.reconcile import reconcile_order
from tests import factories as f

NEW_ORDER = "7BP0540820135115W"
NEW_CAPTURE = "9NEWCAPTURE0000X"
AUSTIN = {"name": "Emily Carter", "line1": "500 Congress Ave", "line2": None, "city": "Austin", "state": "TX", "postal_code": "78701", "country": "US"}
AUSTIN_SHIPPING = {"name": {"full_name": "Emily Carter"}, "address": {"address_line_1": "500 Congress Ave", "admin_area_2": "Austin",
                                                                      "admin_area_1": "TX", "postal_code": "78701", "country_code": "US"}}


@pytest.fixture
def api(db, client_pp):
    from app.main import app

    app.dependency_overrides[get_paypal_client] = lambda: client_pp
    app.dependency_overrides[get_ai_provider_factory] = lambda: (lambda: None)  # template messages, no AI quota
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def mock_original(paypal_mock, cap_status="COMPLETED"):
    cap = f.capture(cap_status)
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[cap]))
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=cap)


def add_evidence(db, order, label_line1="123 Main St", chat_request=True):
    from pathlib import Path

    from app.config import get_settings
    from app.services.storage import storage_root

    data = (Path(__file__).parent / "fixtures" / "labels" / "l01_clean_ny.png").read_bytes()
    dest = storage_root(get_settings()) / order.id / "label.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    lab = Upload(order_id=order.id, kind="LABEL_IMAGE", path=f"{order.id}/label.png", mime="image/png", size=len(data), sha256="0" * 64, sequence=0)
    db.add(lab)
    db.flush()
    db.add(AIExtraction(order_id=order.id, agent="label_reader", upload_ids=[lab.id], provider="fake", model="fake", prompt_version="lr",
                        schema_version="1.0", input_hash=lab.id, status="SUCCEEDED", confidence=Decimal("0.95"), output={
                            "labels_detected": 1, "recipient_name": "Jane Doe", "readable": True, "issues": [], "field_confidence": {},
                            "confidence": 0.95, "tracking_number_visible": None, "carrier_visible": "USPS",
                            "address": {"line1": label_line1, "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": "10001", "country": "US"}}))
    if chat_request:
        ch = Upload(order_id=order.id, kind="CHAT_TEXT", path="x/c", mime="text/plain", size=1, sha256="1" * 64, sequence=1)
        db.add(ch)
        db.flush()
        db.add(AIExtraction(order_id=order.id, agent="conversation_analyst", upload_ids=[ch.id], provider="fake", model="fake", prompt_version="ca",
                            schema_version="1.0", input_hash=ch.id, status="SUCCEEDED", confidence=Decimal("0.9"), output={
                                "messages_observed": 2, "conversation_complete": True, "issues": [], "confidence": 0.9, "addresses_mentioned": [],
                                "requests": [{"type": "ADDRESS_CHANGE", "speaker": "BUYER", "status": "EXPLICIT", "quote": "ship to my friend in Austin",
                                              "source_ref": {"upload_id": ch.id, "position": 1}, "timestamp_text": None,
                                              "requested_address": {"line1": "500 Congress Ave", "line2": None, "city": "Austin", "state": "TX",
                                                                    "postal_code": "78701", "country": None}}]}))
    db.commit()


@pytest.fixture
def red_order(db, paypal_mock, client_pp) -> Order:
    mock_original(paypal_mock)
    order = reconcile_order(db, client_pp, f.ORDER_ID)
    add_evidence(db, order)
    from app.config import get_settings
    from app.workflows.verification import evaluate_order

    assert evaluate_order(db, get_settings(), order.id).verdict == "RED"
    return order


def mock_repay_paypal(paypal_mock, refund_status=201, create_status=201):
    refund = paypal_mock.post(f"/v2/payments/captures/{f.CAPTURE_ID}/refund").respond(
        refund_status, json={"id": "1JU08902781691411", "status": "COMPLETED"} if refund_status < 300 else
        {"name": "UNPROCESSABLE_ENTITY", "debug_id": "dbgR", "details": [{"issue": "CAPTURE_FULLY_REFUNDED"}]})
    # after the refund, the original capture reads REFUNDED
    refunded = f.capture("REFUNDED")
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[refunded]))
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=refunded)
    create = paypal_mock.post("/v2/checkout/orders").respond(
        create_status, json={"id": NEW_ORDER, "status": "PAYER_ACTION_REQUIRED",
                             "links": [{"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={NEW_ORDER}"}]}
        if create_status < 300 else {"name": "INTERNAL_SERVER_ERROR"})
    return refund, create


def test_repay_happy_path_and_buyer_payment(api, db, red_order, paypal_mock):  # AC4.1, AC4.2
    r = api.post(f"/api/orders/{red_order.id}/remediations", json={"type": "REPAY", "requested_address": AUSTIN})
    assert r.status_code == 200, r.text
    rem = r.json()
    assert rem["status"] == "PENDING_CONFIRMATION" and rem["confirmation_code"] and rem["buyer_message"]
    assert rem["refund_amount"] == "300.00"

    refund, create = mock_repay_paypal(paypal_mock)
    bad = api.post(f"/api/remediations/{rem['id']}/confirm", json={"confirmation_code": "WRONG"})
    assert bad.status_code == 422 and refund.call_count == 0  # no money moves without the right confirmation

    ok = api.post(f"/api/remediations/{rem['id']}/confirm", json={"confirmation_code": rem["confirmation_code"]}).json()
    assert ok["status"] == "AWAITING_BUYER_PAYMENT" and ok["new_paypal_order_id"] == NEW_ORDER
    assert ok["pay_page_path"] == f"/pay/{NEW_ORDER}" and NEW_ORDER in ok["buyer_message"]
    assert refund.calls[0].request.headers["PayPal-Request-Id"] == f"repay-refund-{rem['id']}"
    sent = json.loads(create.calls[0].request.content)
    assert sent["payment_source"]["paypal"]["experience_context"]["shipping_preference"] == "SET_PROVIDED_ADDRESS"
    assert sent["purchase_units"][0]["shipping"]["address"]["admin_area_2"] == "Austin"

    # double click: no second refund
    again = api.post(f"/api/remediations/{rem['id']}/confirm", json={"confirmation_code": rem["confirmation_code"]})
    assert again.status_code == 200 and refund.call_count == 1 and create.call_count == 1

    db.expire_all()
    order = db.get(Order, red_order.id)
    assert order.payment_state == "REFUNDED" and order.current_paypal_order_id == NEW_ORDER
    assert order.active_address.city == "New York"  # unpaid re-pay order must not change the protected address
    assert api.get(f"/api/orders/{order.id}/decision").json()["verdict"] == "RED"  # PAY-05 until the buyer pays

    # buyer pays the new order
    new_cap = f.capture("COMPLETED", capture_id=NEW_CAPTURE, order_id=NEW_ORDER)
    paypal_mock.post(f"/v2/checkout/orders/{NEW_ORDER}/capture").respond(201, json=f.order(captures=[new_cap], shipping=AUSTIN_SHIPPING, order_id=NEW_ORDER))
    paypal_mock.get(f"/v2/checkout/orders/{NEW_ORDER}").respond(200, json=f.order(captures=[new_cap], shipping=AUSTIN_SHIPPING, order_id=NEW_ORDER))
    paypal_mock.get(f"/v2/payments/captures/{NEW_CAPTURE}").respond(200, json=new_cap)
    paid = api.post(f"/api/shop/orders/{NEW_ORDER}/capture").json()
    assert paid["order_id"] == order.id and paid["payment_state"] == "PAYMENT_COMPLETED"

    db.expire_all()
    order = db.get(Order, red_order.id)
    assert order.active_address.city == "Austin" and order.active_address.source == "PAYPAL_REPAY" and order.active_address.version == 2
    assert db.scalar(select(func.count()).select_from(Order)) == 1  # still ONE StayCovered order
    assert db.scalar(select(Remediation)).status == "COMPLETED"
    d = api.get(f"/api/orders/{order.id}/decision").json()
    codes = {fl["code"] for fl in d["flags"]}
    assert "ADD-03" not in codes  # the Austin request now matches the protected address
    assert "ADD-04" in codes  # the OLD New York label no longer matches -> upload a new label
    assert any("already matches the PayPal address" in i for i in d["ignored"])


def test_refund_failure_stops_before_new_order(api, db, red_order, paypal_mock):
    rem = api.post(f"/api/orders/{red_order.id}/remediations", json={"type": "REPAY", "requested_address": AUSTIN}).json()
    refund, create = mock_repay_paypal(paypal_mock, refund_status=422)
    r = api.post(f"/api/remediations/{rem['id']}/confirm", json={"confirmation_code": rem["confirmation_code"]})
    assert r.status_code == 502 and r.json()["error_code"] == "REFUND_FAILED" and r.json()["details"]["paypal_debug_id"] == "dbgR"
    assert create.call_count == 0
    assert db.scalar(select(Remediation)).status == "REFUND_FAILED"


def test_order_creation_failure_after_refund_can_retry(api, db, red_order, paypal_mock):
    rem = api.post(f"/api/orders/{red_order.id}/remediations", json={"type": "REPAY", "requested_address": AUSTIN}).json()
    mock_repay_paypal(paypal_mock, create_status=500)
    r = api.post(f"/api/remediations/{rem['id']}/confirm", json={"confirmation_code": rem["confirmation_code"]}).json()
    assert r["status"] == "REFUNDED_AWAITING_NEW_ORDER" and r["error"]
    paypal_mock.post("/v2/checkout/orders").respond(201, json={"id": NEW_ORDER, "status": "PAYER_ACTION_REQUIRED", "links": []})
    retried = api.post(f"/api/remediations/{rem['id']}/retry").json()
    assert retried["status"] == "AWAITING_BUYER_PAYMENT" and retried["new_paypal_order_id"] == NEW_ORDER


@pytest.mark.parametrize("addr,code", [
    ({**AUSTIN, "postal_code": "787"}, "ADDRESS_INVALID"),
    ({**AUSTIN, "city": ""}, "ADDRESS_INCOMPLETE"),
    ({**AUSTIN, "country": "CA"}, "ADDRESS_UNSUPPORTED"),
    (None, "ADDRESS_REQUIRED"),
])
def test_repay_address_validation(api, red_order, addr, code):
    r = api.post(f"/api/orders/{red_order.id}/remediations", json={"type": "REPAY", "requested_address": addr})
    assert r.status_code == 422 and r.json()["error_code"] == code


def test_ship_to_protected_drafts_message_without_money(api, red_order, paypal_mock):
    r = api.post(f"/api/orders/{red_order.id}/remediations", json={"type": "SHIP_TO_PROTECTED"}).json()
    assert r["status"] == "DRAFTED" and "New York" in r["buyer_message"] and r["message_source"] == "TEMPLATE"
    assert "guarantee" not in r["buyer_message"].lower()


def test_suggested_address_comes_from_chat(api, red_order):
    s = api.get(f"/api/orders/{red_order.id}/remediations").json()["suggested_address"]
    assert s["city"] == "Austin" and s["postal_code"] == "78701"


# ---------------- tracking ----------------
def track_response(number, carrier="USPS"):
    return {"id": f.ORDER_ID, "status": "COMPLETED", "purchase_units": [{"shipping": {"trackers": [
        {"id": f"{f.CAPTURE_ID}-{number}", "status": "SHIPPED", "links": []}]}}]}


def green_order(db, paypal_mock, client_pp):
    mock_original(paypal_mock)
    order = reconcile_order(db, client_pp, f.ORDER_ID)
    add_evidence(db, order, chat_request=False)
    from app.config import get_settings
    from app.workflows.verification import evaluate_order

    assert evaluate_order(db, get_settings(), order.id).verdict == "GREEN"
    return order


def test_tracking_blocked_while_red(api, red_order, paypal_mock):  # AC4.6
    r = api.post(f"/api/orders/{red_order.id}/shipments", json={"carrier": "USPS", "tracking_number": "9400111899223344556677"})
    assert r.status_code == 409 and r.json()["error_code"] == "SHIPPING_NOT_ALLOWED"


def test_tracking_registered_and_idempotent(api, db, paypal_mock, client_pp):  # AC4.3
    order = green_order(db, paypal_mock, client_pp)
    route = paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/track").respond(201, json=track_response("9400111899223344556677"))
    body = {"carrier": "USPS", "tracking_number": "9400 1118 9922 3344 5566 77", "notify_payer": True}
    s1 = api.post(f"/api/orders/{order.id}/shipments", json=body).json()
    assert s1["paypal_tracker_id"] == f"{f.CAPTURE_ID}-9400111899223344556677" and s1["status"] == "SHIPPED" and s1["decision_basis"] == "GREEN"
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"capture_id": f.CAPTURE_ID, "tracking_number": "9400111899223344556677", "carrier": "USPS", "notify_payer": True,
                    "items": [{"name": "Handmade Silver Necklace", "quantity": "1"}]}
    s2 = api.post(f"/api/orders/{order.id}/shipments", json=body).json()
    assert s2["id"] == s1["id"] and route.call_count == 1
    db.expire_all()
    assert db.get(Order, order.id).shipment_state == "SHIPPED"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "TRACKING_REGISTERED")) is not None


def test_tracking_blocked_for_non_completed_capture(api, db, paypal_mock, client_pp):  # AC4.4
    order = green_order(db, paypal_mock, client_pp)
    o = db.get(Order, order.id)
    o.payment_state = "PAYMENT_PENDING"
    o.latest_capture.status = "PENDING"
    db.commit()
    r = api.post(f"/api/orders/{order.id}/shipments", json={"carrier": "USPS", "tracking_number": "9400111899223344556677"})
    assert r.status_code == 409 and r.json()["error_code"] == "CAPTURE_NOT_COMPLETED"


def test_tracking_number_reuse_blocked(api, db, paypal_mock, client_pp):  # AC4.5
    order = green_order(db, paypal_mock, client_pp)
    other = Order(paypal_order_id="OTHERORDER1", payment_state="PAYMENT_COMPLETED")
    db.add(other)
    db.flush()
    db.add(Shipment(order_id=other.id, paypal_order_id="OTHERORDER1", capture_id="X", carrier="USPS", tracking_number="9400111899223344556677"))
    db.commit()
    r = api.post(f"/api/orders/{order.id}/shipments", json={"carrier": "USPS", "tracking_number": "9400111899223344556677"})
    assert r.status_code == 409 and r.json()["error_code"] == "SHP-04"


@pytest.mark.parametrize("carrier,number,ok", [
    ("UPS", "1Z999AA10123456784", True), ("UPS", "12345", False), ("FEDEX", "443844607820", True),
    ("USPS", "ABC", False), ("OTHER", "LOCAL123456", True), ("FAKECARRIER", "123456789", False),
])
def test_tracking_validation(api, db, paypal_mock, client_pp, carrier, number, ok):
    order = green_order(db, paypal_mock, client_pp)
    paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/track").respond(201, json=track_response(number))
    body = {"carrier": carrier, "tracking_number": number}
    if carrier == "OTHER":
        body["carrier_name_other"] = "Local Courier"
    r = api.post(f"/api/orders/{order.id}/shipments", json=body)
    assert (r.status_code == 200) == ok, r.text


def test_cancel_tracker_patches_paypal(api, db, paypal_mock, client_pp):
    order = green_order(db, paypal_mock, client_pp)
    paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/track").respond(201, json=track_response("9400111899223344556677"))
    s = api.post(f"/api/orders/{order.id}/shipments", json={"carrier": "USPS", "tracking_number": "9400111899223344556677"}).json()
    patch = paypal_mock.patch(f"/v2/checkout/orders/{f.ORDER_ID}/trackers/{s['paypal_tracker_id']}").respond(204)
    r = api.patch(f"/api/shipments/{s['id']}", json={"status": "CANCELLED"}).json()
    assert r["status"] == "CANCELLED" and patch.call_count == 1
    assert json.loads(patch.calls[0].request.content) == [{"op": "replace", "path": "/status", "value": "CANCELLED"}]
    db.expire_all()
    assert db.get(Order, order.id).shipment_state == "CANCELLED"
