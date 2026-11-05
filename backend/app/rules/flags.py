"""Flag registry (PRD §8.3). Declarative: code -> meaning, severity, verdict effect, seller message, action.

Effects: RED, GREY, YELLOW (needs review), INFO (shown, does not change the verdict), NONE.
Codes marked (ext) extend the PRD table; they are documented in docs/STATUS.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Effect(StrEnum):
    RED = "RED"
    GREY = "GREY"
    YELLOW = "YELLOW"
    INFO = "INFO"
    NONE = "NONE"


@dataclass(frozen=True)
class FlagDef:
    code: str
    name: str
    severity: str  # Critical | High | Medium | Low
    effect: Effect
    detected_by: str  # Rule | AI | System
    message: str
    action: str


_DEFS = [
    FlagDef("PAY-01", "Payment pending", "High", Effect.GREY, "Rule", "Payment is not completed yet.", "Wait for PayPal to complete the payment before shipping."),
    FlagDef("PAY-02", "Payment failed", "Critical", Effect.RED, "Rule", "The payment failed or was declined.", "Do not ship."),
    FlagDef("PAY-04", "Partially refunded", "Medium", Effect.YELLOW, "Rule", "Part of this payment was refunded.", "Confirm what you should still ship."),
    FlagDef("PAY-05", "Refunded or reversed", "Critical", Effect.RED, "Rule", "This payment was refunded or reversed.", "Do not ship."),
    FlagDef("SP-01", "Not eligible for Seller Protection", "Medium", Effect.INFO, "Rule", "PayPal marks this payment as not eligible for Seller Protection.", "Our checks still reduce your risk, but PayPal won't cover a claim."),
    FlagDef("SP-02", "Partially eligible", "Low", Effect.INFO, "Rule", "PayPal marks this payment as partially eligible (item-not-received claims only).", "Keep tracking proof for this order."),
    FlagDef("SP-09", "Signature confirmation", "Low", Effect.INFO, "Rule", "Order total is at or above the signature threshold.", "Add signature confirmation when you ship."),
    FlagDef("ADD-01", "Protected address missing", "Critical", Effect.GREY, "Rule", "PayPal has no shipping address for this payment.", "Refresh from PayPal; without an address there is nothing safe to ship to."),
    FlagDef("ADD-02", "Label missing", "High", Effect.GREY, "Rule", "No shipping label has been checked yet.", "Upload a photo of the shipping label."),
    FlagDef("ADD-03", "Buyer requested a different address", "Critical", Effect.RED, "AI→Rule", "The buyer asked you to ship somewhere other than the PayPal address.", "Ship only to the PayPal address, or use Safe re-pay so the new address is on a PayPal payment."),
    FlagDef("ADD-03A", "Possible different address", "High", Effect.YELLOW, "AI→Rule", "The chat suggests a different delivery address (unclear or suggested by the seller).", "Confirm with the buyer that you will ship to the PayPal address."),
    FlagDef("ADD-04", "City or state differs", "Critical", Effect.RED, "Rule", "The label's city or state does not match the PayPal address.", "Reprint the label with the PayPal address."),
    FlagDef("ADD-05", "ZIP code differs", "Critical", Effect.RED, "Rule", "The label's ZIP code does not match the PayPal address.", "Reprint the label with the PayPal address."),
    FlagDef("ADD-06", "Country differs", "Critical", Effect.RED, "Rule", "The label's country does not match the PayPal address.", "Reprint the label with the PayPal address."),
    FlagDef("ADD-07", "Apartment/unit missing", "High", Effect.YELLOW, "Rule", "The PayPal address has an apartment/unit that is not on the label.", "Add the unit number to the label."),
    FlagDef("ADD-08", "Street differs (ext)", "Critical", Effect.RED, "Rule", "The label's street address does not match the PayPal address.", "Reprint the label with the PayPal address."),
    FlagDef("ADD-09", "Recipient name differs", "Medium", Effect.YELLOW, "Rule", "The name on the label differs from the PayPal shipping name.", "Check for 'c/o' or a different recipient."),
    FlagDef("ADD-10", "Street almost matches (ext)", "High", Effect.YELLOW, "Rule", "The street on the label is close to, but not the same as, the PayPal address.", "Check the street spelling and number on the label."),
    FlagDef("ADD-11", "Address not fully comparable (ext)", "Medium", Effect.YELLOW, "Rule", "Some address fields could not be read or compared (or the address is outside the US).", "Check the label against the PayPal address yourself."),
    FlagDef("ADD-12", "Pickup / courier request", "Critical", Effect.RED, "AI→Rule", "The buyer asked for a pickup or hand-over instead of tracked delivery.", "Only ship with tracking to the PayPal address."),
    FlagDef("ADD-12A", "Possible pickup request (ext)", "High", Effect.YELLOW, "AI→Rule", "The chat suggests a pickup or hand-over.", "Confirm you will ship with tracking to the PayPal address."),
    FlagDef("ADD-14", "Different recipient name requested (ext)", "Medium", Effect.YELLOW, "AI→Rule", "The buyer asked for a different name on the parcel.", "Check that the address stays the PayPal address."),
    FlagDef("ADD-19", "Format-only difference", "Low", Effect.NONE, "Rule", "The addresses differ only in formatting.", "No action needed."),
    FlagDef("AI-01", "Image unreadable", "High", Effect.GREY, "AI", "The label photo could not be read reliably.", "Upload a clearer photo of the label."),
    FlagDef("AI-02", "Conversation incomplete", "Medium", Effect.YELLOW, "AI", "The chat looks cropped or incomplete.", "Upload the rest of the conversation."),
    FlagDef("AI-12", "Multiple labels", "High", Effect.YELLOW, "AI", "More than one label was detected in the photo.", "Upload a photo of just one label."),
    FlagDef("AI-15", "Unsourced extraction discarded", "High", Effect.YELLOW, "Rule", "Some AI findings could not be traced to the evidence and were discarded.", "Review the chat yourself."),
    FlagDef("AI-20", "Low confidence", "Medium", Effect.YELLOW, "Rule", "The AI is not confident about what it read.", "Please verify manually."),
    FlagDef("AI-30", "Suspicious instructions in chat (ext)", "High", Effect.YELLOW, "AI→Rule", "The chat contains pressure or instructions aimed at skipping checks.", "Treat this buyer with care; do not skip any checks."),
    FlagDef("OFF-01", "Off-platform payment request", "High", Effect.YELLOW, "AI→Rule", "The buyer asked to pay outside PayPal.", "Payments outside PayPal are not covered by PayPal."),
    FlagDef("SYS-01", "AI check unavailable", "High", Effect.GREY, "System", "The AI check could not run.", "Retry the AI check."),
    FlagDef("SYS-03", "AI check running (ext)", "Low", Effect.GREY, "System", "The AI is still reading the evidence.", "Wait a few seconds."),
    FlagDef("CHAT-00", "No chat checked (ext)", "Low", Effect.INFO, "Rule", "No buyer chat was uploaded.", "If you talked to the buyer, upload the chat too."),
]

REGISTRY: dict[str, FlagDef] = {d.code: d for d in _DEFS}
