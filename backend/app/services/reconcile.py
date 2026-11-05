"""Reconciliation: PayPal is the source of truth (PRD §6.3 principle 2).

`reconcile_order` re-fetches the order and each capture from PayPal and upserts
orders / captures / protected_addresses. Idempotent: running it twice with the same
PayPal state changes nothing and writes no extra audit rows.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    Actor,
    Capture,
    Order,
    PaymentState,
    ProtectedAddress,
)
from app.services.audit import audit
from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError
from app.services.paypal.orders import get_order
from app.services.paypal.payments import get_capture

# capture.status -> payment_state
CAPTURE_STATUS_MAP: dict[str, PaymentState] = {
    "COMPLETED": PaymentState.PAYMENT_COMPLETED,
    "PENDING": PaymentState.PAYMENT_PENDING,
    "DECLINED": PaymentState.PAYMENT_FAILED,
    "FAILED": PaymentState.PAYMENT_FAILED,
    "PARTIALLY_REFUNDED": PaymentState.PARTIALLY_REFUNDED,
    "REFUNDED": PaymentState.REFUNDED,
    "REVERSED": PaymentState.REVERSED,  # VERIFY: see docs/VERIFICATION.md
}

# Order status when no capture exists yet
ORDER_STATUS_MAP: dict[str, PaymentState] = {
    "VOIDED": PaymentState.PAYMENT_FAILED,
}


def map_payment_state(order_status: str | None, capture_status: str | None) -> PaymentState:
    if capture_status:
        return CAPTURE_STATUS_MAP.get(capture_status.upper(), PaymentState.PAYMENT_PENDING)
    return ORDER_STATUS_MAP.get((order_status or "").upper(), PaymentState.PAYMENT_PENDING)


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None


def extract_shipping(purchase_unit: dict[str, Any]) -> dict[str, str | None] | None:
    shipping = purchase_unit.get("shipping") or {}
    addr = shipping.get("address") or {}
    if not addr:
        return None
    return {
        "name": (shipping.get("name") or {}).get("full_name"),
        "line1": addr.get("address_line_1"),
        "line2": addr.get("address_line_2"),
        "city": addr.get("admin_area_2"),
        "state": addr.get("admin_area_1"),
        "postal_code": addr.get("postal_code"),
        "country": addr.get("country_code"),
    }


def _buyer(order_data: dict[str, Any]) -> tuple[str | None, str | None]:
    payer = order_data.get("payer") or {}
    pp = (order_data.get("payment_source") or {}).get("paypal") or {}
    name = payer.get("name") or pp.get("name") or {}
    full = " ".join(p for p in [name.get("given_name"), name.get("surname")] if p) or None
    email = payer.get("email_address") or pp.get("email_address")
    return full, mask_email(email)


def _upsert_capture(db: Session, order: Order, cap: dict[str, Any]) -> tuple[Capture, list[str]]:
    """Insert or update one capture row. Returns (row, list of changed fields)."""
    sp = cap.get("seller_protection") or {}
    amount = cap.get("amount") or {}
    values = {
        "status": cap.get("status") or "UNKNOWN",
        "status_reason": (cap.get("status_details") or {}).get("reason"),
        "amount": _decimal(amount.get("value")),
        "currency": amount.get("currency_code"),
        "seller_protection_status": sp.get("status") or "UNKNOWN",
        "dispute_categories": sp.get("dispute_categories"),
        "paypal_create_time": cap.get("create_time"),
    }
    row = db.scalar(select(Capture).where(Capture.paypal_capture_id == cap["id"]))
    changed: list[str] = []
    if row is None:
        row = Capture(order_id=order.id, paypal_capture_id=cap["id"], **values)
        order.captures.append(row)
        changed = ["created"]
    else:
        for k, v in values.items():
            if getattr(row, k) != v:
                setattr(row, k, v)
                changed.append(k)
    row.raw = cap
    row.fetched_at = utcnow()
    return row, changed


def _sync_address(db: Session, order: Order, shipping: dict[str, str | None] | None, paypal_order_id: str,
                  source: str = "PAYPAL_ORDER") -> bool:
    """Create a new protected-address version if PayPal's address differs. Returns True if changed."""
    if shipping is None:
        return False
    current = order.active_address
    if current is not None and current.fields() == shipping:
        return False
    next_version = max((a.version for a in order.addresses), default=0) + 1
    for a in order.addresses:
        a.is_active = False
    order.addresses.append(
        ProtectedAddress(
            order_id=order.id,
            source=source,
            paypal_order_id=paypal_order_id,
            version=next_version,
            is_active=True,
            **shipping,
        )
    )
    # PII minimisation: audit only city/state/country
    audit(
        db,
        order.id,
        Actor.PAYPAL,
        "PROTECTED_ADDRESS_RECORDED",
        {
            "version": next_version,
            "source": source,
            "city": shipping.get("city"),
            "state": shipping.get("state"),
            "country": shipping.get("country"),
        },
    )
    return True


def reconcile_order(
    db: Session,
    client: PayPalClient,
    paypal_order_id: str,
    *,
    actor: str = Actor.SYSTEM,
    reason: str = "reconcile",
) -> Order:
    """Fetch the order + captures from PayPal and upsert local state. Commits."""
    order_data = get_order(client, paypal_order_id)
    units = order_data.get("purchase_units") or [{}]
    unit = units[0]

    order = db.scalar(select(Order).where(Order.paypal_order_id == paypal_order_id))
    if order is None:  # a Safe re-pay order belongs to the original StayCovered order
        order = db.scalar(select(Order).where(Order.current_paypal_order_id == paypal_order_id))
    created = order is None
    if order is None:
        order = Order(paypal_order_id=paypal_order_id)
        db.add(order)
        db.flush()

    amount = unit.get("amount") or {}
    buyer_name, buyer_email = _buyer(order_data)
    order.paypal_status = order_data.get("status")
    order.amount = _decimal(amount.get("value"))
    order.currency = amount.get("currency_code")
    order.item_description = unit.get("description") or (
        (unit.get("items") or [{}])[0].get("name")
    )
    order.buyer_name = buyer_name or order.buyer_name
    order.buyer_email_masked = buyer_email or order.buyer_email_masked
    order.paypal_create_time = order_data.get("create_time")

    # Captures: always re-fetch each one (never trust embedded/webhook state alone)
    capture_refs = ((unit.get("payments") or {}).get("captures")) or []
    for ref in capture_refs:
        try:
            cap = get_capture(client, ref["id"])
        except PayPalError as exc:
            if exc.status_code != 404:
                raise
            cap = ref  # fall back to the order's embedded copy
        row, changed = _upsert_capture(db, order, cap)
        if changed:
            audit(
                db,
                order.id,
                Actor.PAYPAL,
                "CAPTURE_SYNCED",
                {
                    "capture_id": row.paypal_capture_id,
                    "status": row.status,
                    "seller_protection": row.seller_protection_status,
                    "changed": changed,
                },
            )

    is_repay = order.paypal_order_id != paypal_order_id
    repay_paid = is_repay and any((c.get("status") == "COMPLETED") for c in capture_refs)
    current_id = order.current_paypal_order_id or order.paypal_order_id
    superseded_original = not is_repay and current_id != paypal_order_id  # original order after a re-pay
    if (not is_repay and not superseded_original) or repay_paid:
        # A re-pay order's preset address only becomes the protected address once the buyer has paid it.
        _sync_address(db, order, extract_shipping(unit), paypal_order_id, source="PAYPAL_REPAY" if is_repay else "PAYPAL_ORDER")
    if repay_paid:
        from app.workflows.remediation import mark_repay_paid  # local import: avoids a cycle

        mark_repay_paid(db, order, paypal_order_id)

    latest = order.latest_capture
    new_state = map_payment_state(order.paypal_status, latest.status if latest else None)
    if created:
        order.payment_state = new_state
        audit(
            db,
            order.id,
            actor,
            "ORDER_CREATED",
            {"paypal_order_id": paypal_order_id, "payment_state": new_state, "source": reason},
        )
    elif order.payment_state != new_state:
        audit(
            db,
            order.id,
            actor,
            "PAYMENT_STATE_CHANGED",
            {"from": order.payment_state, "to": new_state, "source": reason},
        )
        order.payment_state = new_state

    order.last_synced_at = utcnow()
    db.commit()
    from app.config import get_settings
    from app.workflows.verification import evaluate_safely  # local import: avoids a cycle

    evaluate_safely(db, get_settings(), order.id, f"PayPal sync ({reason})")
    db.refresh(order)
    return order


def find_order_id_for_capture(db: Session, client: PayPalClient, capture_id: str) -> str | None:
    """Map a capture ID to its PayPal order ID (DB first, then PayPal)."""
    row = db.scalar(select(Capture).where(Capture.paypal_capture_id == capture_id))
    if row is not None:
        return row.order.paypal_order_id
    cap = get_capture(client, capture_id)
    return ((cap.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
