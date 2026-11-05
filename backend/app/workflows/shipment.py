"""Shipment registration with PayPal tracking (F4).

Gates (all must pass): active verdict GREEN / acknowledged YELLOW / overridden RED; payment COMPLETED;
latest capture COMPLETED; tracking number valid for the carrier; not used on another order (SHP-04).
Idempotent: the same capture + tracking number returns the existing shipment (one PayPal call per parcel).
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.errors import AppError
from app.models import Actor, Order, Shipment, ShipmentState
from app.services.audit import audit
from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError
from app.services.paypal.tracking import CARRIERS, add_tracking, cancel_tracker, find_tracker
from app.workflows.verification import active_decision, shipping_allowed

# Basic per-carrier formats (deliberately permissive; they catch obvious typos only).
TRACKING_FORMATS = {
    "USPS": re.compile(r"^(\d{20,22}|9\d{15,21}|[A-Z]{2}\d{9}US)$"),
    "UPS": re.compile(r"^1Z[0-9A-Z]{16}$"),
    "FEDEX": re.compile(r"^(\d{12}|\d{15}|\d{20}|\d{22})$"),
    "DHL": re.compile(r"^(\d{10,11}|[A-Z0-9]{10,39})$"),
}
GENERIC = re.compile(r"^[A-Z0-9]{6,40}$")


def normalize_tracking(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw or "").upper()


def validate_tracking(carrier: str, number: str) -> None:
    pattern = TRACKING_FORMATS.get(carrier, GENERIC)
    if not pattern.match(number):
        raise AppError("TRACKING_INVALID", f"That doesn't look like a valid {CARRIERS.get(carrier, carrier)} tracking number.", 422,
                       {"carrier": carrier})


def register(db: Session, client: PayPalClient, order_id: str, *, carrier: str, tracking_number: str,
             carrier_name_other: str | None = None, ship_date: str | None = None, notify_payer: bool = True) -> Shipment:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    carrier = (carrier or "").upper()
    if carrier not in CARRIERS:
        raise AppError("CARRIER_UNSUPPORTED", "Choose a carrier from the list, or 'Other'.", 422)
    if carrier == "OTHER" and not (carrier_name_other or "").strip():
        raise AppError("CARRIER_NAME_REQUIRED", "Enter the carrier's name.", 422)
    number = normalize_tracking(tracking_number)
    validate_tracking(carrier, number)  # SHP-01: a tracking number is required to mark shipped
    if ship_date:
        try:
            date.fromisoformat(ship_date)
        except ValueError as exc:
            raise AppError("SHIP_DATE_INVALID", "Ship date must be YYYY-MM-DD.", 422) from exc

    cap = order.latest_capture
    if order.payment_state != "PAYMENT_COMPLETED" or cap is None or cap.status != "COMPLETED":
        raise AppError("CAPTURE_NOT_COMPLETED", "Tracking can only be added to a completed PayPal payment.", 409,
                       {"payment_state": order.payment_state})

    # idempotent: same capture + tracking -> existing record, no second PayPal call
    existing = db.scalar(select(Shipment).where(Shipment.tracking_number == number, Shipment.carrier == carrier))
    if existing is not None:
        if existing.order_id != order.id:
            raise AppError("SHP-04", "This tracking number already belongs to another order.", 409)
        if existing.capture_id == cap.paypal_capture_id:
            return existing

    decision = active_decision(db, order.id)
    ok, why = shipping_allowed(decision)
    if not ok:
        raise AppError("SHIPPING_NOT_ALLOWED", why, 409, {"verdict": decision.verdict if decision else None})

    paypal_order_id = order.current_paypal_order_id or order.paypal_order_id
    try:
        resp = add_tracking(client, paypal_order_id, capture_id=cap.paypal_capture_id, tracking_number=number, carrier=carrier,
                            carrier_name_other=(carrier_name_other or "").strip() or None, notify_payer=notify_payer,
                            items=[{"name": order.item_description or "Item", "quantity": "1"}],
                            request_id=f"track-{cap.paypal_capture_id}-{number}", order_id=order.id)
    except PayPalError as exc:
        audit(db, order.id, Actor.PAYPAL, "TRACKING_FAILED", {"carrier": carrier, "debug_id": exc.debug_id, "issues": exc.issues})
        db.commit()
        raise AppError("TRACKING_FAILED", f"PayPal did not accept the tracking: {exc.human_message()}", 502, exc.public_details()) from exc

    tracker = find_tracker(resp, cap.paypal_capture_id, number) or {}
    basis = "GREEN" if decision.verdict == "GREEN" else decision.resolution
    ship = Shipment(order_id=order.id, paypal_order_id=paypal_order_id, capture_id=cap.paypal_capture_id, carrier=carrier,
                    carrier_name_other=(carrier_name_other or None) if carrier == "OTHER" else None, tracking_number=number,
                    ship_date=ship_date or date.today().isoformat(), notify_payer=notify_payer,
                    paypal_tracker_id=tracker.get("id") or f"{cap.paypal_capture_id}-{number}",
                    status=ShipmentState.SHIPPED, decision_id=decision.id, decision_basis=basis,
                    registered_at=utcnow(), raw={"tracker": tracker, "order_status": resp.get("status")})
    db.add(ship)
    order.shipment_state = ShipmentState.SHIPPED
    audit(db, order.id, Actor.PAYPAL, "TRACKING_REGISTERED", {
        "carrier": carrier, "tracking_number": number, "tracker_id": ship.paypal_tracker_id, "basis": basis,
    })
    db.commit()
    db.refresh(ship)
    return ship


def update_status(db: Session, client: PayPalClient, shipment_id: str, status: str) -> Shipment:
    ship = db.get(Shipment, shipment_id)
    if ship is None:
        raise AppError("SHIPMENT_NOT_FOUND", "Shipment not found.", 404)
    status = status.upper()
    if status not in (ShipmentState.CANCELLED, ShipmentState.DELIVERED):
        raise AppError("STATUS_UNSUPPORTED", "Status can be set to CANCELLED or DELIVERED.", 422)
    if ship.status == status:
        return ship
    note = None
    if status == ShipmentState.CANCELLED:
        try:
            cancel_tracker(client, ship.paypal_order_id, ship.paypal_tracker_id, order_id=ship.order_id)
        except PayPalError as exc:
            raise AppError("TRACKER_UPDATE_FAILED", f"PayPal did not cancel the tracker: {exc.human_message()}", 502, exc.public_details()) from exc
    else:
        note = "seller-reported (PayPal's tracker API only supports CANCELLED)"
    ship.status = status
    order = db.get(Order, ship.order_id)
    others = [s for s in db.scalars(select(Shipment).where(Shipment.order_id == order.id)) if s.id != ship.id]
    if status == ShipmentState.DELIVERED:
        order.shipment_state = ShipmentState.DELIVERED
    elif not any(s.status in (ShipmentState.SHIPPED, ShipmentState.DELIVERED) for s in others):
        order.shipment_state = ShipmentState.CANCELLED
    audit(db, order.id, Actor.SELLER, "SHIPMENT_STATUS_CHANGED", {"shipment_id": ship.id, "status": status, "note": note})
    db.commit()
    db.refresh(ship)
    return ship
