"""Deterministic address comparison (PRD §8.2). Pure functions, no I/O, no AI.

Field rules:
- postal_code, state, city: exact after normalisation
- line1: token-sort similarity >= 0.90 MATCH, 0.75-0.90 FUZZY, else MISMATCH
- line2 (apt/unit): present on PayPal but missing on label -> MISSING_ON_LABEL
Overall: MATCH | FORMAT_ONLY_DIFFERENCE | FUZZY | MISMATCH | INSUFFICIENT_DATA
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from rapidfuzz import fuzz

from app.rules.normalize import norm_city, norm_line, norm_state, norm_zip

LINE1_MATCH = 0.90
LINE1_FUZZY = 0.75

FIELDS = ("line1", "line2", "city", "state", "postal_code", "country")


@dataclass
class FieldResult:
    field: str
    paypal: str | None
    label: str | None
    result: str  # MATCH | FORMAT_ONLY | FUZZY | MISMATCH | MISSING_ON_LABEL | EXTRA_ON_LABEL | MISSING | NOT_COMPARED
    score: float | None = None


@dataclass
class AddressComparison:
    overall: str
    fields: list[FieldResult] = field(default_factory=list)

    def get(self, name: str) -> FieldResult | None:
        return next((f for f in self.fields if f.field == name), None)

    def as_dict(self) -> dict:
        return {"overall": self.overall, "fields": [asdict(f) for f in self.fields]}


def _country(c: str | None) -> str:
    c = (c or "").strip().upper()
    return {"USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US"}.get(c, c)


def compare(paypal: dict, label: dict) -> AddressComparison:
    """Compare the PayPal protected address with the address read from the label."""
    pp_country = _country(paypal.get("country"))
    lb_country = _country(label.get("country")) or pp_country  # labels often omit "US"
    results: list[FieldResult] = []

    if pp_country and pp_country != "US":
        return AddressComparison("INSUFFICIENT_DATA", [FieldResult("country", pp_country, lb_country, "NOT_COMPARED")])

    raw_equal = True

    def exact(name: str, a: str, b: str) -> None:
        nonlocal raw_equal
        pa, lb = paypal.get(name), label.get(name)
        if not a or not b:
            results.append(FieldResult(name, pa, lb, "MISSING"))
            return
        if a == b:
            same_raw = (pa or "").strip().upper() == (lb or "").strip().upper()
            raw_equal = raw_equal and same_raw
            results.append(FieldResult(name, pa, lb, "MATCH" if same_raw else "FORMAT_ONLY"))
        else:
            results.append(FieldResult(name, pa, lb, "MISMATCH"))

    # line1: house/box numbers must match exactly; only the street NAME is compared fuzzily
    # ("1 Main St" vs "123 Main St" is a different address, however similar the strings look).
    l1a, l1b = norm_line(paypal.get("line1")), norm_line(label.get("line1"))
    if not l1a or not l1b:
        results.append(FieldResult("line1", paypal.get("line1"), label.get("line1"), "MISSING"))
    elif _numbers(l1a) != _numbers(l1b):
        results.append(FieldResult("line1", paypal.get("line1"), label.get("line1"), "MISMATCH", 0.0))
    else:
        score = fuzz.token_sort_ratio(_words(l1a), _words(l1b)) / 100.0
        if l1a == l1b:
            same_raw = (paypal.get("line1") or "").strip().upper() == (label.get("line1") or "").strip().upper()
            raw_equal = raw_equal and same_raw
            res = "MATCH" if same_raw else "FORMAT_ONLY"
        elif score >= LINE1_MATCH:
            raw_equal = False
            res = "FORMAT_ONLY"
        elif score >= LINE1_FUZZY:
            res = "FUZZY"
        else:
            res = "MISMATCH"
        results.append(FieldResult("line1", paypal.get("line1"), label.get("line1"), res, round(score, 3)))

    # line2 (apartment / unit)
    l2a, l2b = norm_line(paypal.get("line2")), norm_line(label.get("line2"))
    if l2a and not l2b:
        results.append(FieldResult("line2", paypal.get("line2"), label.get("line2"), "MISSING_ON_LABEL"))
    elif l2b and not l2a:
        results.append(FieldResult("line2", paypal.get("line2"), label.get("line2"), "EXTRA_ON_LABEL"))
    elif l2a and l2b:
        exact("line2", l2a, l2b)
    else:
        results.append(FieldResult("line2", None, None, "MATCH"))

    exact("city", norm_city(paypal.get("city")), norm_city(label.get("city")))
    exact("state", norm_state(paypal.get("state")), norm_state(label.get("state")))
    exact("postal_code", norm_zip(paypal.get("postal_code")), norm_zip(label.get("postal_code")))
    results.append(
        FieldResult("country", pp_country or None, lb_country or None, "MATCH" if (pp_country or "US") == (lb_country or "US") else "MISMATCH")
    )

    kinds = {r.field: r.result for r in results}
    core = [kinds["line1"], kinds["city"], kinds["state"], kinds["postal_code"]]
    if "MISMATCH" in kinds.values():
        overall = "MISMATCH"
    elif "MISSING" in core:
        overall = "INSUFFICIENT_DATA"
    elif "FUZZY" in kinds.values():
        overall = "FUZZY"
    elif raw_equal and all(v in ("MATCH", "MISSING_ON_LABEL", "EXTRA_ON_LABEL") for v in kinds.values()):
        overall = "MATCH"
    else:
        overall = "FORMAT_ONLY_DIFFERENCE"
    return AddressComparison(overall, results)


def _numbers(line: str) -> list[str]:
    return [t for t in line.split() if any(ch.isdigit() for ch in t)]


def _words(line: str) -> str:
    return " ".join(t for t in line.split() if not any(ch.isdigit() for ch in t))


def names_differ(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    na, nb = norm_city(a), norm_city(b)  # uppercase + punctuation stripped
    return fuzz.token_sort_ratio(na, nb) < 85
