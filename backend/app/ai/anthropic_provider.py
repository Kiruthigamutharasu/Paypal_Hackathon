"""Anthropic (Claude) via the official SDK. Structured output = one forced tool call
whose input_schema is our Pydantic JSON schema. The tool does nothing; it only shapes output."""
from __future__ import annotations

import base64
import json
from typing import Any

from app.ai.provider import BlobPart, Part, ProviderTransportError, TextPart

DEFAULT_MODEL = "claude-sonnet-5-5"  # used only when ANTHROPIC_MODEL is blank


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout_s: float = 60.0) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set.")
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self.model = model or DEFAULT_MODEL

    def complete_json(self, system: str, parts: list[Part], schema: dict[str, Any], schema_name: str) -> str:
        content: list[dict[str, Any]] = []
        for p in parts:
            if isinstance(p, TextPart):
                content.append({"type": "text", "text": p.text})
            elif isinstance(p, BlobPart):
                b64 = base64.standard_b64encode(p.data).decode()
                block_type = "document" if p.mime == "application/pdf" else "image"
                content.append({"type": block_type, "source": {"type": "base64", "media_type": p.mime, "data": b64}})
        tool = {
            "name": f"record_{schema_name.lower()}",
            "description": "Record the extracted facts. This only stores data; it performs no action.",
            "input_schema": schema,
        }
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": content}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
            )
        except (self._anthropic.APIConnectionError, self._anthropic.RateLimitError, self._anthropic.InternalServerError) as exc:
            raise ProviderTransportError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                return json.dumps(block.input)
        raise ProviderTransportError("model returned no tool_use block")
