from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import get_db, get_paypal_client
from app.errors import AppError
from app.models import Actor, AuditLog, Order
from app.schemas import (
    AddressOut,
    AuditOut,
    CaptureOut,
    OrderDetail,
    OrderSummary,
    SyncOrderIn,
)
from app.services.audit import audit
from app.services.paypal.client import PayPalClient
from app.services.reconcile import reconcile_order

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _summary(o: Order) -> dict:
    cap = o.latest_capture
    addr = o.active_address
    ship_to = ", ".join(p for p in [addr.city, addr.state] if p) if addr else None
    return dict(
        id=o.id,
        paypal_order_id=o.paypal_order_id,
        created_at=o.created_at,
        buyer_name=o.buyer_name,
        buyer_email_masked=o.buyer_email_masked,
        amount=o.amount,
        currency=o.currency,
        item_description=o.item_description,
        payment_state=o.payment_state,
        verification_state=o.verification_state,
        shipment_state=o.shipment_state,
        seller_protection_status=cap.seller_protection_status if cap else "UNKNOWN",
        ship_to=ship_to or None,
    )


def _load(db: Session, order_id: str) -> Order:
    order = db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.captures), selectinload(Order.addresses))
    )
    if order is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    return order


def _detail(db: Session, o: Order) -> OrderDetail:
    timeline = db.scalars(
        select(AuditLog)
        .where(AuditLog.order_id == o.id, AuditLog.action != "PAYPAL_API_CALL")
        .order_by(AuditLog.created_at.desc())
        .limit(200)
    ).all()
    cap = o.latest_capture
    addr = o.active_address
    return OrderDetail(
        **_summary(o),
        paypal_status=o.paypal_status,
        last_synced_at=o.last_synced_at,
        capture=CaptureOut.model_validate(cap) if cap else None,
        captures=[CaptureOut.model_validate(c) for c in o.captures],
        protected_address=AddressOut.model_validate(addr) if addr else None,
        address_history=[AddressOut.model_validate(a) for a in o.addresses],
        timeline=[AuditOut.model_validate(t) for t in timeline],
    )


@router.get("", response_model=list[OrderSummary])
def list_orders(db: Session = Depends(get_db)):
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.captures), selectinload(Order.addresses))
        .order_by(Order.created_at.desc())
    ).all()
    return [OrderSummary(**_summary(o)) for o in orders]


@router.get("/{order_id}", response_model=OrderDetail)
def get_order_detail(order_id: str, db: Session = Depends(get_db)):
    return _detail(db, _load(db, order_id))


@router.post("/{order_id}/refresh", response_model=OrderDetail)
def refresh_order(
    order_id: str,
    db: Session = Depends(get_db),
    client: PayPalClient = Depends(get_paypal_client),
):
    order = _load(db, order_id)
    audit(db, order.id, Actor.SELLER, "REFRESH_REQUESTED", {})
    db.commit()
    reconcile_order(db, client, order.paypal_order_id, actor=Actor.SELLER, reason="manual refresh")
    return _detail(db, _load(db, order_id))


@router.post("/sync", response_model=OrderDetail)
def sync_order(
    body: SyncOrderIn,
    db: Session = Depends(get_db),
    client: PayPalClient = Depends(get_paypal_client),
):
    """Import an order created outside the demo shop by its PayPal order ID."""
    order = reconcile_order(db, client, body.paypal_order_id, actor=Actor.SELLER, reason="manual sync")
    return _detail(db, _load(db, order.id))
