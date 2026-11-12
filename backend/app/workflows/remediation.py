"""Safe fix workflow (F4).

SHIP_TO_PROTECTED: record the choice + draft a buyer message; the seller re-labels to the PayPal address.
REPAY (money moves -> explicit seller confirmation required):
  PENDING_CONFIRMATION --confirm(code)--> refund original capture (stable request id: one refund even on double click)
     refund fails            -> REFUND_FAILED (no new order is created)
     new order creation fails -> REFUNDED_AWAITING_NEW_ORDER (retry button)
     success                 -> AWAITING_BUYER_PAYMENT (approve link for the buyer)
  buyer pays new order -> reconciliation records a new protected-address version -> COMPLETED -> verdict re-runs
"""
from __future__ import annotations

import re
import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agents import remediation_assistant as ra
from app.ai.provider import Provider
from app.config import Settings
from app.db import utcnow
from app.errors import AppError
from app.models import (
    Actor,
    Order,
    Remediation,
    RemediationStatus,
    RemediationType,
)
from app.services.audit import audit
from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError
from app.services.paypal.orders import build_order_body, create_order
from app.services.paypal.payments import refund_capture
from app.workflows.verification import active_decision

US_STATE = re.compile(r"^[A-Z]{2}$")
US_ZIP = re.compile(r"^\d{5}(-\d{4})?$")
FIXABLE = {"ADD-03", "ADD-12", "ADD-04", "ADD-05", "ADD-06", "ADD-08"}


def validate_address(addr: dict[str, Any] | None) -> dict[str, str | None]:
    if not addr:
        raise AppError("ADDRESS_REQUIRED", "Enter the new shipping address.", 422)
    clean = {k: (str(addr.get(k) or "").strip() or None) for k in ("name", "line1", "line2", "city", "state", "postal_code", "country")}
    clean["state"] = (clean["state"] or "").upper() or None
    clean["country"] = (clean["country"] or "US").upper()
    missing = [k for k in ("name", "line1", "city", "state", "postal_code") if not clean[k]]
    if missing:
        raise AppError("ADDRESS_INCOMPLETE", "The new address is incomplete.", 422, {"missing": missing})
    if clean["country"] != "US":
        raise AppError("ADDRESS_UNSUPPORTED", "Safe re-pay currently supports US addresses only.", 422)
    if not US_STATE.match(clean["state"] or "") or not US_ZIP.match(clean["postal_code"] or ""):
        raise AppError("ADDRESS_INVALID", "Use a 2-letter US state and a 5-digit ZIP code.", 422)
    return clean


# "Emily Carter, 500 Congress Ave, Apt 2, Austin, TX 78701" (name and unit optional). Only used to PREFILL a form
# the seller reviews; it never feeds the verdict.
_US_ADDR = re.compile(
    r"(?:(?P<name>(?-i:[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}))\s*,\s*)?"
    r"(?P<line1>\d+[A-Za-z]?\s+[^,\n]+?)\s*,\s*"
    r"(?:(?P<line2>(?:apt|apartment|unit|suite|ste|#)\.?\s*[^,\n]*?)\s*,\s*)?"
    r"(?P<city>[A-Za-z][A-Za-z .'-]*?)\s*,?\s+(?P<state>[A-Z]{2})\s+(?P<postal_code>\d{5}(?:-\d{4})?)\b",
    re.IGNORECASE,
)
_ADDR_KEYS = ("line1", "line2", "city", "state", "postal_code")


def parse_us_addresses(text: str | None) -> list[dict[str, str | None]]:
    out = []
    for m in _US_ADDR.finditer(text or ""):
        d = {k: (m.group(k) or "").strip() or None for k in ("name", *_ADDR_KEYS)}
        d["state"] = (d["state"] or "").upper() or None
        out.append(d)
    return out


def _same_place(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Do two partial addresses plausibly describe the same destination (city/state/ZIP agree where both given)?"""
    shared = False
    for k in ("city", "state", "postal_code"):
        x, y = (a.get(k) or "").strip().lower(), (b.get(k) or "").strip().lower()
        if x and y:
            if x != y:
                return False
            shared = True
    return shared


def suggested_address(db: Session, order: Order) -> dict[str, Any] | None:
    """Prefill from the buyer's request in the chat (ADD-03 source), if the AI extracted one.

    In screenshots the buyer often says "ship it to my friend in Austin" and gives the full address in the NEXT
    message, so the AI's `requested_address` may hold only city/state. Missing parts (street, ZIP, recipient name)
    are back-filled from the full addresses written in the chat — only when they describe the same place.
    """
    from app.workflows.extraction import latest_extractions

    for ex in latest_extractions(db, order.id).get("conversation_analyst", []):
        out = ex.output or {}
        texts = [m.get("text") for m in out.get("addresses_mentioned", [])] + [r.get("quote") for r in out.get("requests", [])]
        parsed = [p for t in texts for p in parse_us_addresses(t)]
        for req in out.get("requests", []):
            if req.get("type") != "ADDRESS_CHANGE" or req.get("status") == "CANCELLED":
                continue
            a: dict[str, Any] = {k: (req.get("requested_address") or {}).get(k) for k in _ADDR_KEYS}
            a["name"] = None
            for p in parsed:
                if not any(a[k] for k in ("city", "state", "postal_code")) or _same_place(a, p):
                    for k in ("name", *_ADDR_KEYS):
                        a[k] = a[k] or p[k]
            if a.get("city"):
                return {"name": a["name"], **{k: a[k] for k in _ADDR_KEYS},
                        "country": (req.get("requested_address") or {}).get("country") or "US"}
    return None


def start(db: Session, settings: Settings, provider: Provider | None, order_id: str, fix_type: str,
          requested_address: dict[str, Any] | None) -> Remediation:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    decision = active_decision(db, order.id)
    if decision is None or not ({f.code for f in decision.flags} & FIXABLE):
        raise AppError("NOTHING_TO_FIX", "There is no address problem to fix on this order.", 409)
    if fix_type not in (RemediationType.SHIP_TO_PROTECTED, RemediationType.REPAY):
        raise AppError("BAD_FIX_TYPE", "Unknown fix type.", 422)
    open_repay = db.scalar(select(Remediation).where(
        Remediation.order_id == order.id, Remediation.type == RemediationType.REPAY,
        Remediation.status.in_([RemediationStatus.PENDING_CONFIRMATION, RemediationStatus.REFUNDED_AWAITING_NEW_ORDER,
                                RemediationStatus.AWAITING_BUYER_PAYMENT])))
    if open_repay is not None:
        return open_repay  # never two parallel re-pays for one order

    protected = order.active_address
    item = order.item_description or "order"
    rem = Remediation(order_id=order.id, type=fix_type)
    if fix_type == RemediationType.REPAY:
        if order.payment_state != "PAYMENT_COMPLETED" or order.latest_capture is None:
            raise AppError("NOT_REFUNDABLE", "Safe re-pay needs a completed PayPal payment to refund.", 409)
        addr = validate_address(requested_address)
        rem.status = RemediationStatus.PENDING_CONFIRMATION
        rem.requested_address = addr
        rem.original_capture_id = order.latest_capture.paypal_capture_id
        rem.refund_amount = order.latest_capture.amount or order.amount
        rem.confirmation_code = secrets.token_hex(3).upper()
        place = f"{addr['city']}, {addr['state']}"
    else:
        rem.status = RemediationStatus.DRAFTED
        place = None
    msg, source = ra.draft(provider, fix=fix_type, item=item, protected_city=(protected.city if protected else "your PayPal address"),
                           requested_place=place, pay_link=None)
    rem.buyer_message_subject, rem.buyer_message, rem.message_source = msg.subject, msg.message, source
    db.add(rem)
    db.flush()
    audit(db, order.id, Actor.SELLER, "REMEDIATION_STARTED", {
        "remediation_id": rem.id, "type": fix_type, "message_source": source,
        "new_city": (rem.requested_address or {}).get("city"), "new_state": (rem.requested_address or {}).get("state"),
    })
    db.commit()
    return rem


def _create_new_order(db: Session, settings: Settings, client: PayPalClient, order: Order, rem: Remediation) -> None:
    a = rem.requested_address or {}
    origin = settings.FRONTEND_ORIGIN.rstrip("/")
    body = build_order_body(
        item_name=order.item_description or "Order",
        item_sku="NECKLACE-SILVER-01",
        unit_amount=Decimal(rem.refund_amount or order.amount or 0),
        currency=order.currency or "USD",
        brand_name="StayCovered Demo Shop",
        return_url=f"{origin}/pay/return",
        cancel_url=f"{origin}/pay/return?status=cancel",
        shipping_preference="SET_PROVIDED_ADDRESS",
        shipping={
            "name": {"full_name": a.get("name")},
            "address": {k2: v for k2, v in {
                "address_line_1": a.get("line1"), "address_line_2": a.get("line2"), "admin_area_2": a.get("city"),
                "admin_area_1": a.get("state"), "postal_code": a.get("postal_code"), "country_code": a.get("country") or "US",
            }.items() if v},
        },
    )
    created = create_order(client, body, request_id=f"repay-order-{rem.id}")
    rem.new_paypal_order_id = created["id"]
    rem.approve_url = next((l["href"] for l in created.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)
    rem.status = RemediationStatus.AWAITING_BUYER_PAYMENT
    rem.error = None
    order.current_paypal_order_id = created["id"]
    msg, source = ra.draft(None, fix="REPAY", item=order.item_description or "order",
                           protected_city=a.get("city") or "", requested_place=f"{a.get('city')}, {a.get('state')}",
                           pay_link=f"{origin}/pay/{created['id']}")
    rem.buyer_message_subject, rem.buyer_message = msg.subject, msg.message
    rem.message_source = rem.message_source if rem.message_source == "AI" else source
    audit(db, order.id, Actor.PAYPAL, "REPAY_ORDER_CREATED", {"remediation_id": rem.id, "new_paypal_order_id": created["id"],
                                                             "city": a.get("city"), "state": a.get("state")})


def confirm(db: Session, settings: Settings, client: PayPalClient, remediation_id: str, code: str) -> Remediation:
    rem = db.get(Remediation, remediation_id)
    if rem is None:
        raise AppError("REMEDIATION_NOT_FOUND", "Fix not found.", 404)
    if rem.type != RemediationType.REPAY:
        raise AppError("NOTHING_TO_CONFIRM", "Only Safe re-pay needs confirmation.", 409)
    if rem.status != RemediationStatus.PENDING_CONFIRMATION:
        return rem  # double click / retry: already processed -> no second refund
    if not code or code.strip().upper() != rem.confirmation_code:
        raise AppError("CONFIRMATION_MISMATCH", "Type the confirmation code shown in the dialog.", 422)
    order = db.get(Order, rem.order_id)
    rem.confirmed_at = utcnow()
    audit(db, order.id, Actor.SELLER, "REPAY_CONFIRMED", {"remediation_id": rem.id, "refund_amount": str(rem.refund_amount)})
    db.commit()

    # 1) refund (stable request id -> PayPal returns the same refund on retries)
    try:
        refund = refund_capture(client, rem.original_capture_id, request_id=f"repay-refund-{rem.id}",
                                note_to_payer="Refunded so we can ship to your new address via a new PayPal payment.",
                                order_id=order.id)
    except PayPalError as exc:
        rem.status = RemediationStatus.REFUND_FAILED
        rem.error, rem.paypal_debug_id = exc.human_message(), exc.debug_id
        audit(db, order.id, Actor.PAYPAL, "REPAY_REFUND_FAILED", {"remediation_id": rem.id, "debug_id": exc.debug_id, "issues": exc.issues})
        db.commit()
        raise AppError("REFUND_FAILED", f"PayPal refused the refund: {exc.human_message()}", 502, exc.public_details()) from exc
    rem.refund_id, rem.refund_status = refund.get("id"), refund.get("status")
    rem.status = RemediationStatus.REFUNDED_AWAITING_NEW_ORDER
    audit(db, order.id, Actor.PAYPAL, "REPAY_REFUNDED", {"remediation_id": rem.id, "refund_id": rem.refund_id, "status": rem.refund_status})
    db.commit()

    # refresh the original payment state (-> REFUNDED, which re-runs the verdict: PAY-05 RED)
    from app.services.reconcile import reconcile_order

    try:
        reconcile_order(db, client, order.paypal_order_id, actor=Actor.PAYPAL, reason="re-pay refund")
    except PayPalError:
        pass

    # 2) new order with the requested address preset
    try:
        _create_new_order(db, settings, client, order, rem)
    except PayPalError as exc:
        rem.error, rem.paypal_debug_id = exc.human_message(), exc.debug_id
        audit(db, order.id, Actor.PAYPAL, "REPAY_ORDER_FAILED", {"remediation_id": rem.id, "debug_id": exc.debug_id})
    db.commit()
    db.refresh(rem)
    return rem


def retry_new_order(db: Session, settings: Settings, client: PayPalClient, remediation_id: str) -> Remediation:
    rem = db.get(Remediation, remediation_id)
    if rem is None:
        raise AppError("REMEDIATION_NOT_FOUND", "Fix not found.", 404)
    if rem.status != RemediationStatus.REFUNDED_AWAITING_NEW_ORDER:
        return rem
    order = db.get(Order, rem.order_id)
    try:
        _create_new_order(db, settings, client, order, rem)
    except PayPalError as exc:
        rem.error, rem.paypal_debug_id = exc.human_message(), exc.debug_id
        db.commit()
        raise AppError("REPAY_ORDER_FAILED", f"PayPal could not create the new payment: {exc.human_message()}", 502, exc.public_details()) from exc
    db.commit()
    db.refresh(rem)
    return rem


def mark_repay_paid(db: Session, order: Order, paypal_order_id: str) -> None:
    """Called by reconciliation when the buyer has paid the re-pay order."""
    rem = db.scalar(select(Remediation).where(Remediation.new_paypal_order_id == paypal_order_id))
    if rem is None or rem.status == RemediationStatus.COMPLETED:
        return
    rem.status = RemediationStatus.COMPLETED
    audit(db, order.id, Actor.PAYPAL, "REPAY_PAID", {"remediation_id": rem.id, "new_paypal_order_id": paypal_order_id})
