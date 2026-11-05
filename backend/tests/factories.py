"""PayPal response builders (shapes per Orders v2 / Payments v2 docs)."""
from __future__ import annotations

from typing import Any

ORDER_ID = "5O190127TN364715T"
CAPTURE_ID = "3C679366HH908993F"

NY_SHIPPING = {
    "name": {"full_name": "Jane Doe"},
    "address": {
        "address_line_1": "123 Main St",
        "address_line_2": "Apt 4B",
        "admin_area_2": "New York",
        "admin_area_1": "NY",
        "postal_code": "10001",
        "country_code": "US",
    },
}


def capture(status: str = "COMPLETED", *, seller_protection: dict | None | str = "default", capture_id: str = CAPTURE_ID, order_id: str = ORDER_ID) -> dict[str, Any]:
    c: dict[str, Any] = {
        "id": capture_id,
        "status": status,
        "amount": {"currency_code": "USD", "value": "300.00"},
        "final_capture": True,
        "create_time": "2026-11-04T10:00:00Z",
        "supplementary_data": {"related_ids": {"order_id": order_id}},
        "links": [{"rel": "self", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{capture_id}", "method": "GET"}],
    }
    if seller_protection == "default":
        c["seller_protection"] = {
            "status": "ELIGIBLE",
            "dispute_categories": ["ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"],
        }
    elif seller_protection is not None:
        c["seller_protection"] = seller_protection
    return c


def order(
    status: str = "COMPLETED",
    *,
    captures: list[dict] | None = None,
    shipping: dict | None = NY_SHIPPING,
    order_id: str = ORDER_ID,
) -> dict[str, Any]:
    unit: dict[str, Any] = {
        "reference_id": "POS-STARTER-KIT",
        "description": "Pocket POS Starter Kit",
        "amount": {"currency_code": "USD", "value": "300.00"},
    }
    if shipping:
        unit["shipping"] = shipping
    if captures is not None:
        unit["payments"] = {"captures": captures}
    return {
        "id": order_id,
        "status": status,
        "intent": "CAPTURE",
        "create_time": "2026-11-04T09:59:00Z",
        "payer": {
            "name": {"given_name": "Jane", "surname": "Doe"},
            "email_address": "jane.buyer@personal.example.com",
            "payer_id": "QYR5Z8XDVJNXQ",
        },
        "purchase_units": [unit],
    }


def webhook_event(event_type: str, resource: dict, event_id: str = "WH-EVT-1", resource_type: str = "capture") -> dict:
    return {
        "id": event_id,
        "event_version": "1.0",
        "create_time": "2026-11-04T10:00:05Z",
        "resource_type": resource_type,
        "event_type": event_type,
        "summary": event_type,
        "resource": resource,
    }


SIG_HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-360caa42",
    "PAYPAL-TRANSMISSION-ID": "69cd13f0-d67a-11e5-baa3-778b53f4ae55",
    "PAYPAL-TRANSMISSION-SIG": "lmI95Jx3Y9nhR5SJWlHVIWpg4AgFk7n9bCHSRxbrd8A9zrhdu2rMyFrmz+Zjh3s3boXB07VXCXUZy/UFzUlnGJn0wDugt7FlSvdKeIJenLRemUxYCPVoEZzg9VFNqOa48gMkvF+XTpxBeUx/kWy6B5cp7GkT2+pOowfRK7OaynuxUoKW3JcMWw272VKjLTtTAShncla7tGF+55rxyt2KNZIIqxNMJ48RDZheGU5w1npu9dZHnPgTXB9iomeVRoD8O/jhRpnKsGrDschyNdkeh81BJJMH4Ctc6lnCCquoP/GzCzz33MMsNdid7vL/NIWaCsekQpW26FpWPi/tfj8nLA==",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-04T10:00:05Z",
}
