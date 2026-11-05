"""Verification workflow (F3): turns PayPal facts + AI extractions into a versioned verdict.

- evaluate_order(): builds the EvaluationContext, hashes the inputs, reuses the ACTIVE decision if the
  hash is unchanged, otherwise supersedes it and stores a new immutable decision with its flags.
- acknowledge(): YELLOW -> ACKNOWLEDGED (every review item ticked); RED -> OVERRIDDEN (typed reason +
  explicit "Seller Protection likely void" confirmation); GREY cannot be acknowledged.
Any input change (new upload, payment change, new address version) produces a new decision, which
naturally invalidates earlier acknowledgements.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.errors import AppError
from app.models import (
    Actor,
    AddressComparisonRow,
    DecisionResolution,
    DecisionStatus,
    Order,
    RiskFlag,
    ShippingDecision,
    UploadKind,
)
from app.rules.engine import EvaluationContext, ExtractionInput, evaluate
from app.rules.policy import RULES_VERSION
from app.services.audit import audit
from app.services.storage import active_uploads
from app.workflows.extraction import latest_extractions

OVERRIDE_MIN_CHARS = 15


def _tx_date(order: Order) -> date | None:
    cap = order.latest_capture
    raw = (cap.paypal_create_time if cap else None) or order.paypal_create_time
    if not raw:
        return order.created_at.date() if order.created_at else None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def build_context(db: Session, settings: Settings, order: Order) -> tuple[EvaluationContext, str]:
    uploads = active_uploads(db, order.id)
    latest = latest_extractions(db, order.id)
    covered = {uid for rows in latest.values() for r in rows for uid in r.upload_ids}
    pending = any(u.id not in covered for u in uploads)

    def to_input(r) -> ExtractionInput:
        return ExtractionInput(r.id, r.status, r.output, list(r.upload_ids), list(r.validation_notes or []))

    label_rows = latest.get("label_reader", [])
    chats = [to_input(r) for r in latest.get("conversation_analyst", [])]
    cap = order.latest_capture
    addr = order.active_address
    ctx = EvaluationContext(
        payment_state=order.payment_state,
        seller_protection=cap.seller_protection_status if cap else "UNKNOWN",
        amount=order.amount,
        currency=order.currency,
        transaction_date=_tx_date(order),
        protected_address=addr.fields() if addr else None,
        label=to_input(label_rows[0]) if label_rows else None,
        label_uploaded=any(u.kind == UploadKind.LABEL_IMAGE for u in uploads),
        chats=chats,
        chats_uploaded=any(u.kind in (UploadKind.CHAT_IMAGE, UploadKind.CHAT_TEXT) for u in uploads),
        extraction_pending=pending,
        signature_threshold_usd=settings.SIGNATURE_THRESHOLD_USD,
        confidence_threshold=settings.AI_CONFIDENCE_THRESHOLD,
    )
    key = {
        "payment_state": order.payment_state,
        "capture": [cap.paypal_capture_id, cap.status, cap.seller_protection_status] if cap else None,
        "address": [addr.id, addr.version] if addr else None,
        "label": label_rows[0].id if label_rows else None,
        "chats": sorted(c.extraction_id for c in chats),
        "uploads": sorted(u.id for u in uploads),
        "pending": pending,
        "thresholds": [settings.SIGNATURE_THRESHOLD_USD, settings.AI_CONFIDENCE_THRESHOLD],
        "rules": RULES_VERSION,
    }
    input_hash = hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()
    return ctx, input_hash


def active_decision(db: Session, order_id: str) -> ShippingDecision | None:
    return db.scalar(
        select(ShippingDecision)
        .where(ShippingDecision.order_id == order_id, ShippingDecision.status == DecisionStatus.ACTIVE)
        .order_by(ShippingDecision.created_at.desc())
    )


def _state_for(decision: ShippingDecision) -> str:
    if decision.resolution == DecisionResolution.ACKNOWLEDGED:
        return "ACKNOWLEDGED"
    if decision.resolution == DecisionResolution.OVERRIDDEN:
        return "OVERRIDDEN"
    return decision.verdict


def evaluate_order(db: Session, settings: Settings, order_id: str, *, actor: str = Actor.SYSTEM,
                   reason: str = "evaluate") -> ShippingDecision:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    ctx, input_hash = build_context(db, settings, order)
    current = active_decision(db, order.id)
    if current is not None and current.input_hash == input_hash:
        return current  # same inputs -> same decision

    result = evaluate(ctx)
    if current is not None:
        current.status = DecisionStatus.SUPERSEDED
    decision = ShippingDecision(
        order_id=order.id,
        verdict=result.verdict,
        status=DecisionStatus.ACTIVE,
        input_hash=input_hash,
        rules_version=result.rules_version,
        explanation=result.explanation(),
    )
    for i, f in enumerate(result.flags):
        decision.flags.append(
            RiskFlag(position=i, code=f.code, name=f.name, severity=f.severity, effect=f.effect,
                     message=f.message, detail=f.detail, source_ref=f.source_ref, recommended_action=f.action)
        )
    db.add(decision)
    if result.comparison and ctx.label and order.active_address:
        db.add(AddressComparisonRow(order_id=order.id, label_extraction_id=ctx.label.extraction_id,
                                    protected_address_version=order.active_address.version,
                                    field_results=result.comparison["fields"], overall=result.comparison["overall"]))
    order.verification_state = result.verdict
    audit(db, order.id, actor, "DECISION_MADE", {
        "verdict": result.verdict,
        "flags": [f.code for f in result.flags if f.effect not in ("INFO", "NONE")],
        "info": [f.code for f in result.flags if f.effect in ("INFO", "NONE")],
        "superseded": current.id if current else None,
        "trigger": reason,
        "rules_version": result.rules_version,
    })
    db.commit()
    db.refresh(decision)
    return decision


def acknowledge(db: Session, order_id: str, *, items: list[str], reason: str | None, confirm_void: bool) -> ShippingDecision:
    decision = active_decision(db, order_id)
    if decision is None:
        raise AppError("NO_DECISION", "There is no verdict to acknowledge yet.", 409)
    order = db.get(Order, order_id)
    if decision.verdict == "GREEN":
        raise AppError("NOTHING_TO_ACKNOWLEDGE", "Checks already passed.", 409)
    if decision.verdict == "GREY":
        raise AppError("CANNOT_ACKNOWLEDGE", "This order can't be evaluated yet, so it can't be acknowledged. Fix the missing input first.", 409)
    if decision.verdict == "YELLOW":
        needed = {f.code for f in decision.flags if f.effect == "YELLOW"}
        missing = needed - set(items)
        if missing:
            raise AppError("ACK_INCOMPLETE", "Tick every review item before acknowledging.", 422, {"missing": sorted(missing)})
        decision.resolution = DecisionResolution.ACKNOWLEDGED
        decision.acknowledged_items = sorted(needed)
        action = "DECISION_ACKNOWLEDGED"
        details = {"items": sorted(needed)}
    else:  # RED
        text = (reason or "").strip()
        if len(text) < OVERRIDE_MIN_CHARS:
            raise AppError("OVERRIDE_REASON_REQUIRED", f"Type a reason of at least {OVERRIDE_MIN_CHARS} characters to override a blocked shipment.", 422)
        if not confirm_void:
            raise AppError("OVERRIDE_NOT_CONFIRMED", "Confirm that you understand Seller Protection is likely void.", 422)
        decision.resolution = DecisionResolution.OVERRIDDEN
        decision.override_reason = text
        action = "DECISION_OVERRIDDEN"
        details = {"reason": text, "flags": [f.code for f in decision.flags if f.effect == "RED"]}
    decision.resolved_at = utcnow()
    order.verification_state = _state_for(decision)
    audit(db, order_id, Actor.SELLER, action, {"decision_id": decision.id, "verdict": decision.verdict, **details})
    db.commit()
    db.refresh(decision)
    return decision


def shipping_allowed(decision: ShippingDecision | None) -> tuple[bool, str]:
    """Gate for F4 shipments: GREEN, acknowledged YELLOW, or overridden RED."""
    if decision is None:
        return False, "Run the checks first."
    if decision.verdict == "GREEN":
        return True, "checks passed"
    if decision.verdict == "YELLOW" and decision.resolution == DecisionResolution.ACKNOWLEDGED:
        return True, "review acknowledged"
    if decision.verdict == "RED" and decision.resolution == DecisionResolution.OVERRIDDEN:
        return True, "override by seller"
    return False, {"YELLOW": "Acknowledge the review items first.", "RED": "Shipment is blocked. Fix the problem (or override with a reason).",
                   "GREY": "The order can't be evaluated yet."}.get(decision.verdict, "Not allowed.")


def evaluate_safely(db: Session, settings: Settings, order_id: str, reason: str) -> None:
    """Hook used after reconciliation/extraction; never breaks the caller."""
    import logging

    try:
        evaluate_order(db, settings, order_id, reason=reason)
    except Exception:  # pragma: no cover - defensive
        db.rollback()
        logging.getLogger("staycovered.verification").exception("evaluation failed for %s", order_id)
