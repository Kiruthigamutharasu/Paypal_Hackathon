"""Webhook signature verification via POST /v1/notifications/verify-webhook-signature."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError

log = logging.getLogger("staycovered.webhooks")

# PayPal transmission headers (case-insensitive) -> verify API field
HEADER_FIELDS = {
    "paypal-auth-algo": "auth_algo",
    "paypal-cert-url": "cert_url",
    "paypal-transmission-id": "transmission_id",
    "paypal-transmission-sig": "transmission_sig",
    "paypal-transmission-time": "transmission_time",
}


def verify_signature(
    client: PayPalClient, headers: Mapping[str, str], raw_body: bytes, webhook_id: str
) -> tuple[bool, str]:
    """Return (verified, reason). Never raises for a bad signature."""
    if not webhook_id:
        return False, "PAYPAL_WEBHOOK_ID is not configured"
    lower = {k.lower(): v for k, v in headers.items()}
    payload: dict[str, Any] = {}
    for header, field in HEADER_FIELDS.items():
        value = lower.get(header)
        if not value:
            return False, f"missing header {header}"
        payload[field] = value
    try:
        payload["webhook_event"] = json.loads(raw_body)
    except ValueError:
        return False, "body is not valid JSON"
    payload["webhook_id"] = webhook_id
    try:
        resp = client.request("POST", "/v1/notifications/verify-webhook-signature", json=payload)
    except PayPalError as exc:
        if exc.retryable:
            raise  # PayPal down: let PayPal redeliver later rather than reject
        return False, f"verification call rejected ({exc.status_code})"
    status = resp.get("verification_status")
    return status == "SUCCESS", f"verification_status={status}"
