"""Orders v2 tracking (verified live in sandbox Nov 5, 2026; see docs/VERIFICATION.md).

POST /v2/checkout/orders/{id}/track returns the ORDER; trackers are in purchase_units[].shipping.trackers[]
with id "{capture_id}-{tracking_number}". PATCH .../trackers/{tracker_id} with a JSON Patch array; only
status -> CANCELLED is supported by PayPal.
"""
from __future__ import annotations

from typing import Any

from app.services.paypal.client import PayPalClient

# Verified live: USPS, UPS, FEDEX (docs example), DHL, DHL_API, OTHER (+ carrier_name_other).
CARRIERS = {
    "USPS": "USPS",
    "UPS": "UPS",
    "FEDEX": "FedEx",
    "DHL": "DHL",
    "OTHER": "Other carrier",
}


def add_tracking(client: PayPalClient, paypal_order_id: str, *, capture_id: str, tracking_number: str, carrier: str,
                 carrier_name_other: str | None, notify_payer: bool, items: list[dict] | None, request_id: str,
                 order_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "capture_id": capture_id,
        "tracking_number": tracking_number,
        "carrier": carrier,
        "notify_payer": notify_payer,
    }
    if carrier == "OTHER":
        body["carrier_name_other"] = carrier_name_other
    if items:
        body["items"] = items
    return client.request("POST", f"/v2/checkout/orders/{paypal_order_id}/track", json=body,
                          request_id=request_id, order_id=order_id)


def find_tracker(order_response: dict[str, Any], capture_id: str, tracking_number: str) -> dict[str, Any] | None:
    for unit in order_response.get("purchase_units") or []:
        for t in (unit.get("shipping") or {}).get("trackers") or []:
            if t.get("id") == f"{capture_id}-{tracking_number}":
                return t
    return None


def cancel_tracker(client: PayPalClient, paypal_order_id: str, tracker_id: str, order_id: str | None = None) -> None:
    client.request("PATCH", f"/v2/checkout/orders/{paypal_order_id}/trackers/{tracker_id}",
                   json=[{"op": "replace", "path": "/status", "value": "CANCELLED"}], order_id=order_id)
