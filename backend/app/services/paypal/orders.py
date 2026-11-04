"""PayPal Orders v2."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.paypal.client import PayPalClient


def _money(currency: str, value: Decimal) -> dict[str, str]:
    return {"currency_code": currency, "value": f"{value:.2f}"}


def build_order_body(
    *,
    item_name: str,
    item_sku: str,
    unit_amount: Decimal,
    currency: str,
    quantity: int = 1,
    brand_name: str,
    return_url: str,
    cancel_url: str,
    shipping_preference: str = "GET_FROM_FILE",
    shipping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """intent CAPTURE, one physical-goods item. With GET_FROM_FILE the buyer's PayPal
    shipping address becomes the protected address on the transaction."""
    total = unit_amount * quantity
    unit: dict[str, Any] = {
        "reference_id": item_sku,
        "description": item_name,
        "amount": {
            **_money(currency, total),
            "breakdown": {"item_total": _money(currency, total)},
        },
        "items": [
            {
                "name": item_name,
                "sku": item_sku,
                "quantity": str(quantity),
                "unit_amount": _money(currency, unit_amount),
                "category": "PHYSICAL_GOODS",
            }
        ],
    }
    if shipping:
        unit["shipping"] = shipping
    return {
        "intent": "CAPTURE",
        "purchase_units": [unit],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "shipping_preference": shipping_preference,
                    "user_action": "PAY_NOW",
                    "brand_name": brand_name,
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                }
            }
        },
    }


def create_order(client: PayPalClient, body: dict[str, Any], *, request_id: str) -> dict[str, Any]:
    return client.request(
        "POST",
        "/v2/checkout/orders",
        json=body,
        request_id=request_id,
        extra_headers={"Prefer": "return=representation"},
    )


def capture_order(client: PayPalClient, paypal_order_id: str, *, request_id: str) -> dict[str, Any]:
    return client.request(
        "POST",
        f"/v2/checkout/orders/{paypal_order_id}/capture",
        json={},
        request_id=request_id,
        extra_headers={"Prefer": "return=representation"},
    )


def get_order(client: PayPalClient, paypal_order_id: str) -> dict[str, Any]:
    return client.request("GET", f"/v2/checkout/orders/{paypal_order_id}")
