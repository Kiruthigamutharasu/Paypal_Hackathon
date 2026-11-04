import copy

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Capture, Order, PaymentState, ProtectedAddress
from app.services.reconcile import map_payment_state, mask_email, reconcile_order
from tests import factories as f


@pytest.mark.parametrize(
    "order_status,capture_status,expected",
    [
        ("COMPLETED", "COMPLETED", PaymentState.PAYMENT_COMPLETED),
        ("COMPLETED", "PENDING", PaymentState.PAYMENT_PENDING),
        ("COMPLETED", "DECLINED", PaymentState.PAYMENT_FAILED),
        ("COMPLETED", "FAILED", PaymentState.PAYMENT_FAILED),
        ("COMPLETED", "PARTIALLY_REFUNDED", PaymentState.PARTIALLY_REFUNDED),
        ("COMPLETED", "REFUNDED", PaymentState.REFUNDED),
        ("COMPLETED", "REVERSED", PaymentState.REVERSED),
        ("APPROVED", None, PaymentState.PAYMENT_PENDING),
        ("PAYER_ACTION_REQUIRED", None, PaymentState.PAYMENT_PENDING),
        ("VOIDED", None, PaymentState.PAYMENT_FAILED),
    ],
)
def test_status_mapping(order_status, capture_status, expected):
    assert map_payment_state(order_status, capture_status) == expected


def test_mask_email():
    assert mask_email("jane.buyer@personal.example.com") == "j***@personal.example.com"
    assert mask_email(None) is None


def _mock_paypal(paypal_mock, order_body, capture_body):
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=order_body)
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=capture_body)


def test_reconcile_creates_order_capture_and_protected_address(db, paypal_mock, client_pp):  # AC1.1
    cap = f.capture()
    _mock_paypal(paypal_mock, f.order(captures=[cap]), cap)
    o = reconcile_order(db, client_pp, f.ORDER_ID)

    assert o.payment_state == PaymentState.PAYMENT_COMPLETED
    assert o.latest_capture.seller_protection_status == "ELIGIBLE"
    assert o.latest_capture.dispute_categories == ["ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"]
    addr = o.active_address
    assert (addr.line1, addr.line2, addr.city, addr.state, addr.postal_code, addr.country) == (
        "123 Main St", "Apt 4B", "New York", "NY", "10001", "US",
    )
    assert addr.version == 1
    assert o.buyer_email_masked == "j***@personal.example.com"


def test_reconcile_is_idempotent(db, paypal_mock, client_pp):
    cap = f.capture()
    _mock_paypal(paypal_mock, f.order(captures=[cap]), cap)
    reconcile_order(db, client_pp, f.ORDER_ID)
    audits_before = db.scalar(select(func.count()).select_from(AuditLog))
    reconcile_order(db, client_pp, f.ORDER_ID)
    reconcile_order(db, client_pp, f.ORDER_ID)

    assert db.scalar(select(func.count()).select_from(Order)) == 1
    assert db.scalar(select(func.count()).select_from(Capture)) == 1
    assert db.scalar(select(func.count()).select_from(ProtectedAddress)) == 1
    assert db.scalar(select(func.count()).select_from(AuditLog)) == audits_before


def test_missing_seller_protection_is_stored_as_unknown(db, paypal_mock, client_pp):
    cap = f.capture(seller_protection=None)
    _mock_paypal(paypal_mock, f.order(captures=[cap]), cap)
    o = reconcile_order(db, client_pp, f.ORDER_ID)
    assert o.latest_capture.seller_protection_status == "UNKNOWN"


def test_address_change_creates_new_version(db, paypal_mock, client_pp):
    cap = f.capture()
    _mock_paypal(paypal_mock, f.order(captures=[cap]), cap)
    reconcile_order(db, client_pp, f.ORDER_ID)

    new_ship = copy.deepcopy(f.NY_SHIPPING)
    new_ship["address"].update({"address_line_1": "500 Congress Ave", "address_line_2": None,
                                "admin_area_2": "Austin", "admin_area_1": "TX", "postal_code": "78701"})
    paypal_mock.get(f"/v2/checkout/orders/{f.ORDER_ID}").respond(200, json=f.order(captures=[cap], shipping=new_ship))
    o = reconcile_order(db, client_pp, f.ORDER_ID)

    assert o.active_address.version == 2 and o.active_address.city == "Austin"
    assert [a.is_active for a in o.addresses] == [False, True]


def test_payment_state_change_is_audited(db, paypal_mock, client_pp):
    cap = f.capture()
    _mock_paypal(paypal_mock, f.order(captures=[cap]), cap)
    reconcile_order(db, client_pp, f.ORDER_ID)
    paypal_mock.get(f"/v2/payments/captures/{f.CAPTURE_ID}").respond(200, json=f.capture("REFUNDED"))
    o = reconcile_order(db, client_pp, f.ORDER_ID)

    assert o.payment_state == PaymentState.REFUNDED
    actions = db.scalars(select(AuditLog.action).where(AuditLog.order_id == o.id)).all()
    assert "PAYMENT_STATE_CHANGED" in actions


def test_audit_never_contains_street_address(db, paypal_mock, client_pp):
    cap = f.capture()
    _mock_paypal(paypal_mock, f.order(captures=[cap]), cap)
    reconcile_order(db, client_pp, f.ORDER_ID)
    details = str(db.scalars(select(AuditLog.details)).all())
    assert "123 Main St" not in details and "10001" not in details
