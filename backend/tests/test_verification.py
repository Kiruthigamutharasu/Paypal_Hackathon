"""F3: decision versioning, invalidation, acknowledge/override, API."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.errors import AppError
from app.models import (
    AIExtraction,
    AuditLog,
    Capture,
    Order,
    ProtectedAddress,
    ShippingDecision,
    Upload,
)
from app.workflows.verification import acknowledge, active_decision, evaluate_order, shipping_allowed

LABEL_OUT = {
    "schema_version": "1.0", "labels_detected": 1, "recipient_name": "John Doe",
    "address": {"line1": "1 Main St", "line2": None, "city": "San Jose", "state": "CA", "postal_code": "95131", "country": "US"},
    "tracking_number_visible": None, "carrier_visible": "USPS", "readable": True, "issues": [], "field_confidence": {}, "confidence": 0.95,
}


def chat_out(*reqs):
    return {"schema_version": "1.0", "messages_observed": 3, "conversation_complete": True, "requests": list(reqs),
            "addresses_mentioned": [], "issues": [], "confidence": 0.95}


AUSTIN = {"type": "ADDRESS_CHANGE", "speaker": "BUYER", "status": "EXPLICIT", "quote": "ship to my friend in Austin",
          "source_ref": {"upload_id": "x", "position": 2}, "timestamp_text": None,
          "requested_address": {"line1": None, "line2": None, "city": "Austin", "state": "TX", "postal_code": None, "country": None}}


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def order(db) -> Order:
    o = Order(paypal_order_id="ORDV1", payment_state="PAYMENT_COMPLETED", amount=Decimal("300.00"), currency="USD")
    db.add(o)
    db.flush()
    db.add(Capture(order_id=o.id, paypal_capture_id="CAPV1", status="COMPLETED", seller_protection_status="ELIGIBLE",
                   paypal_create_time="2026-11-04T10:00:00Z"))
    db.add(ProtectedAddress(order_id=o.id, name="John Doe", line1="1 Main St", city="San Jose", state="CA", postal_code="95131", country="US"))
    db.commit()
    return o


def add_upload(db, order, kind, n=1):
    u = Upload(order_id=order.id, kind=kind, path=f"x/{kind}{n}", mime="image/png", size=1, sha256="0" * 64, sequence=n)
    db.add(u)
    db.commit()
    return u


def add_extraction(db, order, agent, upload, output, status="SUCCEEDED"):
    x = AIExtraction(order_id=order.id, agent=agent, upload_ids=[upload.id], provider="fake", model="fake", prompt_version="v",
                     schema_version="1.0", input_hash=upload.id, output=output, status=status, confidence=Decimal("0.9"))
    db.add(x)
    db.commit()
    return x


def test_missing_label_is_grey_then_green(db, settings, order):  # AC3.5
    d1 = evaluate_order(db, settings, order.id)
    assert d1.verdict == "GREY" and "ADD-02" in {f.code for f in d1.flags}
    lab = add_upload(db, order, "LABEL_IMAGE")
    d_pending = evaluate_order(db, settings, order.id)
    assert d_pending.verdict == "GREY" and "SYS-03" in {f.code for f in d_pending.flags}
    add_extraction(db, order, "label_reader", lab, LABEL_OUT)
    d2 = evaluate_order(db, settings, order.id)
    assert d2.verdict == "GREEN"
    db.refresh(d1)
    assert d1.status == "SUPERSEDED" and active_decision(db, order.id).id == d2.id
    assert db.get(Order, order.id).verification_state == "GREEN"


def test_same_inputs_return_same_decision(db, settings, order):
    a = evaluate_order(db, settings, order.id)
    b = evaluate_order(db, settings, order.id)
    assert a.id == b.id
    assert db.scalar(select(func.count()).select_from(ShippingDecision)) == 1


def test_ship_to_friend_is_red_with_quote(db, settings, order):  # AC3.2
    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, LABEL_OUT)
    ch = add_upload(db, order, "CHAT_IMAGE", 2)
    add_extraction(db, order, "conversation_analyst", ch, chat_out(AUSTIN))
    d = evaluate_order(db, settings, order.id)
    f = next(f for f in d.flags if f.code == "ADD-03")
    assert d.verdict == "RED" and "Austin" in f.detail and f.recommended_action


def test_new_label_supersedes_and_reevaluates(db, settings, order):  # AC3.4
    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, dict(LABEL_OUT, address=dict(LABEL_OUT["address"], postal_code="95132")))
    first = evaluate_order(db, settings, order.id)
    assert first.verdict == "RED"
    lab2 = add_upload(db, order, "LABEL_IMAGE", 2)
    lab.superseded_by = lab2.id
    db.commit()
    add_extraction(db, order, "label_reader", lab2, LABEL_OUT)
    second = evaluate_order(db, settings, order.id)
    db.refresh(first)
    assert second.verdict == "GREEN" and first.status == "SUPERSEDED"


def test_payment_change_reevaluates(db, settings, order):
    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, LABEL_OUT)
    assert evaluate_order(db, settings, order.id).verdict == "GREEN"
    o = db.get(Order, order.id)
    o.payment_state = "REFUNDED"
    db.commit()
    d = evaluate_order(db, settings, order.id)
    assert d.verdict == "RED" and "PAY-05" in {f.code for f in d.flags}


def test_yellow_acknowledge_requires_every_item(db, settings, order):
    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, dict(LABEL_OUT, recipient_name="Robert Smith"))
    d = evaluate_order(db, settings, order.id)
    assert d.verdict == "YELLOW"
    with pytest.raises(AppError) as ei:
        acknowledge(db, order.id, items=[], reason=None, confirm_void=False)
    assert ei.value.error_code == "ACK_INCOMPLETE"
    d = acknowledge(db, order.id, items=["ADD-09"], reason=None, confirm_void=False)
    assert d.resolution == "ACKNOWLEDGED" and shipping_allowed(d)[0]
    assert db.get(Order, order.id).verification_state == "ACKNOWLEDGED"


def test_red_override_requires_reason_and_confirmation_and_is_audited(db, settings, order):  # AC3.6
    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, dict(LABEL_OUT, address=dict(LABEL_OUT["address"], city="Austin", state="TX")))
    assert evaluate_order(db, settings, order.id).verdict == "RED"
    assert not shipping_allowed(active_decision(db, order.id))[0]
    with pytest.raises(AppError):
        acknowledge(db, order.id, items=[], reason="too short", confirm_void=True)
    with pytest.raises(AppError):
        acknowledge(db, order.id, items=[], reason="Buyer confirmed by phone, I accept the risk", confirm_void=False)
    d = acknowledge(db, order.id, items=[], reason="Buyer confirmed by phone, I accept the risk", confirm_void=True)
    assert d.resolution == "OVERRIDDEN" and shipping_allowed(d)[0]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "DECISION_OVERRIDDEN"))
    assert entry.details["reason"].startswith("Buyer confirmed")


def test_grey_cannot_be_acknowledged(db, settings, order):
    evaluate_order(db, settings, order.id)
    with pytest.raises(AppError) as ei:
        acknowledge(db, order.id, items=[], reason="x" * 20, confirm_void=True)
    assert ei.value.error_code == "CANNOT_ACKNOWLEDGE"


def test_new_input_resets_acknowledgement(db, settings, order):
    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, dict(LABEL_OUT, recipient_name="Robert Smith"))
    evaluate_order(db, settings, order.id)
    acknowledge(db, order.id, items=["ADD-09"], reason=None, confirm_void=False)
    ch = add_upload(db, order, "CHAT_TEXT", 2)
    add_extraction(db, order, "conversation_analyst", ch, chat_out())
    d = evaluate_order(db, settings, order.id)
    assert d.resolution == "NONE" and not shipping_allowed(d)[0]


def test_decision_api_and_orders_list_show_verdict(db, order, client_pp):
    from app.deps import get_paypal_client
    from app.main import app

    lab = add_upload(db, order, "LABEL_IMAGE")
    add_extraction(db, order, "label_reader", lab, dict(LABEL_OUT, address=dict(LABEL_OUT["address"], line1="2211 N First St")))
    app.dependency_overrides[get_paypal_client] = lambda: client_pp
    with TestClient(app) as c:
        d = c.get(f"/api/orders/{order.id}/decision").json()
        assert d["verdict"] == "RED" and d["can_ship"] is False
        assert any(f["code"] == "ADD-08" for f in d["flags"])
        assert {ch["key"] for ch in d["checks"]} >= {"payment", "label", "match"}
        assert d["comparison"]["overall"] == "MISMATCH"
        r = c.post(f"/api/orders/{order.id}/decision/acknowledge", json={"reason": "short", "confirm_void": True})
        assert r.status_code == 422 and r.json()["error_code"] == "OVERRIDE_REASON_REQUIRED"
        r = c.post(f"/api/orders/{order.id}/decision/acknowledge",
                   json={"reason": "Customer moved; confirmed by phone call", "confirm_void": True})
        assert r.status_code == 200 and r.json()["can_ship"] is True
        row = next(o for o in c.get("/api/orders").json() if o["id"] == order.id)
        assert row["verdict"] == "RED" and row["verdict_resolution"] == "OVERRIDDEN"
    app.dependency_overrides.clear()
