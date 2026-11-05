"""PayPal Seller Protection policy rules (US). Keyed by transaction date so policy changes are explicit.

VERIFY on PayPal's current US Seller Protection page (recorded in docs/VERIFICATION.md):
signature confirmation was REQUIRED for US transactions >= $750 processed before 2026-01-26 and is
RECOMMENDED (not mandatory) for transactions on/after that date.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

RULES_VERSION = "1.0.0"
SIGNATURE_RULE_CHANGE = date(2026, 1, 26)  # VERIFY


def signature_requirement(total: Decimal | None, currency: str | None, country: str | None,
                          tx_date: date | None, threshold_usd: float) -> str | None:
    """Return None, 'RECOMMENDED' or 'REQUIRED'."""
    if total is None or (currency or "USD") != "USD" or (country or "US") != "US":
        return None
    if Decimal(total) < Decimal(str(threshold_usd)):
        return None
    if tx_date is not None and tx_date < SIGNATURE_RULE_CHANGE:
        return "REQUIRED"
    return "RECOMMENDED"
