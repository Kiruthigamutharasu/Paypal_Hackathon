"""AI output schemas (PRD §7.4, schema_version 1.0).

These are the ONLY shapes model output may take. They are passed to the model as a JSON
schema (Gemini `response_json_schema` / Anthropic forced tool input) and then validated
again here with Pydantic.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Versioned(_Strict):
    """schema_version is stamped by our code; whatever the model writes there is ignored."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION

    @field_validator("schema_version", mode="before")
    @classmethod
    def _stamp(cls, _v: object) -> str:
        return SCHEMA_VERSION


class RequestType(StrEnum):
    ADDRESS_CHANGE = "ADDRESS_CHANGE"
    PICKUP_OR_COURIER = "PICKUP_OR_COURIER"
    OFF_PLATFORM_PAYMENT = "OFF_PLATFORM_PAYMENT"
    NAME_CHANGE = "NAME_CHANGE"
    OTHER_RISK = "OTHER_RISK"


class Speaker(StrEnum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    UNKNOWN = "UNKNOWN"


class RequestStatus(StrEnum):
    EXPLICIT = "EXPLICIT"
    AMBIGUOUS = "AMBIGUOUS"
    CANCELLED = "CANCELLED"


class ChatIssue(StrEnum):
    CROPPED = "CROPPED"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    LOW_RESOLUTION = "LOW_RESOLUTION"
    MULTIPLE_THREADS = "MULTIPLE_THREADS"


class LabelIssue(StrEnum):
    ROTATED = "ROTATED"
    BLURRY = "BLURRY"
    HANDWRITTEN = "HANDWRITTEN"
    MULTIPLE_LABELS = "MULTIPLE_LABELS"


class SourceRef(_Strict):
    upload_id: str = Field(description="The upload_id of the evidence block the text came from.")
    position: int = Field(ge=0, description="1-based message number within that upload (0 if unknown).")


class Address(_Strict):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = Field(default=None, description="ISO 3166-1 alpha-2 code if known.")


class ChatRequest(_Strict):
    type: RequestType
    speaker: Speaker
    status: RequestStatus
    quote: str = Field(min_length=1, max_length=500, description="Exact text copied from the evidence.")
    source_ref: SourceRef
    timestamp_text: str | None = None
    requested_address: Address | None = None


class AddressMention(_Strict):
    text: str = Field(min_length=1, max_length=500)
    source_ref: SourceRef


class ConversationExtraction(_Versioned):
    messages_observed: int = Field(ge=0)
    conversation_complete: bool
    requests: list[ChatRequest]
    addresses_mentioned: list[AddressMention]
    issues: list[ChatIssue]
    confidence: float = Field(ge=0.0, le=1.0)


class FieldConfidence(_Strict):
    line1: float | None = Field(default=None, ge=0, le=1)
    line2: float | None = Field(default=None, ge=0, le=1)
    city: float | None = Field(default=None, ge=0, le=1)
    state: float | None = Field(default=None, ge=0, le=1)
    postal_code: float | None = Field(default=None, ge=0, le=1)
    country: float | None = Field(default=None, ge=0, le=1)


class LabelExtraction(_Versioned):
    labels_detected: int = Field(ge=0)
    recipient_name: str | None
    address: Address
    tracking_number_visible: str | None
    carrier_visible: str | None
    readable: bool
    issues: list[LabelIssue]
    field_confidence: FieldConfidence
    confidence: float = Field(ge=0.0, le=1.0)
