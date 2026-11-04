from __future__ import annotations

from typing import Any


class PayPalError(Exception):
    """A failed PayPal API call. Carries PayPal's debug_id for support escalation."""

    def __init__(
        self,
        status_code: int,
        name: str | None = None,
        message: str | None = None,
        debug_id: str | None = None,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"PayPal {status_code} {name or ''}: {message or ''}".strip())
        self.status_code = status_code
        self.name = name
        self.message = message
        self.debug_id = debug_id
        self.details = details or []
        self.retryable = retryable

    @property
    def issues(self) -> list[str]:
        return [d.get("issue", "") for d in self.details if isinstance(d, dict)]

    def has_issue(self, issue: str) -> bool:
        return issue in self.issues

    def human_message(self) -> str:
        if self.has_issue("INSTRUMENT_DECLINED"):
            return "The buyer's payment method was declined. Ask them to choose another one."
        if self.has_issue("ORDER_NOT_APPROVED"):
            return "The buyer has not approved this payment yet."
        return self.message or "PayPal returned an error."

    def public_details(self) -> dict[str, Any]:
        return {
            "paypal_status": self.status_code,
            "paypal_name": self.name,
            "paypal_debug_id": self.debug_id,
            "issues": self.issues,
        }
