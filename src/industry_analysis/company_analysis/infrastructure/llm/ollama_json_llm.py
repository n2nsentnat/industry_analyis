from __future__ import annotations

from typing import Any

import httpx
import orjson

from industry_analysis.company_analysis.infrastructure.config.settings import Settings
from industry_analysis.company_analysis.infrastructure.http.retry import request_with_retries
from industry_analysis.company_analysis.infrastructure.llm.company_enrichment_llm_schema import (
    OPENAI_COMPANY_ENRICHMENT_JSON_SCHEMA,
)
from industry_analysis.company_analysis.infrastructure.llm.llm_json_parse import parse_llm_json_object


class OllamaJsonObjectLlm:
    """Local Ollama ``POST /api/chat`` with JSON-schema ``format`` (structured outputs)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OllamaJsonObjectLlm:
        limits = httpx.Limits(max_connections=max(32, self._settings.ENRICH_CONCURRENCY + 8))
        read_s = self._settings.OLLAMA_TIMEOUT_S
        connect_s = min(30.0, read_s)
        timeout = httpx.Timeout(connect=connect_s, read=read_s, write=connect_s, pool=connect_s)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def generate_company_profile_json(self, user_prompt: str) -> dict[str, Any]:
        client = self._client
        if client is None:
            msg = "Use OllamaJsonObjectLlm as an async context manager before calling."
            raise RuntimeError(msg)

        base = self._settings.OLLAMA_BASE_URL.rstrip("/")
        url = f"{base}/api/chat"
        body: dict[str, Any] = {
            "model": self._settings.OLLAMA_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return exactly one JSON object matching the schema in format. "
                        "No markdown, no code fences, no commentary."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0},
            "format": OPENAI_COMPANY_ENRICHMENT_JSON_SCHEMA,
        }
        response = await request_with_retries(
            lambda: client.post(url, content=orjson.dumps(body)),
            max_retries=self._settings.HTTP_MAX_RETRIES,
        )
        response.raise_for_status()
        data = response.json()
        err = data.get("error")
        if err:
            msg = f"Ollama error: {err!r}"
            raise RuntimeError(msg)
        message = data.get("message")
        if not isinstance(message, dict):
            msg = "Ollama response missing message"
            raise RuntimeError(msg)
        content = message.get("content")
        if isinstance(content, dict):
            return content
        if not isinstance(content, str) or not content.strip():
            msg = "Ollama response missing assistant content"
            raise RuntimeError(msg)
        try:
            return parse_llm_json_object(content)
        except (orjson.JSONDecodeError, ValueError) as e:
            msg = f"Ollama JSON parse failed: {e}"
            raise RuntimeError(msg) from e
