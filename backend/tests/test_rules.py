"""F3: table-driven tests for the deterministic decision engine (PRD §8.3) and address comparison."""
from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest

from app.rules.address import compare
from app.rules.engine import EvaluationContext, ExtractionInput, evaluate
from app.rules.normalize import norm_line, norm_state, norm_zip

PROTECTED = {"name": "Jane Doe", "line1": "123 Main St", "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": "10001", "country": "US"}


def label(**over) -> ExtractionInput:
    addr = {"line1": "123 MAIN ST", "line2": "APT 4B", "city": "NEW YORK", "state": "NY", "postal_code": "10001", "country": "US"}
    addr.update(over.pop("address", {}))
    out = {"labels_detected": 1, "recipient_name": "JANE DOE", "address": addr, "tracking_number_visible": None,
           "carrier_visible": "USPS", "readable": True, "issues": [], "field_confidence": {}, "confidence": 0.95}
    out.update(over)
    return ExtractionInput("lab1", "SUCCEEDED", out, ["u_label"])


def chat(*requests, complete=True, issues=None, confidence=0.9, notes=None, status="SUCCEEDED") -> ExtractionInput:
    out = {"messages_observed": 4, "conversation_complete": complete, "requests": list(requests),
           "addresses_mentioned": [], "issues": issues or [], "confidence": confidence}
    return ExtractionInput("ch1", status, out if status == "SUCCEEDED" else None, ["u_chat"], notes or [])


def req(type_="ADDRESS_CHANGE", status="EXPLICIT", speaker="BUYER", address=None):
    return {"type": type_, "status": status, "speaker": speaker, "quote": "please ship to my friend in Austin",
            "source_ref": {"upload_id": "u_chat", "position": 3}, "requested_address": address}


def ctx(**over) -> EvaluationContext:
    base = dict(payment_state="PAYMENT_COMPLETED", seller_protection="ELIGIBLE", amount=Decimal("300.00"), currency="USD",
                transaction_date=date(2026, 11, 4), protected_address=copy.deepcopy(PROTECTED), label=label(),
                label_uploaded=True, chats=[chat()], chats_uploaded=True)
    base.update(over)
    return EvaluationContext(**base)


def codes(d):
    return {f.code for f in d.flags}


CASES = [
    # id, overrides, expected verdict, must-have codes, must-not-have codes
    ("clean_green", {}, "GREEN", set(), {"ADD-03"}),
    ("pay01_pending", {"payment_state": "PAYMENT_PENDING"}, "GREY", {"PAY-01"}, set()),
    ("pay02_failed", {"payment_state": "PAYMENT_FAILED"}, "RED", {"PAY-02"}, set()),
    ("pay04_partial", {"payment_state": "PARTIALLY_REFUNDED"}, "YELLOW", {"PAY-04"}, set()),
    ("pay05_refunded", {"payment_state": "REFUNDED"}, "RED", {"PAY-05"}, set()),
    ("pay05_reversed", {"payment_state": "REVERSED"}, "RED", {"PAY-05"}, set()),
    ("sp01_not_eligible_info", {"seller_protection": "NOT_ELIGIBLE"}, "GREEN", {"SP-01"}, set()),
    ("sp02_partial_info", {"seller_protection": "PARTIALLY_ELIGIBLE"}, "GREEN", {"SP-02"}, set()),
    ("sp_unknown_ok", {"seller_protection": "UNKNOWN"}, "GREEN", set(), {"SP-01"}),
    ("sp09_after_cutoff_info", {"amount": Decimal("800")}, "GREEN", {"SP-09"}, set()),
    ("sp09_before_cutoff_yellow", {"amount": Decimal("800"), "transaction_date": date(2026, 1, 10)}, "YELLOW", {"SP-09"}, set()),
    ("sp09_below_threshold", {"amount": Decimal("749.99"), "transaction_date": date(2026, 1, 10)}, "GREEN", set(), {"SP-09"}),
    ("sp09_exact_threshold", {"amount": Decimal("750.00")}, "GREEN", {"SP-09"}, set()),
    ("add01_no_address", {"protected_address": None}, "GREY", {"ADD-01"}, set()),
    ("add02_no_label", {"label": None, "label_uploaded": False}, "GREY", {"ADD-02"}, set()),
    ("label_pending", {"label": None, "label_uploaded": True, "extraction_pending": True}, "GREY", {"SYS-03"}, set()),
    ("add03_explicit_buyer", {"chats": [chat(req())]}, "RED", {"ADD-03"}, set()),
    ("add03a_ambiguous", {"chats": [chat(req(status="AMBIGUOUS"))]}, "YELLOW", {"ADD-03A"}, {"ADD-03"}),
    ("add03a_seller_suggestion", {"chats": [chat(req(speaker="SELLER"))]}, "YELLOW", {"ADD-03A"}, {"ADD-03"}),
    ("add03a_unknown_speaker", {"chats": [chat(req(speaker="UNKNOWN"))]}, "YELLOW", {"ADD-03A"}, {"ADD-03"}),
    ("cancelled_request_ignored", {"chats": [chat(req(status="CANCELLED"))]}, "GREEN", set(), {"ADD-03", "ADD-03A"}),
    ("request_matches_protected", {"chats": [chat(req(address={"city": "New York", "state": "NY", "postal_code": "10001"}))]}, "GREEN", set(), {"ADD-03"}),
    ("request_other_city_same_state", {"chats": [chat(req(address={"city": "Buffalo", "state": "NY"}))]}, "RED", {"ADD-03"}, set()),
    ("add12_pickup", {"chats": [chat(req("PICKUP_OR_COURIER"))]}, "RED", {"ADD-12"}, set()),
    ("add12a_pickup_ambiguous", {"chats": [chat(req("PICKUP_OR_COURIER", "AMBIGUOUS"))]}, "YELLOW", {"ADD-12A"}, {"ADD-12"}),
    ("off01_off_platform", {"chats": [chat(req("OFF_PLATFORM_PAYMENT"))]}, "YELLOW", {"OFF-01"}, set()),
    ("add14_name_change", {"chats": [chat(req("NAME_CHANGE"))]}, "YELLOW", {"ADD-14"}, set()),
    ("ai30_injection", {"chats": [chat(req("OTHER_RISK"))]}, "YELLOW", {"AI-30"}, set()),
    ("ai02_cropped", {"chats": [chat(complete=False)]}, "YELLOW", {"AI-02"}, set()),
    ("ai02_suppressed_by_explicit", {"chats": [chat(req(), complete=False)]}, "RED", {"ADD-03"}, {"AI-02"}),
    ("ai20_chat_low_conf", {"chats": [chat(confidence=0.5)]}, "YELLOW", {"AI-20"}, set()),
    ("ai15_unsourced", {"chats": [chat(notes=["AI-15: dropped"])]}, "YELLOW", {"AI-15"}, set()),
    ("sys01_chat_failed", {"chats": [chat(status="PROVIDER_UNAVAILABLE")]}, "GREY", {"SYS-01"}, set()),
    ("chat00_no_chat_info", {"chats": [], "chats_uploaded": False}, "GREEN", {"CHAT-00"}, set()),
    ("ai01_unreadable", {"label": label(readable=False)}, "GREY", {"AI-01"}, set()),
    ("ai12_multiple_labels", {"label": label(labels_detected=2)}, "YELLOW", {"AI-12"}, set()),
    ("ai20_label_low_conf", {"label": label(confidence=0.4)}, "YELLOW", {"AI-20"}, set()),
    ("sys01_label_failed", {"label": ExtractionInput("x", "EXTRACTION_FAILED", None, ["u"])}, "GREY", {"SYS-01"}, set()),
    ("add05_zip_mismatch", {"label": label(address={"postal_code": "10010"})}, "RED", {"ADD-05"}, set()),
    ("add04_city_mismatch", {"label": label(address={"city": "Brooklyn"})}, "RED", {"ADD-04"}, set()),
    ("add04_state_mismatch", {"label": label(address={"state": "NJ"})}, "RED", {"ADD-04"}, set()),
    ("add06_country_mismatch", {"label": label(address={"country": "CA"})}, "RED", {"ADD-06"}, set()),
    ("add08_street_mismatch", {"label": label(address={"line1": "2211 N First St"})}, "RED", {"ADD-08"}, set()),
    ("add10_street_fuzzy", {"label": label(address={"line1": "123 Mian St"})}, "YELLOW", {"ADD-10"}, {"ADD-08"}),
    ("add08_house_number_differs", {"label": label(address={"line1": "1 Main St"})}, "RED", {"ADD-08"}, set()),
    ("add08_digits_transposed", {"label": label(address={"line1": "132 Main St"})}, "RED", {"ADD-08"}, set()),
    ("add07_unit_missing", {"label": label(address={"line2": None})}, "YELLOW", {"ADD-07"}, set()),
    ("add19_format_only", {"label": label(address={"line1": "123 Main Street", "state": "New York", "postal_code": "10001-1234"})}, "GREEN", {"ADD-19"}, set()),
    ("add09_name_differs", {"label": label(recipient_name="Robert Smith")}, "YELLOW", {"ADD-09"}, set()),
    ("add09_case_only_ok", {"label": label(recipient_name="jane doe")}, "GREEN", set(), {"ADD-09"}),
    ("label_country_omitted_ok", {"label": label(address={"country": None})}, "GREEN", set(), {"ADD-06"}),
    ("add11_non_us", {"protected_address": dict(PROTECTED, country="GB")}, "YELLOW", {"ADD-11"}, set()),
    ("red_beats_grey", {"payment_state": "PAYMENT_PENDING", "chats": [chat(req())]}, "RED", {"ADD-03", "PAY-01"}, set()),
    ("grey_beats_yellow", {"label": None, "label_uploaded": False, "chats": [chat(req("OFF_PLATFORM_PAYMENT"))]}, "GREY", {"ADD-02", "OFF-01"}, set()),
    ("demo_order_two_reds", {"label": label(address={"line1": "1 Main St", "line2": None}), "chats": [chat(req())]}, "RED", {"ADD-03", "ADD-08"}, set()),
]


@pytest.mark.parametrize("case_id,over,verdict,must,must_not", CASES, ids=[c[0] for c in CASES])
def test_engine_cases(case_id, over, verdict, must, must_not):  # AC3.1
    d = evaluate(ctx(**over))
    assert d.verdict == verdict, (case_id, [(f.code, f.effect) for f in d.flags])
    assert must <= codes(d), (case_id, codes(d))
    assert not (must_not & codes(d)), (case_id, codes(d))


def test_case_count_meets_prd():
    assert len(CASES) >= 40


def test_green_says_not_a_guarantee():  # AC3.3
    d = evaluate(ctx())
    assert d.verdict == "GREEN" and "not a guarantee" in d.headline


def test_red_has_quote_and_recommended_action():  # AC3.2
    d = evaluate(ctx(chats=[chat(req())]))
    f = next(f for f in d.flags if f.code == "ADD-03")
    assert "Austin" in f.detail and f.source_ref["upload_id"] == "u_chat"
    assert "PayPal address" in d.recommended_action


def test_checks_list_is_complete():
    keys = [c.key for c in evaluate(ctx()).checks]
    assert keys == ["payment", "address", "protection", "signature", "chat", "label", "match"]


def test_engine_is_deterministic():
    a, b = evaluate(ctx(chats=[chat(req())])), evaluate(ctx(chats=[chat(req())]))
    assert a.explanation() == b.explanation() and [f.code for f in a.flags] == [f.code for f in b.flags]


# ---------- address comparison ----------
@pytest.mark.parametrize(
    "label_addr,overall",
    [
        ({"line1": "123 Main St", "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": "10001", "country": "US"}, "MATCH"),
        ({"line1": "123 MAIN STREET", "line2": "Apartment 4B", "city": "new york", "state": "New York", "postal_code": "10001-0001"}, "FORMAT_ONLY_DIFFERENCE"),
        ({"line1": "123 Mian St", "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": "10001"}, "FUZZY"),
        ({"line1": "1 Main St", "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": "10001"}, "MISMATCH"),
        ({"line1": "9 River Rd", "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": "10001"}, "MISMATCH"),
        ({"line1": "123 Main St", "line2": "Apt 4B", "city": "New York", "state": "NY", "postal_code": None}, "INSUFFICIENT_DATA"),
    ],
)
def test_compare_overall(label_addr, overall):
    assert compare(PROTECTED, label_addr).overall == overall


def test_compare_flags_missing_unit():
    res = compare(PROTECTED, {"line1": "123 Main St", "city": "New York", "state": "NY", "postal_code": "10001"})
    assert res.get("line2").result == "MISSING_ON_LABEL"


@pytest.mark.parametrize("value", ["123 Main Street, Apt. #4B", "  42 north oak AVENUE  ", "PO Box 12", "1 Main St Unit 7"])
def test_normalisation_is_idempotent(value):  # property-style check
    assert norm_line(norm_line(value)) == norm_line(value)


def test_state_and_zip_normalisation():
    assert norm_state("texas") == "TX" and norm_state("TX") == "TX"
    assert norm_zip("78701-1234") == "78701" and norm_zip("787") == "787"
