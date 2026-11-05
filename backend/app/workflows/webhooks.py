"""Webhook intake and background processing.

Intake (fast, in request):   verify signature -> dedupe by event ID -> store -> 200
Processing (background):     payment events -> re-fetch from PayPal and reconcile
                             dispute events -> stored for Feature 5
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db as dbm
from app.config import Settings
from app.db import utcnow
from app.models import Actor, WebhookEvent, WebhookStatus
from app.services.audit import audit
from app.services.paypal.client import PayPalClient
from app.services.paypal.webhooks import verify_signature
from app.services.reconcile import find_order_id_for_capture, reconcile_order

log = logging.getLogger("staycovered.webhooks")

# VERIFY names against PayPal's event list (see docs/VERIFICATION.md)
PAYMENT_EVENTS = {
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.PENDING",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
}
DISPUTE_EVENTS = {
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.UPDATED",
    "CUSTOMER.DISPUTE.RESOLVED",
}

_CAPTURE_HREF = re.compile(r"/v2/payments/captures/([A-Z0-9]+)")


@dataclass
class IntakeResult:
    status_code: int
    outcome: str  # accepted | duplicate | rejected
    event_row_id: str | None = None
    reason: str | None = None


def receive_webhook(
    db: Session,
    client: PayPalClient,
    settings: Settings,
    headers: Mapping[str, str],
    raw_body: bytes,
) -> IntakeResult:
    try:
        event = json.loads(raw_body)
        event_id = event["id"]
        event_type = event["event_type"]
    except (ValueError, KeyError, TypeError):
        audit(db, None, Actor.SYSTEM, "SECURITY_WEBHOOK_MALFORMED", {"size": len(raw_body)})
        db.commit()
        return IntakeResult(400, "rejected", reason="malformed body")

    verified, reason = verify_signature(client, headers, raw_body, settings.PAYPAL_WEBHOOK_ID)
    if not verified:
        log.warning("webhook signature rejected: %s (event %s)", reason, event_id)
        audit(
            db,
            None,
            Actor.SYSTEM,
            "SECURITY_WEBHOOK_SIGNATURE_INVALID",
            {"event_id": event_id, "event_type": event_type, "reason": reason},
        )
        db.commit()
        return IntakeResult(400, "rejected", reason=reason)

    existing = db.scalar(select(WebhookEvent).where(WebhookEvent.paypal_event_id == event_id))
    if existing is not None:
        return IntakeResult(200, "duplicate", existing.id)

    resource = event.get("resource") or {}
    row = WebhookEvent(
        paypal_event_id=event_id,
        event_type=event_type,
        resource_type=event.get("resource_type"),
        resource_id=resource.get("id") if isinstance(resource, dict) else None,
        verified=True,
        status=WebhookStatus.RECEIVED,
        raw=event,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # concurrent delivery of the same event
        db.rollback()
        existing = db.scalar(select(WebhookEvent).where(WebhookEvent.paypal_event_id == event_id))
        return IntakeResult(200, "duplicate", existing.id if existing else None)
    return IntakeResult(200, "accepted", row.id)


def _paypal_order_id_for(db: Session, client: PayPalClient, event: dict[str, Any]) -> str | None:
    resource = event.get("resource") or {}
    related = ((resource.get("supplementary_data") or {}).get("related_ids")) or {}
    if related.get("order_id"):
        return related["order_id"]
    # Refund/reversal resources point back to the capture via an "up" link
    for link in resource.get("links") or []:
        m = _CAPTURE_HREF.search(link.get("href", ""))
        if m:
            return find_order_id_for_capture(db, client, m.group(1))
    if event.get("resource_type") == "capture" and resource.get("id"):
        return find_order_id_for_capture(db, client, resource["id"])
    return None


def process_event(db: Session, client: PayPalClient, event_row_id: str) -> WebhookEvent:
    row = db.get(WebhookEvent, event_row_id)
    if row is None:
        raise LookupError(event_row_id)
    if row.status in (WebhookStatus.PROCESSED, WebhookStatus.IGNORED):
        return row  # already handled; processing is idempotent
    row.attempts += 1
    try:
        if row.event_type in PAYMENT_EVENTS:
            paypal_order_id = _paypal_order_id_for(db, client, row.raw)
            if not paypal_order_id:
                raise ValueError("could not determine the PayPal order for this event")
            order = reconcile_order(
                db, client, paypal_order_id, actor=Actor.PAYPAL, reason=f"webhook {row.event_type}"
            )
            row.order_id = order.id
            row.status = WebhookStatus.PROCESSED
            audit(db, order.id, Actor.PAYPAL, "WEBHOOK_PROCESSED", {"event_type": row.event_type, "event_id": row.paypal_event_id})
        elif row.event_type in DISPUTE_EVENTS:
            from app.workflows.disputes import sync_dispute  # local import: avoids a cycle

            resource = row.raw.get("resource") or {}
            dispute_id = resource.get("dispute_id") or resource.get("id")
            if not dispute_id:
                raise ValueError("dispute event without dispute_id")
            dispute = sync_dispute(db, client, dispute_id)  # always re-fetch; never trust the payload
            row.order_id = dispute.order_id
            row.status = WebhookStatus.PROCESSED
        else:
            row.status = WebhookStatus.IGNORED
        row.error = None
        row.processed_at = utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        row = db.get(WebhookEvent, event_row_id)
        assert row is not None
        row.status = WebhookStatus.FAILED
        row.error = f"{type(exc).__name__}: {exc}"[:1000]
        audit(db, row.order_id, Actor.SYSTEM, "WEBHOOK_FAILED", {"event_type": row.event_type, "event_id": row.paypal_event_id, "error": type(exc).__name__})
        db.commit()
        log.warning("webhook %s failed: %s", row.paypal_event_id, exc)
    return row


def process_event_in_background(client: PayPalClient, event_row_id: str) -> None:
    with dbm.SessionLocal() as db:
        process_event(db, client, event_row_id)


def reprocess_failed(db: Session, client: PayPalClient) -> list[str]:
    ids = list(
        db.scalars(
            select(WebhookEvent.id).where(
                WebhookEvent.status.in_([WebhookStatus.FAILED, WebhookStatus.RECEIVED, WebhookStatus.STORED])
            )
        )
    )
    for event_id in ids:
        process_event(db, client, event_id)
    return ids
