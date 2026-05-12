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


class OpenAiJsonObjectLlm:
    """OpenAI Chat Completions with strict ``json_schema`` structured output (application port)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OpenAiJsonObjectLlm:
        limits = httpx.Limits(max_connections=max(32, self._settings.ENRICH_CONCURRENCY + 8))
        timeout = httpx.Timeout(self._settings.HTTP_TIMEOUT_S)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def generate_company_profile_json(self, user_prompt: str) -> dict[str, Any]:
        client = self._client
        if client is None:
            msg = "Use OpenAiJsonObjectLlm as an async context manager before calling."
            raise RuntimeError(msg)
        if not self._settings.OPENAI_API_KEY:
            msg = "OPENAI_API_KEY is not set (add it to your .env for enrich)."
            raise RuntimeError(msg)

        url = self._settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._settings.OPENAI_MODEL,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "company_enrichment",
                    "strict": True,
                    "schema": OPENAI_COMPANY_ENRICHMENT_JSON_SCHEMA,
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return exactly one JSON object matching the json_schema. "
                        "No markdown, no commentary."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        }
        response = await request_with_retries(
            lambda: client.post(url, headers=headers, content=orjson.dumps(payload)),
            max_retries=self._settings.HTTP_MAX_RETRIES,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            msg = "Unexpected OpenAI response shape"
            raise RuntimeError(msg)
        try:
            return parse_llm_json_object(content)
        except (orjson.JSONDecodeError, ValueError) as e:
            msg = f"OpenAI JSON parse failed: {e}"
            raise RuntimeError(msg) from e
