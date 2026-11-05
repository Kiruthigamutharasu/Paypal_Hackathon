"""Claim verifier (EVD-08): every factual claim in a dispute note must be backed by stored facts.

Deterministic, no AI. It extracts tracking/ID-like tokens, money amounts, dates, ZIP codes and risky words
("delivered", "signature") from each sentence and checks them against the evidence facts. Any sentence with an
unsupported claim blocks submission and is shown to the seller.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

_SPACED_DIGITS = re.compile(r"\b\d(?:[\d ]{8,}\d)\b")
_TOKEN = re.compile(r"\b(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{9,60}\b")
_MONEY = re.compile(r"(?:\$|USD\s?)\s?([\d,]+(?:\.\d{1,2})?)", re.I)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TEXT_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.I)
_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")


@dataclass
class Facts:
    tracking_numbers: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)  # order / capture / tracker / dispute IDs
    amounts: set[Decimal] = field(default_factory=set)
    dates: set[date] = field(default_factory=set)
    zips: set[str] = field(default_factory=set)
    delivered: bool = False
    signature: bool = False


@dataclass
class SentenceCheck:
    text: str
    ok: bool
    problems: list[str] = field(default_factory=list)


@dataclass
class ClaimCheck:
    passed: bool
    sentences: list[SentenceCheck]

    def as_dict(self) -> dict:
        return {"passed": self.passed, "sentences": [asdict(s) for s in self.sentences]}


def _norm(tok: str) -> str:
    return re.sub(r"[\s-]", "", tok).upper()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _parse_text_date(m: re.Match, default_year: int) -> date | None:
    mon = MONTHS.get(m.group(1).lower()[:3])
    year = int(m.group(3)) if m.group(3) else default_year
    try:
        return date(year, mon, int(m.group(2)))
    except (TypeError, ValueError):
        return None


def verify(note: str, facts: Facts) -> ClaimCheck:
    known_tokens = {_norm(t) for t in facts.tracking_numbers | facts.ids}
    default_year = max((d.year for d in facts.dates), default=datetime.now().year)
    out: list[SentenceCheck] = []
    for sent in _sentences(note or ""):
        problems: list[str] = []
        work = sent
        # 1) dates first (an ISO date would otherwise look like an ID token)
        for m in _ISO_DATE.finditer(work):
            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                d = None
            if d not in facts.dates:
                problems.append(f"date {m.group(0)} is not a recorded payment/shipping date")
        work = _ISO_DATE.sub(" ", work)
        for m in _TEXT_DATE.finditer(work):
            d = _parse_text_date(m, default_year)
            if d not in facts.dates:
                problems.append(f"date {m.group(0)!r} is not a recorded payment/shipping date")
        work = _TEXT_DATE.sub(" ", work)
        # 2) money
        for m in _MONEY.finditer(work):
            try:
                amt = Decimal(m.group(1).replace(",", ""))
            except InvalidOperation:
                continue
            if amt not in facts.amounts:
                problems.append(f"amount ${m.group(1)} does not match the payment")
        work = _MONEY.sub(" ", work)
        # 3) long numbers written with spaces (tracking numbers), then ID-like tokens
        for m in _SPACED_DIGITS.finditer(work):
            tok = _norm(m.group(0))
            if len(tok) >= 10:
                if tok not in known_tokens:
                    problems.append(f"number {m.group(0)!r} is not a tracking number or ID on this order")
                work = work.replace(m.group(0), " ")
        for m in _TOKEN.finditer(work.upper()):
            if _norm(m.group(0)) not in known_tokens:
                problems.append(f"{m.group(0)!r} is not a tracking number or ID on this order")
            work = re.sub(re.escape(m.group(0)), " ", work, flags=re.I)
        # 4) ZIP codes
        for m in _ZIP.finditer(work):
            if m.group(0)[:5] not in facts.zips:
                problems.append(f"ZIP {m.group(0)} is not the protected address ZIP")
        low = sent.lower()
        if re.search(r"\bdelivered\b|\bdelivery (was )?confirmed\b", low) and not re.search(r"\bnot (yet )?(been )?delivered\b", low) and not facts.delivered:
            problems.append("says 'delivered' but delivery is not confirmed in our records")
        if "signature" in low and not facts.signature:
            problems.append("mentions a signature, but no signature confirmation is recorded")
        out.append(SentenceCheck(sent, not problems, problems))
    return ClaimCheck(all(s.ok for s in out) and bool(out), out)
