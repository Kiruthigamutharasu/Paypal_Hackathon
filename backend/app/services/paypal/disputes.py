"""PayPal Disputes v1 (sandbox). See docs/VERIFICATION.md for what was verified and what wasn't.

- GET  /v1/customer/disputes, GET /v1/customer/disputes/{id}
- POST /v1/customer/disputes/{id}/provide-evidence  (multipart/form-data: "input" JSON part + "evidence-file" parts)
- POST /v1/customer/disputes/{id}/adjudicate        (sandbox only; status UNDER_REVIEW; adjudication_outcome)
- POST /v1/customer/disputes/{id}/require-evidence  (sandbox only; action SELLER_EVIDENCE | BUYER_EVIDENCE)
There is NO API to create a dispute; in the sandbox the buyer opens one on sandbox.paypal.com.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.paypal.client import PayPalClient


def list_disputes(client: PayPalClient, page_size: int = 50) -> list[dict[str, Any]]:
    return client.request("GET", "/v1/customer/disputes", params={"page_size": page_size}).get("items", [])


def get_dispute(client: PayPalClient, dispute_id: str) -> dict[str, Any]:
    return client.request("GET", f"/v1/customer/disputes/{dispute_id}")


def allowed_actions(dispute: dict[str, Any]) -> list[str]:
    """Action names from HATEOAS links, normalised from the URL's last path segment (robust to rel naming)."""
    actions = set()
    for link in dispute.get("links") or []:
        href = (link.get("href") or "").rstrip("/")
        if link.get("method", "").upper() == "POST" and "/customer/disputes/" in href:
            actions.add(href.rsplit("/", 1)[-1].replace("_", "-"))
        rel = (link.get("rel") or "").replace("_", "-")
        if rel and rel not in ("self", "up"):
            actions.add(rel)
    return sorted(actions)


def provide_evidence(client: PayPalClient, dispute_id: str, *, evidences: list[dict[str, Any]],
                     files: list[tuple[str, bytes, str]], request_id: str, order_id: str | None = None) -> dict[str, Any]:
    parts: list[tuple[str, tuple[str | None, bytes, str]]] = [
        ("input", (None, json.dumps({"evidences": evidences}).encode(), "application/json")),
    ]
    for name, data, mime in files:
        parts.append(("evidence-file", (name, data, mime)))
    return client.request("POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=parts,
                          request_id=request_id, order_id=order_id)


def adjudicate(client: PayPalClient, dispute_id: str, outcome: str) -> dict[str, Any]:
    return client.request("POST", f"/v1/customer/disputes/{dispute_id}/adjudicate", json={"adjudication_outcome": outcome})


def require_evidence(client: PayPalClient, dispute_id: str, action: str) -> dict[str, Any]:
    return client.request("POST", f"/v1/customer/disputes/{dispute_id}/require-evidence", json={"action": action})
