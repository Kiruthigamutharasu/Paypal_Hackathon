"""ORM models (PRD §10). Feature 1 tables."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow

DEFAULT_SELLER_ID = "seller_demo"


def new_id() -> str:
    return str(uuid.uuid4())


class PaymentState(StrEnum):
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    REVERSED = "REVERSED"


class VerificationState(StrEnum):
    AWAITING_DOCUMENTS = "AWAITING_DOCUMENTS"
    AI_PROCESSING = "AI_PROCESSING"
    GREY = "GREY"
    YELLOW = "YELLOW"
    RED = "RED"
    GREEN = "GREEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERRIDDEN = "OVERRIDDEN"


class ShipmentState(StrEnum):
    NOT_SHIPPED = "NOT_SHIPPED"
    LABEL_CHECKED = "LABEL_CHECKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Actor(StrEnum):
    SYSTEM = "SYSTEM"
    SELLER = "SELLER"
    AI = "AI"
    PAYPAL = "PAYPAL"


class WebhookStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    STORED = "STORED"  # accepted, processing deferred to a later feature (disputes -> F5)
    IGNORED = "IGNORED"
    FAILED = "FAILED"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    seller_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_SELLER_ID, index=True)
    paypal_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    payment_state: Mapped[str] = mapped_column(String(32), default=PaymentState.PAYMENT_PENDING)
    verification_state: Mapped[str] = mapped_column(
        String(32), default=VerificationState.AWAITING_DOCUMENTS
    )
    shipment_state: Mapped[str] = mapped_column(String(32), default=ShipmentState.NOT_SHIPPED)
    paypal_status: Mapped[str | None] = mapped_column(String(32))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    item_description: Mapped[str | None] = mapped_column(String(255))
    buyer_name: Mapped[str | None] = mapped_column(String(255))
    buyer_email_masked: Mapped[str | None] = mapped_column(String(255))
    paypal_create_time: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    captures: Mapped[list[Capture]] = relationship(
        back_populates="order", order_by="Capture.created_at", cascade="all, delete-orphan"
    )
    addresses: Mapped[list[ProtectedAddress]] = relationship(
        back_populates="order", order_by="ProtectedAddress.version", cascade="all, delete-orphan"
    )

    @property
    def active_address(self) -> ProtectedAddress | None:
        active = [a for a in self.addresses if a.is_active]
        return active[-1] if active else None

    @property
    def latest_capture(self) -> Capture | None:
        return self.captures[-1] if self.captures else None


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    paypal_capture_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    status_reason: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    seller_protection_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    dispute_categories: Mapped[list[str] | None] = mapped_column(JSON)
    paypal_create_time: Mapped[str | None] = mapped_column(String(40))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="captures")


class ProtectedAddress(Base):
    """The shipping address on the PayPal transaction. Versioned; one active per order."""

    __tablename__ = "protected_addresses"
    __table_args__ = (UniqueConstraint("order_id", "version", name="uq_protected_address_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="PAYPAL_ORDER")
    paypal_order_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(255))
    line1: Mapped[str | None] = mapped_column(String(300))
    line2: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(300))
    postal_code: Mapped[str | None] = mapped_column(String(60))
    country: Mapped[str | None] = mapped_column(String(2))
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # filled by F3
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[Order] = relationship(back_populates="addresses")

    def fields(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "line1": self.line1,
            "line2": self.line2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
        }


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paypal_event_id: Mapped[str] = mapped_column(String(128), unique=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=WebhookStatus.RECEIVED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadKind(StrEnum):
    CHAT_IMAGE = "CHAT_IMAGE"
    CHAT_TEXT = "CHAT_TEXT"
    LABEL_IMAGE = "LABEL_IMAGE"


class ExtractionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"  # SYS-01


class Upload(Base):
    """Immutable original evidence file. Replacing a label sets `superseded_by`; nothing is overwritten."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(500))  # relative to FILE_STORAGE_PATH
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    batch_id: Mapped[str | None] = mapped_column(String(36))
    superseded_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIExtraction(Base):
    __tablename__ = "ai_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(48), index=True)
    upload_ids: Mapped[list[str]] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(16))
    schema_version: Mapped[str] = mapped_column(String(16))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_response_hash: Mapped[str | None] = mapped_column(String(64))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validation_notes: Mapped[list[str] | None] = mapped_column(JSON)  # e.g. dropped unsourced items (AI-15)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(24))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DecisionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DecisionResolution(StrEnum):
    NONE = "NONE"
    ACKNOWLEDGED = "ACKNOWLEDGED"  # seller reviewed a YELLOW verdict
    OVERRIDDEN = "OVERRIDDEN"  # seller shipped despite RED (reason logged)


class AddressComparisonRow(Base):
    __tablename__ = "address_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    label_extraction_id: Mapped[str] = mapped_column(String(36))
    protected_address_version: Mapped[int] = mapped_column(Integer)
    field_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    overall: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShippingDecision(Base):
    """Immutable verdict bound to its inputs (input_hash). Only `status` and the seller's
    resolution fields change afterwards."""

    __tablename__ = "shipping_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    verdict: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default=DecisionStatus.ACTIVE, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    rules_version: Mapped[str] = mapped_column(String(16))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON)
    resolution: Mapped[str] = mapped_column(String(16), default=DecisionResolution.NONE)
    acknowledged_items: Mapped[list[str] | None] = mapped_column(JSON)
    override_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    flags: Mapped[list[RiskFlag]] = relationship(back_populates="decision", cascade="all, delete-orphan", order_by="RiskFlag.position")


class RiskFlag(Base):
    __tablename__ = "risk_flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    decision_id: Mapped[str] = mapped_column(ForeignKey("shipping_decisions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    severity: Mapped[str] = mapped_column(String(16))
    effect: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(Text)

    decision: Mapped[ShippingDecision] = relationship(back_populates="flags")


class AuditLog(Base):
    """Append-only audit trail. Never store secrets or full street addresses here."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


__all__ = [
    "DEFAULT_SELLER_ID",
    "AIExtraction",
    "Actor",
    "AddressComparisonRow",
    "DecisionResolution",
    "DecisionStatus",
    "RiskFlag",
    "ShippingDecision",
    "ExtractionStatus",
    "Upload",
    "UploadKind",
    "AuditLog",
    "Capture",
    "Order",
    "PaymentState",
    "ProtectedAddress",
    "ShipmentState",
    "VerificationState",
    "WebhookEvent",
    "WebhookStatus",
]
