"""Dispute Defense Agent (F5).

1. Read-only "tools" gather facts from our database (order, capture, protected address, shipments, decision
   history, label extraction, timeline). No write access, no PayPal access.
2. Planner: reason-specific evidence rules enforced in code (MVP: item-not-received and unauthorised).
3. Evidence Writer: the AI turns the facts into a short factual note (template fallback). The claim verifier
   (rules/claims.py) then checks every claim before the seller can submit.

Deviation from the PRD's bounded tool loop: facts are gathered by code and given to the model in one structured
call. It is cheaper on the free AI tier and keeps the model away from any tool that could act.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import Provider, TextPart, generate_structured
from app.models import AuditLog, Dispute, Order, Shipment, ShippingDecision, Upload
from app.rules.claims import Facts

PROMPT_VERSION = "dd-1.0"
NOTE_MAX = 1000

INR = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED"}
UNAUTH = {"UNAUTHORISED", "UNAUTHORIZED"}

WRITER_PROMPT = """\
You write the seller's note for a PayPal dispute. Use ONLY the facts provided in FACTS.
Rules:
- Plain, factual, polite, first person ("I shipped..."). At most 900 characters. No markdown, no greetings.
- State: what was sold and the amount; that the parcel was shipped to the shipping address on the PayPal
  transaction (city, state, ZIP); carrier and tracking number exactly as given; the ship date; that tracking was
  registered with PayPal.
- Never say the parcel was delivered unless DELIVERED is true. Never mention signatures unless SIGNATURE is true.
- Do not invent dates, numbers, names or events. Do not threaten, speculate or promise outcomes.
- Return JSON: {"note": "..."}
"""


class EvidenceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=40, max_length=NOTE_MAX)


@dataclass
class Plan:
    reason: str
    supported: bool
    evidence_type: str | None
    tracking_info: list[dict[str, str]] = field(default_factory=list)
    file_upload_ids: list[str] = field(default_factory=list)
    include_summary_pdf: bool = True
    rationale: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    manual_checklist: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# ---------------- read-only tools ----------------
def _d(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def gather_facts(db: Session, dispute: Dispute) -> dict[str, Any]:
    order = db.get(Order, dispute.order_id) if dispute.order_id else None
    if order is None:
        return {"dispute_id": dispute.paypal_dispute_id, "order_found": False}
    cap = next((c for c in order.captures if c.paypal_capture_id == dispute.disputed_capture_id), None) or order.latest_capture
    addr = order.active_address
    ships = list(db.scalars(select(Shipment).where(Shipment.order_id == order.id).order_by(Shipment.created_at)))
    live = [s for s in ships if s.status in ("SHIPPED", "DELIVERED")]
    decision = db.scalar(select(ShippingDecision).where(ShippingDecision.order_id == order.id, ShippingDecision.status == "ACTIVE"))
    label = db.scalar(select(Upload).where(Upload.order_id == order.id, Upload.kind == "LABEL_IMAGE", Upload.superseded_by.is_(None)))
    comparison = (decision.explanation or {}).get("comparison") if decision else None
    label_fields = {f["field"]: f.get("label") for f in (comparison or {}).get("fields", [])}
    events = db.scalars(select(AuditLog).where(AuditLog.order_id == order.id, AuditLog.action.in_([
        "ORDER_CREATED", "PROTECTED_ADDRESS_RECORDED", "EVIDENCE_UPLOADED", "DECISION_MADE", "DECISION_ACKNOWLEDGED",
        "DECISION_OVERRIDDEN", "TRACKING_REGISTERED", "REPAY_PAID"])).order_by(AuditLog.created_at)).all()
    return {
        "dispute_id": dispute.paypal_dispute_id,
        "order_found": True,
        "order_id": order.id,
        "paypal_order_id": order.current_paypal_order_id or order.paypal_order_id,
        "original_paypal_order_id": order.paypal_order_id,
        "capture_id": cap.paypal_capture_id if cap else None,
        "amount": str(cap.amount if cap and cap.amount is not None else order.amount),
        "currency": order.currency or "USD",
        "payment_date": (_d(cap.paypal_create_time) if cap else None),
        "item": order.item_description,
        "protected_address": addr.fields() if addr else None,
        "verdict": f"{decision.verdict}{' (' + decision.resolution.lower() + ')' if decision and decision.resolution != 'NONE' else ''}" if decision else None,
        "overridden": bool(decision and decision.resolution == "OVERRIDDEN"),
        "label": {
            "upload_id": label.id if label else None,
            "mime": label.mime if label else None,
            "address_text": ", ".join(v for v in [label_fields.get("line1"), label_fields.get("city"), label_fields.get("state"), label_fields.get("postal_code")] if v) or None,
            "comparison": (comparison or {}).get("overall"),
        },
        "shipments": [{"carrier": s.carrier if s.carrier != "OTHER" else (s.carrier_name_other or "OTHER"), "carrier_code": s.carrier,
                       "carrier_name_other": s.carrier_name_other, "tracking_number": s.tracking_number, "ship_date": s.ship_date,
                       "registered_at": s.registered_at.date().isoformat() if s.registered_at else None, "status": s.status,
                       "tracker_id": s.paypal_tracker_id} for s in live],
        "delivered": any(s.status == "DELIVERED" for s in live),
        "dispute_created": _d(dispute.paypal_create_time),
        "timeline": [{"when": e.created_at.strftime("%Y-%m-%d %H:%M"), "what": e.action.replace("_", " ").lower()} for e in events],
    }


def facts_for_verifier(facts: dict[str, Any], dispute: Dispute) -> Facts:
    f = Facts()
    for s in facts.get("shipments", []):
        f.tracking_numbers.add(s["tracking_number"])
        if s.get("tracker_id"):
            f.ids.add(s["tracker_id"])
        for k in ("ship_date", "registered_at"):
            if s.get(k):
                f.dates.add(date.fromisoformat(s[k]))
    for k in ("paypal_order_id", "original_paypal_order_id", "capture_id"):
        if facts.get(k):
            f.ids.add(facts[k])
    f.ids.add(dispute.paypal_dispute_id)
    if facts.get("amount") and facts["amount"] != "None":
        f.amounts.add(Decimal(facts["amount"]).quantize(Decimal("0.01")))
        f.amounts.add(Decimal(facts["amount"]).quantize(Decimal("1")))
    if dispute.amount is not None:
        f.amounts.add(Decimal(dispute.amount).quantize(Decimal("0.01")))
    if facts.get("payment_date"):
        f.dates.add(facts["payment_date"])
    if facts.get("dispute_created"):
        f.dates.add(facts["dispute_created"])
    a = facts.get("protected_address") or {}
    if a.get("postal_code"):
        f.zips.add(re.sub(r"\D", "", a["postal_code"])[:5])
    f.delivered = bool(facts.get("delivered"))
    return f


# ---------------- planner (rules enforced in code) ----------------
def plan(dispute: Dispute, facts: dict[str, Any]) -> Plan:
    reason = (dispute.reason or "OTHER").upper()
    p = Plan(reason=reason, supported=reason in INR | UNAUTH, evidence_type=None)
    if not facts.get("order_found"):
        p.supported = False
        p.missing.append("This dispute is not linked to an order in StayCovered.")
        return p
    if not p.supported:
        p.manual_checklist = [
            "Read the buyer's claim in your PayPal Resolution Center.",
            "Collect photos/description proving the item matched the listing.",
            "Respond in PayPal before the deadline; StayCovered only automates item-not-received and unauthorised disputes.",
        ]
        return p
    ships = facts.get("shipments") or []
    p.evidence_type = "PROOF_OF_FULFILLMENT"
    for s in ships:
        info = {"carrier_name": s["carrier_code"], "tracking_number": s["tracking_number"]}
        if s["carrier_code"] == "OTHER":
            info["carrier_name_other"] = s.get("carrier_name_other") or "Other"
        p.tracking_info.append(info)
    if not ships:
        p.missing.append("No tracking registered with PayPal for this order — proof of fulfillment needs tracking.")
    else:
        p.rationale.append("Tracking was registered with PayPal at dispatch (carrier + number).")
    if facts["label"].get("upload_id"):
        p.file_upload_ids.append(facts["label"]["upload_id"])
        p.rationale.append("Label photo shows the parcel was addressed to the PayPal shipping address.")
    if facts["label"].get("comparison") in ("MATCH", "FORMAT_ONLY_DIFFERENCE"):
        p.rationale.append("Pre-shipment check: label matched the protected address.")
    if facts.get("overridden"):
        p.info.append("The pre-shipment verdict was overridden by the seller; Seller Protection may not apply.")
    if reason in UNAUTH:
        p.rationale.append("Unauthorised claim: shipment went to the address on the PayPal transaction (transaction evidence attached).")
    created = facts.get("dispute_created")
    for s in ships:
        if created and s.get("registered_at") and date.fromisoformat(s["registered_at"]) > created:
            p.info.append(f"SHP-15: tracking {s['tracking_number']} was registered after the dispute was opened.")
    p.rationale.append("One-page summary PDF of PayPal facts, label check, tracking and timeline.")
    return p


# ---------------- evidence writer ----------------
def template_note(facts: dict[str, Any]) -> str:
    a = facts.get("protected_address") or {}
    ships = facts.get("shipments") or []
    s = ships[0] if ships else None
    parts = [f"I sold the {facts.get('item') or 'item'} for ${facts.get('amount')} {facts.get('currency')} through PayPal."]
    if s:
        parts.append(
            f"I shipped it on {s['ship_date']} with {s['carrier']}, tracking number {s['tracking_number']}, to the shipping address "
            f"on the PayPal transaction in {a.get('city')}, {a.get('state')} {a.get('postal_code')}."
        )
        parts.append("The tracking number was registered with PayPal when the parcel was shipped.")
    if facts.get("delivered"):
        parts.append("The carrier shows the parcel as delivered.")
    parts.append("The attached label photo and summary show the parcel was addressed to the PayPal shipping address.")
    return " ".join(parts)[:NOTE_MAX]


def write_note(provider: Provider | None, facts: dict[str, Any]) -> tuple[str, str]:
    if provider is not None and facts.get("shipments"):
        a = facts.get("protected_address") or {}
        s = facts["shipments"][0]
        payload = (
            f"FACTS:\nITEM: {facts.get('item')}\nAMOUNT: ${facts.get('amount')} {facts.get('currency')}\n"
            f"PAYPAL ADDRESS: {a.get('city')}, {a.get('state')} {a.get('postal_code')}\nCARRIER: {s['carrier']}\n"
            f"TRACKING NUMBER: {s['tracking_number']}\nSHIP DATE: {s['ship_date']}\nTRACKING REGISTERED WITH PAYPAL: {s['registered_at']}\n"
            f"LABEL MATCHED PAYPAL ADDRESS: {facts['label'].get('comparison') in ('MATCH', 'FORMAT_ONLY_DIFFERENCE')}\n"
            f"DELIVERED: {facts.get('delivered')}\nSIGNATURE: False"
        )
        try:
            res = generate_structured(provider, WRITER_PROMPT, [TextPart(payload)], EvidenceNote)
            if res.output is not None:
                return res.output.note, "AI"
        except Exception:  # noqa: BLE001 - template fallback
            pass
    return template_note(facts), "TEMPLATE"
