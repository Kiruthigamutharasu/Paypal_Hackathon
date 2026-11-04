"""Audit helper. Every state change writes an audit row (CLAUDE.md coding standards)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app import db as dbm
from app.models import AuditLog

log = logging.getLogger("staycovered.audit")

_SECRET_KEYS = {"authorization", "access_token", "client_secret", "password", "token", "secret"}


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in _SECRET_KEYS else _scrub(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def audit(
    db: Session,
    order_id: str | None,
    actor: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit row to the current session (committed with the caller's transaction)."""
    row = AuditLog(order_id=order_id, actor=str(actor), action=action, details=_scrub(details or {}))
    db.add(row)
    return row


def audit_now(order_id: str | None, actor: str, action: str, details: dict[str, Any] | None = None) -> None:
    """Write an audit row in its own transaction (used by the PayPal client call hook)."""
    try:
        with dbm.SessionLocal() as db:
            audit(db, order_id, actor, action, details)
            db.commit()
    except Exception:  # auditing must never break the request
        log.exception("failed to write audit row for %s", action)
