import json

import httpx
from sqlalchemy import func, select

from app.models import AuditLog, Order, WebhookEvent
from tests import factories as f

VERIFY = "/v1/notifications/verify-webhook-signature"


def _post_webhook(api, event, headers=None):
    return api.post(
        "/api/webhooks/paypal",
        content=json.dumps(event),
        headers={"Content-Type": "application/json", **(headers if headers is not None else f.SIG_HEADERS)},
    )


def test_health(api):
    r = api.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["paypal_environment"] == "sandbox"
    assert "test-client-secret" not in r.text


def test_shop_create_capture_reconcile(api, paypal_mock, db):  # AC1.1
    create = paypal_mock.post("/v2/checkout/orders").respond(
        201, json={"id": f.ORDER_ID, "status": "PAYER_ACTION_REQUIRED"}
    )
    cap = f.capture()
    capture_route = paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/capture").respond(
        201, json=f.order(captures=[cap])
    )
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[cap]))
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=cap)

    r = api.post("/api/shop/orders", json={"sku": "NECKLACE-SILVER-01", "quantity": 1})
    assert r.status_code == 200 and r.json() == {"orderId": f.ORDER_ID}
    sent = json.loads(create.calls[0].request.content)
    assert sent["intent"] == "CAPTURE"
    assert sent["purchase_units"][0]["amount"]["value"] == "300.00"  # price from server catalog
    assert sent["payment_source"]["paypal"]["experience_context"]["shipping_preference"] == "GET_FROM_FILE"

    r = api.post(f"/api/shop/orders/{f.ORDER_ID}/capture")
    assert r.status_code == 200, r.text
    assert r.json()["payment_state"] == "PAYMENT_COMPLETED"
    assert r.json()["seller_protection_status"] == "ELIGIBLE"
    assert capture_route.calls[0].request.headers["PayPal-Request-Id"] == f"shop-capture-{f.ORDER_ID}"

    # Double click -> PayPal says already captured -> still exactly one order
    paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/capture").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]}
    )
    assert api.post(f"/api/shop/orders/{f.ORDER_ID}/capture").status_code == 200
    assert db.scalar(select(func.count()).select_from(Order)) == 1

    orders = api.get("/api/orders").json()
    assert len(orders) == 1 and orders[0]["ship_to"] == "New York, NY"
    detail = api.get(f"/api/orders/{orders[0]['id']}").json()
    assert detail["protected_address"]["postal_code"] == "10001"
    assert any(t["action"] == "ORDER_CREATED" for t in detail["timeline"])  # AC1.6


def test_capture_declined_returns_clear_error(api, paypal_mock):
    paypal_mock.post(f"/v2/checkout/orders/{f.ORDER_ID}/capture").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY", "debug_id": "d1", "details": [{"issue": "INSTRUMENT_DECLINED"}]}
    )
    r = api.post(f"/api/shop/orders/{f.ORDER_ID}/capture")
    assert r.status_code == 422
    assert r.json()["error_code"] == "INSTRUMENT_DECLINED"
    assert r.json()["details"]["paypal_debug_id"] == "d1"


def test_unknown_paypal_order_maps_to_pay09(api, paypal_mock):
    paypal_mock.get("/v2/checkout/orders/NOPE12345").respond(404, json={"name": "RESOURCE_NOT_FOUND"})
    r = api.post("/api/orders/sync", json={"paypal_order_id": "NOPE12345"})
    assert r.status_code == 404 and r.json()["error_code"] == "PAY-09"


def test_webhook_valid_signature_processes_event(api, paypal_mock, db):
    verify = paypal_mock.post(VERIFY).respond(200, json={"verification_status": "SUCCESS"})
    cap = f.capture()
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[cap]))
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=cap)

    r = _post_webhook(api, f.webhook_event("PAYMENT.CAPTURE.COMPLETED", cap))
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    sent = json.loads(verify.calls[0].request.content)
    assert sent["webhook_id"] == "WH-TEST-123" and sent["transmission_id"] == f.SIG_HEADERS["PAYPAL-TRANSMISSION-ID"]

    ev = db.scalar(select(WebhookEvent))
    assert ev.status == "PROCESSED" and ev.verified
    order = db.scalar(select(Order))
    assert order.payment_state == "PAYMENT_COMPLETED" and ev.order_id == order.id


def test_webhook_invalid_signature_rejected_and_audited(api, paypal_mock, db):  # AC1.3
    paypal_mock.post(VERIFY).respond(200, json={"verification_status": "FAILURE"})
    r = _post_webhook(api, f.webhook_event("PAYMENT.CAPTURE.COMPLETED", f.capture()))
    assert r.status_code == 400
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 0
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    actions = db.scalars(select(AuditLog.action)).all()
    assert "SECURITY_WEBHOOK_SIGNATURE_INVALID" in actions


def test_webhook_missing_headers_rejected_without_calling_paypal(api, paypal_mock, db):
    verify = paypal_mock.post(VERIFY).respond(200, json={"verification_status": "SUCCESS"})
    r = _post_webhook(api, f.webhook_event("PAYMENT.CAPTURE.COMPLETED", f.capture()), headers={})
    assert r.status_code == 400 and verify.call_count == 0


def test_webhook_replayed_three_times_is_processed_once(api, paypal_mock, db):  # AC1.2
    paypal_mock.post(VERIFY).respond(200, json={"verification_status": "SUCCESS"})
    cap = f.capture()
    order_route = paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[cap]))
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=cap)

    event = f.webhook_event("PAYMENT.CAPTURE.COMPLETED", cap, event_id="WH-DUP-1")
    outcomes = [_post_webhook(api, event).json()["status"] for _ in range(3)]

    assert outcomes == ["accepted", "duplicate", "duplicate"]
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 1
    assert order_route.call_count == 1  # processed (reconciled) exactly once


def test_out_of_order_events_end_in_paypal_state(api, paypal_mock, db):
    """REFUNDED arrives before COMPLETED; re-fetch means final state = PayPal's (REFUNDED)."""
    paypal_mock.post(VERIFY).respond(200, json={"verification_status": "SUCCESS"})
    refunded = f.capture("REFUNDED")
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[refunded]))
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=refunded)

    refund_resource = {
        "id": "1JU08902781691411",
        "status": "COMPLETED",
        "links": [{"rel": "up", "method": "GET", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{f.CAPTURE_ID}"}],
    }
    _post_webhook(api, f.webhook_event("PAYMENT.CAPTURE.REFUNDED", refund_resource, "WH-R", "refund"))
    _post_webhook(api, f.webhook_event("PAYMENT.CAPTURE.COMPLETED", f.capture("COMPLETED"), "WH-C"))

    order = db.scalar(select(Order))
    assert order.payment_state == "REFUNDED"
    assert {e.status for e in db.scalars(select(WebhookEvent))} == {"PROCESSED"}


def test_dispute_event_is_stored_for_feature5(api, paypal_mock, db):
    paypal_mock.post(VERIFY).respond(200, json={"verification_status": "SUCCESS"})
    ev = f.webhook_event("CUSTOMER.DISPUTE.CREATED", {"dispute_id": "PP-D-1"}, "WH-D", "dispute")
    assert _post_webhook(api, ev).status_code == 200
    assert db.scalar(select(WebhookEvent)).status == "STORED"


def test_failed_processing_can_be_reprocessed(api, paypal_mock, db):
    paypal_mock.post(VERIFY).respond(200, json={"verification_status": "SUCCESS"})
    cap = f.capture()
    order_route = paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}")
    order_route.side_effect = [httpx.Response(400, json={"name": "INVALID_REQUEST"}), httpx.Response(200, json=f.order(captures=[cap]))]
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=cap)

    _post_webhook(api, f.webhook_event("PAYMENT.CAPTURE.COMPLETED", cap, "WH-F"))
    assert db.scalar(select(WebhookEvent)).status == "FAILED"

    r = api.post("/api/admin/webhooks/reprocess")
    assert r.status_code == 200 and len(r.json()["reprocessed"]) == 1
    db.expire_all()
    assert db.scalar(select(WebhookEvent)).status == "PROCESSED"
    assert db.scalar(select(Order)).payment_state == "PAYMENT_COMPLETED"


def test_paypal_down_returns_sys02(api, paypal_mock):
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(503)
    r = api.post("/api/orders/sync", json={"paypal_order_id": f.ORDER_ID})
    assert r.status_code == 503 and r.json()["error_code"] == "SYS-02"
