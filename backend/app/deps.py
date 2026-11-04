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


@lru_cache
def _provider():
    from app.ai.provider import get_provider

    return get_provider(get_settings())


def get_ai_provider_factory():
    """Returns a zero-arg factory so background tasks build the provider lazily (and tests can swap it)."""
    return _provider


def settings_dep() -> Settings:
    return get_settings()


__all__ = ["get_ai_provider_factory", "get_db", "get_paypal_client", "settings_dep"]
