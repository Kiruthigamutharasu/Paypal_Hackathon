"""End-to-end story through the real API (PayPal mocked with respx, AI faked):

pay -> chat + wrong label -> RED -> Safe re-pay -> buyer pays new order -> new label -> GREEN
-> tracking registered -> dispute webhook -> evidence planned -> submitted to PayPal.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.deps import get_ai_provider_factory, get_paypal_client
from tests import factories as f
from tests.test_extraction import FakeProvider, conv, req

FIX = Path(__file__).parent / "fixtures"
NEW_ORDER, NEW_CAP, DID = "8NEWORDER0000001", "8NEWCAPTURE00001", "PP-D-E2E1"
AUSTIN_SHIPPING = {"name": {"full_name": "Emily Carter"}, "address": {"address_line_1": "500 Congress Ave", "admin_area_2": "Austin",
                                                                      "admin_area_1": "TX", "postal_code": "78701", "country_code": "US"}}
TRACK = "9400111899223355566677"


def label_out(line1, city, state, zip_, name):
    return {"schema_version": "1.0", "labels_detected": 1, "recipient_name": name, "readable": True, "issues": [],
            "address": {"line1": line1, "line2": "Apt 4B" if city == "New York" else None, "city": city, "state": state, "postal_code": zip_, "country": "US"},
            "tracking_number_visible": None, "carrier_visible": "USPS", "field_confidence": {}, "confidence": 0.95}


def test_full_story(db, paypal_mock, client_pp):
    from app.main import app

    labels = [label_out("1 Main St", "New York", "NY", "10001", "Jane Doe"),        # wrong street -> RED
              label_out("500 Congress Ave", "Austin", "TX", "78701", "Emily Carter")]  # after re-pay -> GREEN

    def ai(schema_name, parts):
        if schema_name == "LabelExtraction":
            return labels.pop(0)
        uid = next(p.text.split('upload_id="')[1].split('"')[0] for p in parts if hasattr(p, "text") and 'upload_id="' in p.text)
        return conv(uid, req(uid, "It's a gift! Please ship to my friend in Austin, TX instead", pos=3,
                             address={"line1": "500 Congress Ave", "line2": None, "city": "Austin", "state": "TX", "postal_code": "78701", "country": None}))

    provider = FakeProvider([ai])
    app.dependency_overrides[get_paypal_client] = lambda: client_pp
    app.dependency_overrides[get_ai_provider_factory] = lambda: (lambda: provider)
    try:
        with TestClient(app) as api:
            # 1) buyer pays in the demo shop
            cap = f.capture()
            paypal_mock.post("/v2/checkout/orders").respond(201, json={"id": f.ORDER_ID, "status": "PAYER_ACTION_REQUIRED"})
            paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/capture").respond(201, json=f.order(captures=[cap]))
            paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[cap]))
            paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=cap)
            assert api.post("/api/shop/orders", json={}).json()["orderId"] == f.ORDER_ID
            oid = api.post(f"/api/shop/orders/{f.ORDER_ID}/capture").json()["order_id"]

            # 2) seller uploads the chat + a label with the wrong street -> RED
            chat_png = (FIX / "chats" / "c01_gift_friend_austin.png").read_bytes()
            label_png = (FIX / "labels" / "l01_clean_ny.png").read_bytes()
            assert api.post(f"/api/orders/{oid}/uploads", data={"kind": "CHAT_IMAGE"},
                            files=[("files", ("chat.png", io.BytesIO(chat_png), "image/png"))]).status_code == 200
            assert api.post(f"/api/orders/{oid}/uploads", data={"kind": "LABEL_IMAGE"},
                            files=[("files", ("label.png", io.BytesIO(label_png), "image/png"))]).status_code == 200
            d = api.get(f"/api/orders/{oid}/decision").json()
            assert d["verdict"] == "RED" and {"ADD-03", "ADD-08"} <= {x["code"] for x in d["flags"]} and not d["can_ship"]

            # 3) Safe re-pay (seller confirms) -> refund + new order with the Austin address
            rem = api.post(f"/api/orders/{oid}/remediations", json={"type": "REPAY", "requested_address": {
                "name": "Emily Carter", "line1": "500 Congress Ave", "city": "Austin", "state": "TX", "postal_code": "78701", "country": "US"}}).json()
            paypal_mock.post(f"/v2/payments/captures/{f.CAPTURE_ID}/refund").respond(201, json={"id": "REFUND1", "status": "COMPLETED"})
            refunded = f.capture("REFUNDED")
            paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[refunded]))
            paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=refunded)
            paypal_mock.post("/v2/checkout/orders").respond(201, json={"id": NEW_ORDER, "status": "PAYER_ACTION_REQUIRED", "links": []})
            rem = api.post(f"/api/remediations/{rem['id']}/confirm", json={"confirmation_code": rem["confirmation_code"]}).json()
            assert rem["status"] == "AWAITING_BUYER_PAYMENT"

            # 4) buyer pays the new order -> Austin becomes the protected address
            new_cap = f.capture(capture_id=NEW_CAP, order_id=NEW_ORDER)
            paid_order = f.order(captures=[new_cap], shipping=AUSTIN_SHIPPING, order_id=NEW_ORDER)
            paypal_mock.post(f"/v2/checkout/orders/{NEW_ORDER}/capture").respond(201, json=paid_order)
            paypal_mock.get(f"/v2/checkout/orders/{NEW_ORDER}").respond(200, json=paid_order)
            paypal_mock.get(f"/v2/payments/captures/{NEW_CAP}").respond(200, json=new_cap)
            assert api.post(f"/api/shop/orders/{NEW_ORDER}/capture").json()["order_id"] == oid
            order = api.get(f"/api/orders/{oid}").json()
            assert order["protected_address"]["city"] == "Austin" and order["payment_state"] == "PAYMENT_COMPLETED"

            # 5) new label for Austin -> GREEN
            assert api.post(f"/api/orders/{oid}/uploads", data={"kind": "LABEL_IMAGE"},
                            files=[("files", ("austin.png", io.BytesIO(label_png), "image/png"))]).status_code == 200
            d = api.get(f"/api/orders/{oid}/decision").json()
            assert d["verdict"] == "GREEN" and d["can_ship"], [(x["code"], x["effect"]) for x in d["flags"]]

            # 6) register tracking with PayPal (on the NEW order / capture)
            track = paypal_mock.post(f"/v2/checkout/orders/{NEW_ORDER}/track").respond(201, json={"id": NEW_ORDER, "purchase_units": [
                {"shipping": {"trackers": [{"id": f"{NEW_CAP}-{TRACK}", "status": "SHIPPED"}]}}]})
            ship = api.post(f"/api/orders/{oid}/shipments", json={"carrier": "USPS", "tracking_number": TRACK}).json()
            assert ship["paypal_tracker_id"] == f"{NEW_CAP}-{TRACK}"
            assert json.loads(track.calls[0].request.content)["capture_id"] == NEW_CAP

            # 7) buyer opens an item-not-received dispute -> webhook -> evidence -> submitted
            paypal_mock.post("/v1/notifications/verify-webhook-signature").respond(200, json={"verification_status": "SUCCESS"})
            paypal_mock.get(f"/v1/customer/disputes/{DID}").respond(200, json={
                "dispute_id": DID, "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "status": "WAITING_FOR_SELLER_RESPONSE",
                "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"currency_code": "USD", "value": "300.00"},
                "seller_response_due_date": "2099-01-01T00:00:00.000Z", "disputed_transactions": [{"seller_transaction_id": NEW_CAP}],
                "links": [{"href": f"https://api-m.sandbox.paypal.com/v1/customer/disputes/{DID}/provide-evidence", "rel": "provide_evidence", "method": "POST"}]})
            ev = f.webhook_event("CUSTOMER.DISPUTE.CREATED", {"dispute_id": DID}, "WH-E2E", "dispute")
            assert api.post("/api/webhooks/paypal", content=json.dumps(ev), headers={"Content-Type": "application/json", **f.SIG_HEADERS}).status_code == 200
            dispute = api.get("/api/disputes").json()[0]
            assert dispute["order_id"] == oid
            pack = api.post(f"/api/disputes/{dispute['id']}/plan").json()["pack"]
            assert pack["status"] == "READY" and pack["plan"]["tracking_info"][0]["tracking_number"] == TRACK
            paypal_mock.post(f"/v1/customer/disputes/{DID}/provide-evidence").respond(200, json={"links": []})
            done = api.post(f"/api/disputes/{dispute['id']}/submit", json={"pack_id": pack["id"], "confirm": True}).json()
            assert done["pack"]["status"] == "SUBMITTED"

            timeline = [t["action"] for t in api.get(f"/api/orders/{oid}").json()["timeline"]]
            for step in ("ORDER_CREATED", "EVIDENCE_UPLOADED", "DECISION_MADE", "REPAY_REFUNDED", "REPAY_PAID",
                         "TRACKING_REGISTERED", "DISPUTE_OPENED", "EVIDENCE_SUBMITTED"):
                assert step in timeline, step
    finally:
        app.dependency_overrides.clear()
