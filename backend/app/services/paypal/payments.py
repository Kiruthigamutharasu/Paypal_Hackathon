"""PayPal Payments v2 (captures)."""
from __future__ import annotations

from typing import Any

from app.services.paypal.client import PayPalClient


def get_capture(client: PayPalClient, capture_id: str) -> dict[str, Any]:
    return client.request("GET", f"/v2/payments/captures/{capture_id}")
