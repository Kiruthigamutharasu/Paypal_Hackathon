"""Decision engine (PRD §8). Deterministic: same inputs -> same verdict. No AI, no I/O.

Precedence: RED > GREY > YELLOW > GREEN. INFO/NONE flags never change the verdict.
GREEN means "our checks passed on the evidence provided" — never "guaranteed protected".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.rules.address import compare, names_differ
from app.rules.flags import REGISTRY, Effect
from app.rules.normalize import norm_city, norm_state, norm_zip
from app.rules.policy import RULES_VERSION, signature_requirement

VERDICT_ORDER = ["RED", "GREY", "YELLOW", "GREEN"]
HEADLINES = {
    "GREEN": "Checks passed — safe to ship to the PayPal address (not a guarantee of Seller Protection)",
    "YELLOW": "Review needed before shipping",
    "RED": "Shipment blocked",
    "GREY": "Cannot evaluate yet",
}


@dataclass
class ExtractionInput:
    extraction_id: str
    status: str  # SUCCEEDED | EXTRACTION_FAILED | PROVIDER_UNAVAILABLE
    output: dict[str, Any] | None
    upload_ids: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class EvaluationContext:
    payment_state: str
    seller_protection: str = "UNKNOWN"
    amount: Decimal | None = None
    currency: str | None = "USD"
    transaction_date: date | None = None
    protected_address: dict[str, Any] | None = None  # name, line1, line2, city, state, postal_code, country
    label: ExtractionInput | None = None
    label_uploaded: bool = False
    chats: list[ExtractionInput] = field(default_factory=list)
    chats_uploaded: bool = False
    extraction_pending: bool = False
    signature_threshold_usd: float = 750.0
    confidence_threshold: float = 0.7


@dataclass
class FlagHit:
    code: str
    name: str
    effect: str
    severity: str
    message: str
    action: str
    detail: str | None = None
    source_ref: dict[str, Any] | None = None


@dataclass
class Check:
    key: str
    label: str
    status: str  # pass | fail | warn | pending | na | info
    detail: str


@dataclass
class Decision:
    verdict: str
    headline: str
    flags: list[FlagHit]
    checks: list[Check]
    comparison: dict[str, Any] | None
    recommended_action: str
    rules_version: str = RULES_VERSION
    ignored: list[str] = field(default_factory=list)

    def explanation(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "checks": [asdict(c) for c in self.checks],
            "comparison": self.comparison,
            "recommended_action": self.recommended_action,
            "ignored": self.ignored,
        }


def _hit(code: str, detail: str | None = None, source_ref: dict | None = None,
         effect: Effect | None = None, message: str | None = None) -> FlagHit:
    d = REGISTRY[code]
    return FlagHit(code, d.name, str(effect or d.effect), d.severity, message or d.message, d.action, detail, source_ref)


def _matches_protected(req_addr: dict | None, protected: dict | None) -> bool:
    """A chat 'change' that already equals the protected address (e.g. after Safe re-pay) is not a risk."""
    if not req_addr or not protected:
        return False
    city, state, zp = req_addr.get("city"), req_addr.get("state"), req_addr.get("postal_code")
    if not city and not zp:
        return False
    if city and norm_city(city) != norm_city(protected.get("city")):
        return False
    if state and norm_state(state) != norm_state(protected.get("state")):
        return False
    if zp and norm_zip(zp) != norm_zip(protected.get("postal_code")):
        return False
    return True


def evaluate(ctx: EvaluationContext) -> Decision:
    flags: list[FlagHit] = []
    checks: list[Check] = []
    ignored: list[str] = []
    comparison_dict: dict | None = None
    thr = ctx.confidence_threshold

    # ---- payment (from PayPal) ----
    pay = {
        "PAYMENT_PENDING": "PAY-01",
        "PAYMENT_FAILED": "PAY-02",
        "PARTIALLY_REFUNDED": "PAY-04",
        "REFUNDED": "PAY-05",
        "REVERSED": "PAY-05",
    }.get(ctx.payment_state)
    if pay:
        flags.append(_hit(pay, ctx.payment_state))
    checks.append(Check("payment", "Payment completed on PayPal", "pass" if not pay else "fail", ctx.payment_state.replace("_", " ").lower()))

    # ---- protected address ----
    addr = ctx.protected_address
    if not addr or not (addr.get("line1") or addr.get("city")):
        flags.append(_hit("ADD-01"))
        checks.append(Check("address", "Protected address on the PayPal payment", "fail", "missing"))
        addr = None
    else:
        checks.append(Check("address", "Protected address on the PayPal payment", "pass",
                            ", ".join(p for p in [addr.get("city"), addr.get("state")] if p)))

    # ---- policy: Seller Protection status + signature ----
    sp = ctx.seller_protection or "UNKNOWN"
    if sp == "NOT_ELIGIBLE":
        flags.append(_hit("SP-01"))
    elif sp == "PARTIALLY_ELIGIBLE":
        flags.append(_hit("SP-02"))
    checks.append(Check("protection", "Seller Protection status (from PayPal)", "info" if sp != "ELIGIBLE" else "pass", sp.replace("_", " ").lower()))

    sig = signature_requirement(ctx.amount, ctx.currency, (addr or {}).get("country"), ctx.transaction_date, ctx.signature_threshold_usd)
    if sig == "REQUIRED":
        flags.append(_hit("SP-09", f"total ≥ ${ctx.signature_threshold_usd:,.0f}, before 2026-01-26", effect=Effect.YELLOW,
                          message="Signature confirmation is required for this amount."))
        checks.append(Check("signature", "Signature confirmation", "warn", "required"))
    elif sig == "RECOMMENDED":
        flags.append(_hit("SP-09", f"total ≥ ${ctx.signature_threshold_usd:,.0f}", message="Signature confirmation is recommended for this amount."))
        checks.append(Check("signature", "Signature confirmation", "info", "recommended"))
    else:
        checks.append(Check("signature", "Signature confirmation", "na", "not needed for this amount"))

    # ---- chats ----
    if ctx.extraction_pending:
        flags.append(_hit("SYS-03"))
    explicit_found = False
    chat_status = "na"
    chat_detail = "no chat uploaded"
    if ctx.chats_uploaded or ctx.chats:
        chat_status, chat_detail = "pass", "no risky requests"
    for ex in ctx.chats:
        if ex.status != "SUCCEEDED" or not ex.output:
            flags.append(_hit("SYS-01", "chat check failed — retry"))
            chat_status, chat_detail = "fail", "AI check failed"
            continue
        out = ex.output
        for req in out.get("requests", []):
            t, st, who = req.get("type"), req.get("status"), req.get("speaker")
            src = req.get("source_ref")
            quote = req.get("quote")
            if st == "CANCELLED":
                ignored.append(f"Cancelled request ignored: “{quote}”")
                continue
            if t == "ADDRESS_CHANGE":
                if _matches_protected(req.get("requested_address"), addr):
                    ignored.append(f"Request already matches the PayPal address: “{quote}”")
                    continue
                if st == "EXPLICIT" and who == "BUYER":
                    flags.append(_hit("ADD-03", quote, src))
                    explicit_found = True
                else:
                    flags.append(_hit("ADD-03A", quote, src))
            elif t == "PICKUP_OR_COURIER":
                if st == "EXPLICIT" and who == "BUYER":
                    flags.append(_hit("ADD-12", quote, src))
                    explicit_found = True
                else:
                    flags.append(_hit("ADD-12A", quote, src))
            elif t == "OFF_PLATFORM_PAYMENT":
                flags.append(_hit("OFF-01", quote, src))
            elif t == "NAME_CHANGE":
                flags.append(_hit("ADD-14", quote, src))
            elif t == "OTHER_RISK":
                flags.append(_hit("AI-30", quote, src))
        if (not out.get("conversation_complete", True) or "CROPPED" in out.get("issues", [])) and not explicit_found:
            flags.append(_hit("AI-02"))
        if out.get("confidence", 1.0) < thr:
            flags.append(_hit("AI-20", f"chat confidence {out['confidence']:.2f}"))
        if ex.notes:
            flags.append(_hit("AI-15", f"{len(ex.notes)} finding(s) discarded"))
    chat_codes = {"ADD-03", "ADD-12"}
    chat_review = {"ADD-03A", "ADD-12A", "OFF-01", "ADD-14", "AI-30", "AI-02"}
    if any(f.code in chat_codes for f in flags):
        chat_status, chat_detail = "fail", "risky request found"
    elif any(f.code in chat_review for f in flags) and chat_status != "fail":
        chat_status, chat_detail = "warn", "needs your review"
    if not ctx.chats_uploaded and not ctx.chats:
        flags.append(_hit("CHAT-00"))
    if ctx.extraction_pending and chat_status == "na" and ctx.chats_uploaded:
        chat_status, chat_detail = "pending", "AI is reading"
    checks.append(Check("chat", "Buyer chat checked", chat_status, chat_detail))

    # ---- label ----
    label_status, label_detail = "fail", "no label uploaded"
    match_status, match_detail = "na", "needs a readable label"
    lab = ctx.label
    if not ctx.label_uploaded and lab is None:
        flags.append(_hit("ADD-02"))
    elif lab is None:
        label_status, label_detail = "pending", "AI is reading"
    elif lab.status != "SUCCEEDED" or not lab.output:
        flags.append(_hit("SYS-01", "label check failed — retry"))
        label_detail = "AI check failed"
    else:
        out = lab.output
        if not out.get("readable", True):
            flags.append(_hit("AI-01"))
            label_detail = "not readable"
        else:
            label_status, label_detail = "pass", "readable"
            if out.get("labels_detected", 1) > 1:
                flags.append(_hit("AI-12", f"{out['labels_detected']} labels"))
            if out.get("confidence", 1.0) < thr:
                flags.append(_hit("AI-20", f"label confidence {out['confidence']:.2f}"))
                label_status = "warn"
            if addr is not None:
                cmp = compare(addr, out.get("address") or {})
                comparison_dict = cmp.as_dict()
                res = {f.field: f for f in cmp.fields}
                if cmp.overall == "INSUFFICIENT_DATA":
                    flags.append(_hit("ADD-11"))
                for fname, code in (("city", "ADD-04"), ("state", "ADD-04"), ("postal_code", "ADD-05"), ("country", "ADD-06"), ("line1", "ADD-08")):
                    fr = res.get(fname)
                    if fr and fr.result == "MISMATCH":
                        flags.append(_hit(code, f"PayPal: {fr.paypal or '—'} · Label: {fr.label or '—'}"))
                if res.get("line1") and res["line1"].result == "FUZZY":
                    fr = res["line1"]
                    flags.append(_hit("ADD-10", f"PayPal: {fr.paypal} · Label: {fr.label}"))
                if res.get("line2") and res["line2"].result == "MISSING_ON_LABEL":
                    flags.append(_hit("ADD-07", f"PayPal unit: {res['line2'].paypal}"))
                if cmp.overall == "FORMAT_ONLY_DIFFERENCE":
                    flags.append(_hit("ADD-19"))
                if names_differ(addr.get("name"), out.get("recipient_name")) and cmp.overall in ("MATCH", "FORMAT_ONLY_DIFFERENCE"):
                    flags.append(_hit("ADD-09", f"PayPal: {addr.get('name')} · Label: {out.get('recipient_name')}"))
                match_status = {"MATCH": "pass", "FORMAT_ONLY_DIFFERENCE": "pass", "FUZZY": "warn", "MISMATCH": "fail"}.get(cmp.overall, "warn")
                match_detail = {"MATCH": "label matches the PayPal address", "FORMAT_ONLY_DIFFERENCE": "matches (formatting differs only)",
                                "FUZZY": "almost matches — check the street", "MISMATCH": "label does NOT match the PayPal address"}.get(cmp.overall, "could not compare fully")
    checks.append(Check("label", "Shipping label readable", label_status, label_detail))
    checks.append(Check("match", "Label matches the PayPal address", match_status, match_detail))

    # ---- verdict ----
    effects = {f.effect for f in flags}
    verdict = next((v for v in ("RED", "GREY", "YELLOW") if v in effects), "GREEN")
    blocking = [f for f in flags if f.effect == verdict] if verdict != "GREEN" else []
    severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    blocking.sort(key=lambda f: severity_rank.get(f.severity, 9))
    recommended = blocking[0].action if blocking else "Ship to the PayPal address with tracking, then register the tracking number."
    return Decision(verdict, HEADLINES[verdict], flags, checks, comparison_dict, recommended, RULES_VERSION, ignored)
