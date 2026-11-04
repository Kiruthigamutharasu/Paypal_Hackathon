"""Deterministic US address field normalisation (PRD §8.2). Shared by the eval harness (F2)
and the decision engine (F3). Pure functions, no I/O."""
from __future__ import annotations

import re

US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA", "COLORADO": "CO",
    "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
    "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY", "PUERTO RICO": "PR",
}

STREET_ABBR = {
    "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "ROAD": "RD", "BOULEVARD": "BLVD", "DRIVE": "DR", "LANE": "LN",
    "COURT": "CT", "PLACE": "PL", "TERRACE": "TER", "PARKWAY": "PKWY", "HIGHWAY": "HWY", "CIRCLE": "CIR",
    "SQUARE": "SQ", "SUITE": "STE", "APARTMENT": "APT", "UNIT": "APT", "#": "APT", "FLOOR": "FL",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE", "NORTHWEST": "NW",
    "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}


def _basic(s: str) -> str:
    s = s.upper().replace("#", " # ")
    s = re.sub(r"[^\w# ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_line(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(STREET_ABBR.get(t, t) for t in _basic(s).split())


def norm_city(s: str | None) -> str:
    return _basic(s) if s else ""


def norm_state(s: str | None) -> str:
    if not s:
        return ""
    b = _basic(s)
    return US_STATES.get(b, b)


def norm_zip(s: str | None) -> str:
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    return digits[:5] if len(digits) >= 5 else digits


def norm_field(field: str, value: str | None) -> str:
    if field == "postal_code":
        return norm_zip(value)
    if field == "state":
        return norm_state(value)
    if field == "city":
        return norm_city(value)
    if field in ("line1", "line2"):
        return norm_line(value)
    return _basic(value or "")
