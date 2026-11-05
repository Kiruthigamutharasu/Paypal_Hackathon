"""PayPal Payments v2 (captures)."""
from __future__ import annotations

from typing import Any

from app.services.paypal.client import PayPalClient


def get_capture(client: PayPalClient, capture_id: str) -> dict[str, Any]:
    return client.request("GET", f"/v2/payments/captures/{capture_id}")


def refund_capture(client: PayPalClient, capture_id: str, *, request_id: str, note_to_payer: str | None = None,
                   order_id: str | None = None) -> dict[str, Any]:
    """Full refund (empty body = full amount). Stable request_id makes double clicks refund once."""
    body: dict[str, Any] = {}
    if note_to_payer:
        body["note_to_payer"] = note_to_payer[:255]
    return client.request(
        "POST",
        f"/v2/payments/captures/{capture_id}/refund",
        json=body,
        request_id=request_id,
        extra_headers={"Prefer": "return=representation"},
        order_id=order_id,
    )
