"""AI provider abstraction (PRD §7, F2 task 2).

`generate_structured()` is the only way agents talk to a model:
- the provider returns raw JSON text constrained by the schema,
- we validate it with Pydantic,
- up to two spaced retries on transport errors, one retry on validation failure (the error is fed back),
- otherwise a structured failure (EXTRACTION_FAILED / PROVIDER_UNAVAILABLE).
No provider can call tools that act on the world; output is data only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("staycovered.ai")

T = TypeVar("T", bound=BaseModel)

# Free-tier models return 503 "high demand" spikes; two spaced retries ride most of them out.
MAX_TRANSPORT_RETRIES = 2
TRANSPORT_BACKOFF_S = (2.0, 6.0)


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class BlobPart:
    data: bytes
    mime: str  # image/png, image/jpeg, image/gif, application/pdf


Part = TextPart | BlobPart


class ProviderTransportError(Exception):
    """Network / quota / 5xx from the AI provider (retryable)."""


class Provider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, parts: list[Part], schema: dict[str, Any], schema_name: str) -> str:
        """Return the model's JSON text constrained to `schema`."""
        ...


@dataclass
class StructuredResult(Generic[T]):
    output: T | None
    status: str  # SUCCEEDED | EXTRACTION_FAILED | PROVIDER_UNAVAILABLE
    provider: str
    model: str
    attempts: int
    latency_ms: int
    raw_response_hash: str | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def hash_parts(parts: list[Part], *extra: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, TextPart):
            h.update(b"T" + p.text.encode("utf-8"))
        else:
            h.update(b"B" + p.mime.encode() + hashlib.sha256(p.data).digest())
    for e in extra:
        h.update(b"X" + e.encode("utf-8"))
    return h.hexdigest()


def generate_structured(
    provider: Provider,
    system: str,
    parts: list[Part],
    schema_model: type[T],
    *,
    sleep=time.sleep,
) -> StructuredResult[T]:
    schema = schema_model.model_json_schema()
    started = time.monotonic()
    attempts = 0
    transport_retries = 0
    validation_retries = 0
    feedback: list[Part] = []
    raw_hash: str | None = None
    last_error = ""

    while True:
        attempts += 1
        try:
            raw = provider.complete_json(system, parts + feedback, schema, schema_model.__name__)
        except ProviderTransportError as exc:
            last_error = f"provider error: {exc}"[:500]
            if transport_retries < MAX_TRANSPORT_RETRIES:
                sleep(TRANSPORT_BACKOFF_S[transport_retries])
                transport_retries += 1
                continue
            return StructuredResult(None, "PROVIDER_UNAVAILABLE", provider.name, provider.model, attempts,
                                    _ms(started), raw_hash, last_error)

        raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        try:
            parsed = schema_model.model_validate(json.loads(raw))
            used = getattr(provider, "last_model", provider.model)
            return StructuredResult(parsed, "SUCCEEDED", provider.name, used, attempts, _ms(started), raw_hash)
        except (ValueError, ValidationError) as exc:
            last_error = f"invalid output: {_short(exc)}"
            log.warning("schema validation failed (%s): %s", schema_model.__name__, last_error)
            if validation_retries < 1:
                validation_retries += 1
                feedback = [
                    TextPart(
                        "Your previous answer did not match the required JSON schema. "
                        f"Validation errors: {_short(exc)}. Return ONLY corrected JSON that matches the schema."
                    )
                ]
                continue
            return StructuredResult(None, "EXTRACTION_FAILED", provider.name, provider.model, attempts,
                                    _ms(started), raw_hash, last_error)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:8])
    return str(exc)[:300]


def get_provider(settings) -> Provider:
    """Select by AI_PROVIDER. Imports are lazy so tests need no SDK keys."""
    name = (settings.AI_PROVIDER or "gemini").strip().lower()
    if name == "gemini":
        from app.ai.gemini import GeminiProvider

        return GeminiProvider(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
    if name in ("anthropic", "claude"):
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.ANTHROPIC_API_KEY, settings.ANTHROPIC_MODEL)
    raise ValueError(f"Unknown AI_PROVIDER {settings.AI_PROVIDER!r} (use 'gemini' or 'anthropic').")


def run_tool_loop(*_args, **_kwargs):  # used by the Dispute Defense Agent in Feature 5
    raise NotImplementedError("run_tool_loop arrives in Feature 5")
