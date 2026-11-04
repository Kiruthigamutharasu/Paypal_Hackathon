"""Shared dependencies: settings, DB session, PayPal client singleton."""
from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Actor
from app.services.audit import audit_now
from app.services.paypal.client import PayPalClient


def _audit_paypal_call(record: dict) -> None:
    audit_now(record.get("order_id"), Actor.SYSTEM, "PAYPAL_API_CALL", record)


@lru_cache
def get_paypal_client() -> PayPalClient:
    return PayPalClient(get_settings(), on_call=_audit_paypal_call)


def settings_dep() -> Settings:
    return get_settings()


__all__ = ["get_db", "get_paypal_client", "settings_dep"]
