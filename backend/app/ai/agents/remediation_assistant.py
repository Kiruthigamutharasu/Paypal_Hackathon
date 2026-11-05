"""Remediation Assistant: drafts a short, polite message the SELLER copies to the buyer.

Inputs are order facts only (no raw chat text), so buyer-supplied text can't steer it. It never
sends anything and never promises a PayPal outcome. If the AI is unavailable, a deterministic
template is used instead (free, always works).
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from app.ai.provider import Provider, TextPart, generate_structured

PROMPT_VERSION = "ra-1.0"
AGENT = "remediation_assistant"
MAX_CHARS = 900

SYSTEM_PROMPT = """\
You write short, warm, professional messages that a small online seller sends to a buyer.
Context: PayPal Seller Protection only covers parcels shipped to the address on the PayPal payment.
Rules:
- Use only the facts given. Do not invent order numbers, dates, prices or addresses.
- Explain kindly that the seller can only ship to the address on the PayPal payment.
- Offer exactly the fix described (FIX). Never promise what PayPal will decide; never say "guaranteed".
- No links unless a PAYMENT LINK is given. Plain text, at most 900 characters, no markdown.
- Return JSON: {"subject": ..., "message": ...}.
"""


class BuyerMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=20, max_length=MAX_CHARS)


_FORBIDDEN = re.compile(r"guarantee|100% protected|paypal will (approve|decide in your favou?r)", re.I)


def template(fix: str, item: str, protected_city: str, requested_place: str | None, pay_link: str | None) -> BuyerMessage:
    place = requested_place or "the new address"
    if fix == "REPAY":
        body = (
            f"Hi! Thank you so much for your order of the {item}. I'm happy to send it to {place}. "
            f"For PayPal, I can only ship to the address on the PayPal payment, so I've refunded your original payment "
            f"and created a new PayPal payment with {place} as the shipping address. "
            + (f"You can pay it here: {pay_link} " if pay_link else "I'll send you the payment link shortly. ")
            + "As soon as it's paid, I'll ship right away with tracking. Thank you for understanding!"
        )
        subject = f"Your {item}: new payment for the new address"
    else:
        body = (
            f"Hi! Thank you so much for your order of the {item}. For PayPal, I can only ship to the address on your "
            f"PayPal payment ({protected_city}), so that's where I'll send it, with tracking. If you need it delivered "
            f"somewhere else, let me know and I can set up a new PayPal payment with that address instead. Thank you!"
        )
        subject = f"Shipping your {item}"
    return BuyerMessage(subject=subject[:120], message=body[:MAX_CHARS])


def draft(provider: Provider | None, *, fix: str, item: str, protected_city: str, requested_place: str | None,
          pay_link: str | None) -> tuple[BuyerMessage, str]:
    """Return (message, source) where source is AI or TEMPLATE."""
    if provider is not None:
        facts = (
            f"FIX: {'Refund the original payment and send a NEW PayPal payment with the new address' if fix == 'REPAY' else 'Ship to the address on the PayPal payment'}\n"
            f"ITEM: {item}\nPAYPAL ADDRESS CITY: {protected_city}\nBUYER REQUESTED: {requested_place or 'a different address'}\n"
            f"PAYMENT LINK: {pay_link or 'none'}"
        )
        try:
            res = generate_structured(provider, SYSTEM_PROMPT, [TextPart(facts)], BuyerMessage)
            msg = res.output
            if msg is not None and not _FORBIDDEN.search(msg.message) and (not pay_link or fix != "REPAY" or pay_link in msg.message):
                return msg, "AI"
        except Exception:  # noqa: BLE001 - always fall back to the template
            pass
    return template(fix, item, protected_city, requested_place, pay_link), "TEMPLATE"
