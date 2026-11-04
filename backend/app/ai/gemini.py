"""Gemini via the official google-genai SDK with JSON-schema constrained output."""
from __future__ import annotations

from typing import Any

from app.ai.provider import BlobPart, Part, ProviderTransportError, TextPart


# Used once when GEMINI_MODEL is out of free-tier quota (429) or overloaded (503): the first entry
# that differs from GEMINI_MODEL. Each model has its own free-tier daily quota
# (seen Nov 5, 2026: 20 requests/day for gemini-3.5-flash). All are free-tier models.
FALLBACK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_s: float = 60.0) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
        if not model:
            raise ValueError("GEMINI_MODEL is not set.")
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        self.model = model
        self.last_model = model  # the model that actually produced the last answer

    def complete_json(self, system: str, parts: list[Part], schema: dict[str, Any], schema_name: str) -> str:
        types = self._types
        contents = []
        for p in parts:
            if isinstance(p, TextPart):
                contents.append(types.Part.from_text(text=p.text))
            elif isinstance(p, BlobPart):
                contents.append(types.Part.from_bytes(data=p.data, mime_type=p.mime))
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0,
        )
        fallback = next((m for m in FALLBACK_MODELS if m != self.model), None)
        models = [self.model] + ([fallback] if fallback else [])
        resp = None
        for i, model in enumerate(models):
            try:
                resp = self._client.models.generate_content(model=model, contents=contents, config=config)
                self.last_model = model
                break
            except Exception as exc:  # SDK raises various errors: network, 429, 5xx
                if _is_client_error(exc):
                    raise
                if i + 1 < len(models) and _is_capacity_error(exc):
                    continue  # try the fallback model
                raise ProviderTransportError(_describe(exc)) from exc
        assert resp is not None
        text = resp.text
        if not text:
            raise ProviderTransportError("empty response (possibly blocked)")
        return text


def _is_client_error(exc: Exception) -> bool:
    """400-class errors other than 429 are bugs/config problems, not transient."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return isinstance(code, int) and 400 <= code < 500 and code != 429


def _is_capacity_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code in (429, 503)


def _describe(exc: Exception) -> str:
    s = str(exc)
    if "RESOURCE_EXHAUSTED" in s:
        per_day = "PerDay" in s
        return f"Gemini quota exhausted ({'daily' if per_day else 'per-minute'} free-tier limit)"
    if "UNAVAILABLE" in s:
        return "Gemini is overloaded right now (503 high demand)"
    return f"{type(exc).__name__}: {s[:200]}"
