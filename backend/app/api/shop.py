"""Demo shop: creates and captures real PayPal sandbox orders (server-side only)."""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_db, get_paypal_client, settings_dep
from app.errors import AppError
from app.models import Actor
from app.schemas import (
    CaptureShopOrderOut,
    CreateShopOrderIn,
    CreateShopOrderOut,
    ShopProduct,
)
from app.services.audit import audit
from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError
from app.services.paypal.orders import build_order_body, capture_order, create_order
from app.services.reconcile import reconcile_order

router = APIRouter(prefix="/api/shop", tags=["shop"])

CATALOG: dict[str, ShopProduct] = {
    "NECKLACE-SILVER-01": ShopProduct(
        sku="NECKLACE-SILVER-01",
        name="Handmade Silver Necklace",
        description="Sterling silver teardrop pendant on an 18-inch chain, handmade in small batches by Priya.",
        price=Decimal("300.00"),
        currency="USD",
    )
}

PAYPAL_ORDER_ID = Path(..., min_length=5, max_length=64, pattern=r"^[A-Z0-9]+$")


@router.get("/products", response_model=list[ShopProduct])
def list_products():
    return list(CATALOG.values())


@router.post("/orders", response_model=CreateShopOrderOut)
def create_shop_order(
    body: CreateShopOrderIn,
    db: Session = Depends(get_db),
    client: PayPalClient = Depends(get_paypal_client),
    settings: Settings = Depends(settings_dep),
):
    product = CATALOG.get(body.sku)
    if product is None:
        raise AppError("UNKNOWN_PRODUCT", "That product does not exist.", 404)
    origin = settings.FRONTEND_ORIGIN.rstrip("/")
    order_body = build_order_body(
        item_name=product.name,
        item_sku=product.sku,
        unit_amount=product.price,  # amount always from the server catalog, never the client
        currency=product.currency,
        quantity=body.quantity,
        brand_name="StayCovered Demo Shop",
        return_url=f"{origin}/shop?status=return",
        cancel_url=f"{origin}/shop?status=cancel",
    )
    result = create_order(client, order_body, request_id=f"shop-create-{uuid.uuid4()}")
    audit(db, None, Actor.SYSTEM, "SHOP_ORDER_CREATED", {"paypal_order_id": result["id"], "sku": product.sku, "status": result.get("status")})
    db.commit()
    return CreateShopOrderOut(orderId=result["id"])


@router.post("/orders/{paypal_order_id}/capture", response_model=CaptureShopOrderOut)
def capture_shop_order(
    paypal_order_id: str = PAYPAL_ORDER_ID,
    db: Session = Depends(get_db),
    client: PayPalClient = Depends(get_paypal_client),
):
    # Stable request ID: a double-click or retry cannot capture twice.
    try:
        capture_order(client, paypal_order_id, request_id=f"shop-capture-{paypal_order_id}")
    except PayPalError as exc:
        if exc.has_issue("ORDER_ALREADY_CAPTURED"):
            pass  # already captured: just reconcile below
        elif exc.has_issue("INSTRUMENT_DECLINED"):
            raise AppError(
                "INSTRUMENT_DECLINED",
                "The payment method was declined. Please try again with another one.",
                422,
                exc.public_details(),
            ) from exc
        else:
            raise
    order = reconcile_order(db, client, paypal_order_id, actor=Actor.PAYPAL, reason="shop capture")
    cap = order.latest_capture
    return CaptureShopOrderOut(
        order_id=order.id,
        paypal_order_id=order.paypal_order_id,
        payment_state=order.payment_state,
        seller_protection_status=cap.seller_protection_status if cap else "UNKNOWN",
    )
