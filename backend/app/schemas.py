"""API request/response models."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AddressOut(ORM):
    version: int
    name: str | None
    line1: str | None
    line2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    source: str
    created_at: datetime


class CaptureOut(ORM):
    paypal_capture_id: str
    status: str
    status_reason: str | None
    amount: Decimal | None
    currency: str | None
    seller_protection_status: str
    dispute_categories: list[str] | None
    paypal_create_time: str | None
    fetched_at: datetime


class AuditOut(ORM):
    id: str
    actor: str
    action: str
    details: dict[str, Any] | None
    created_at: datetime


class OrderSummary(BaseModel):
    id: str
    paypal_order_id: str
    created_at: datetime
    buyer_name: str | None
    buyer_email_masked: str | None
    amount: Decimal | None
    currency: str | None
    item_description: str | None
    payment_state: str
    verification_state: str
    shipment_state: str
    seller_protection_status: str
    verdict: str | None = None  # wired in Feature 3
    dispute_state: str | None = None  # wired in Feature 5
    ship_to: str | None = None  # "City, ST" only (PII minimisation)


class OrderDetail(OrderSummary):
    paypal_status: str | None
    last_synced_at: datetime | None
    capture: CaptureOut | None
    captures: list[CaptureOut]
    protected_address: AddressOut | None
    address_history: list[AddressOut]
    timeline: list[AuditOut]


class ShopProduct(BaseModel):
    sku: str
    name: str
    description: str
    price: Decimal
    currency: str


class CreateShopOrderIn(BaseModel):
    sku: str = "NECKLACE-SILVER-01"
    quantity: int = Field(default=1, ge=1, le=5)


class CreateShopOrderOut(BaseModel):
    orderId: str


class CaptureShopOrderOut(BaseModel):
    order_id: str
    paypal_order_id: str
    payment_state: str
    seller_protection_status: str


class SyncOrderIn(BaseModel):
    paypal_order_id: str = Field(min_length=5, max_length=64, pattern=r"^[A-Z0-9]+$")
