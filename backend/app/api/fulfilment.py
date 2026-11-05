"""Safe fix (remediation), PayPal tracking and the buyer pay page (F4)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_ai_provider_factory, get_db, get_paypal_client, settings_dep
from app.errors import AppError
from app.models import Order, Remediation, Shipment
from app.services.paypal.client import PayPalClient
from app.services.paypal.orders import get_order
from app.services.paypal.tracking import CARRIERS
from app.workflows import remediation as rw
from app.workflows import shipment as sw

router = APIRouter(tags=["fulfilment"])


class RemediationIn(BaseModel):
    type: str = Field(pattern="^(SHIP_TO_PROTECTED|REPAY)$")
    requested_address: dict[str, Any] | None = None


class ConfirmIn(BaseModel):
    confirmation_code: str = Field(min_length=1, max_length=16)


class RemediationOut(BaseModel):
    id: str
    type: str
    status: str
    requested_address: dict[str, Any] | None
    refund_amount: Decimal | None
    refund_id: str | None
    refund_status: str | None
    new_paypal_order_id: str | None
    approve_url: str | None
    pay_page_path: str | None
    confirmation_code: str | None
    buyer_message_subject: str | None
    buyer_message: str | None
    message_source: str | None
    error: str | None
    paypal_debug_id: str | None
    confirmed_at: datetime | None
    created_at: datetime


class ShipmentIn(BaseModel):
    carrier: str
    tracking_number: str = Field(min_length=4, max_length=64)
    carrier_name_other: str | None = Field(default=None, max_length=64)
    ship_date: str | None = None
    notify_payer: bool = True


class ShipmentPatch(BaseModel):
    status: str


class ShipmentOut(BaseModel):
    id: str
    carrier: str
    carrier_name_other: str | None
    tracking_number: str
    ship_date: str | None
    notify_payer: bool
    paypal_tracker_id: str | None
    status: str
    decision_basis: str | None
    registered_at: datetime | None
    paypal_order_id: str


def rem_out(r: Remediation) -> RemediationOut:
    return RemediationOut(
        id=r.id, type=r.type, status=r.status, requested_address=r.requested_address, refund_amount=r.refund_amount,
        refund_id=r.refund_id, refund_status=r.refund_status, new_paypal_order_id=r.new_paypal_order_id, approve_url=r.approve_url,
        pay_page_path=f"/pay/{r.new_paypal_order_id}" if r.new_paypal_order_id else None,
        confirmation_code=r.confirmation_code if r.status == "PENDING_CONFIRMATION" else None,
        buyer_message_subject=r.buyer_message_subject, buyer_message=r.buyer_message, message_source=r.message_source,
        error=r.error, paypal_debug_id=r.paypal_debug_id, confirmed_at=r.confirmed_at, created_at=r.created_at,
    )


def ship_out(s: Shipment) -> ShipmentOut:
    return ShipmentOut(id=s.id, carrier=s.carrier, carrier_name_other=s.carrier_name_other, tracking_number=s.tracking_number,
                       ship_date=s.ship_date, notify_payer=s.notify_payer, paypal_tracker_id=s.paypal_tracker_id, status=s.status,
                       decision_basis=s.decision_basis, registered_at=s.registered_at, paypal_order_id=s.paypal_order_id)


def _order(db: Session, order_id: str) -> Order:
    o = db.get(Order, order_id)
    if o is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    return o


# ---------------- remediation ----------------
@router.get("/api/orders/{order_id}/remediations")
def list_remediations(order_id: str, db: Session = Depends(get_db)):
    order = _order(db, order_id)
    rows = db.scalars(select(Remediation).where(Remediation.order_id == order.id).order_by(Remediation.created_at.desc())).all()
    return {"remediations": [rem_out(r) for r in rows], "suggested_address": rw.suggested_address(db, order),
            "protected_name": order.active_address.name if order.active_address else None}


@router.post("/api/orders/{order_id}/remediations", response_model=RemediationOut)
def start_remediation(order_id: str, body: RemediationIn, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep),
                      provider_factory=Depends(get_ai_provider_factory)):
    try:
        provider = provider_factory()
    except Exception:  # no AI configured -> template message
        provider = None
    return rem_out(rw.start(db, settings, provider, order_id, body.type, body.requested_address))


@router.post("/api/remediations/{remediation_id}/confirm", response_model=RemediationOut)
def confirm_remediation(remediation_id: str, body: ConfirmIn, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep),
                        client: PayPalClient = Depends(get_paypal_client)):
    return rem_out(rw.confirm(db, settings, client, remediation_id, body.confirmation_code))


@router.post("/api/remediations/{remediation_id}/retry", response_model=RemediationOut)
def retry_remediation(remediation_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep),
                      client: PayPalClient = Depends(get_paypal_client)):
    return rem_out(rw.retry_new_order(db, settings, client, remediation_id))


# ---------------- shipments ----------------
@router.get("/api/carriers")
def carriers():
    return [{"code": k, "name": v} for k, v in CARRIERS.items()]


@router.get("/api/orders/{order_id}/shipments", response_model=list[ShipmentOut])
def list_shipments(order_id: str, db: Session = Depends(get_db)):
    order = _order(db, order_id)
    return [ship_out(s) for s in db.scalars(select(Shipment).where(Shipment.order_id == order.id).order_by(Shipment.created_at))]


@router.post("/api/orders/{order_id}/shipments", response_model=ShipmentOut)
def create_shipment(order_id: str, body: ShipmentIn, db: Session = Depends(get_db), client: PayPalClient = Depends(get_paypal_client)):
    return ship_out(sw.register(db, client, order_id, carrier=body.carrier, tracking_number=body.tracking_number,
                                carrier_name_other=body.carrier_name_other, ship_date=body.ship_date, notify_payer=body.notify_payer))


@router.patch("/api/shipments/{shipment_id}", response_model=ShipmentOut)
def patch_shipment(shipment_id: str, body: ShipmentPatch, db: Session = Depends(get_db), client: PayPalClient = Depends(get_paypal_client)):
    return ship_out(sw.update_status(db, client, shipment_id, body.status))


# ---------------- buyer pay page for a re-pay order ----------------
@router.get("/api/shop/pay/{paypal_order_id}")
def pay_page_info(paypal_order_id: str, db: Session = Depends(get_db), client: PayPalClient = Depends(get_paypal_client)):
    rem = db.scalar(select(Remediation).where(Remediation.new_paypal_order_id == paypal_order_id))
    if rem is None:
        raise AppError("PAY_LINK_NOT_FOUND", "This payment link is not valid.", 404)
    order = db.get(Order, rem.order_id)
    pp = get_order(client, paypal_order_id)
    a = rem.requested_address or {}
    return {
        "paypal_order_id": paypal_order_id,
        "status": pp.get("status"),
        "item": order.item_description,
        "amount": str(rem.refund_amount or order.amount),
        "currency": order.currency or "USD",
        "ship_to": {"name": a.get("name"), "city": a.get("city"), "state": a.get("state")},
        "paid": rem.status == "COMPLETED" or pp.get("status") == "COMPLETED",
        "order_id": order.id,
    }
