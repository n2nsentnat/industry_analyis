from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import orjson

from industry_analysis.company_analysis.infrastructure.config.settings import Settings
from industry_analysis.company_analysis.infrastructure.http.retry import request_with_retries
from industry_analysis.company_analysis.infrastructure.llm.company_enrichment_llm_schema import (
    GEMINI_COMPANY_ENRICHMENT_RESPONSE_SCHEMA,
)
from industry_analysis.company_analysis.infrastructure.llm.llm_json_parse import parse_llm_json_object


def _normalize_gemini_model_id(model: str) -> str:
    """
    Return the model id for ``.../v1beta/models/{id}:generateContent``.

    Accepts ``gemini-2.0-flash`` or common misconfigurations like ``gemini/gemini-2.0-flash``
    or ``models/gemini-2.0-flash``.
    """
    m = model.strip()
    while m.lower().startswith("gemini/"):
        m = m[7:].lstrip("/")
    if m.lower().startswith("models/"):
        m = m[9:].lstrip("/")
    return m.strip() or "gemini-2.0-flash"


class GeminiJsonObjectLlm:
    """Google Gemini `generateContent` with JSON output (`responseMimeType: application/json`)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._gemini_gate = asyncio.Lock()
        self._last_gemini_end_monotonic: float = 0.0

    async def __aenter__(self) -> GeminiJsonObjectLlm:
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
            msg = "Use GeminiJsonObjectLlm as an async context manager before calling."
            raise RuntimeError(msg)
        if not self._settings.GEMINI_API_KEY:
            msg = "GEMINI_API_KEY is not set (add it to your .env for enrich with Gemini)."
            raise RuntimeError(msg)

        async with self._gemini_gate:
            interval = self._settings.GEMINI_MIN_REQUEST_INTERVAL_S
            if interval > 0 and self._last_gemini_end_monotonic > 0.0:
                gap = time.monotonic() - self._last_gemini_end_monotonic
                if gap < interval:
                    await asyncio.sleep(interval - gap)

            base = self._settings.GEMINI_API_BASE.rstrip("/")
            model = _normalize_gemini_model_id(self._settings.GEMINI_MODEL)
            url = f"{base}/v1beta/models/{model}:generateContent"
            params = {"key": self._settings.GEMINI_API_KEY}

            system_text = (
                "Return exactly one JSON object matching the response schema. "
                "No markdown, no code fences, no keys other than those in the schema."
            )
            body: dict[str, Any] = {
                "systemInstruction": {"parts": [{"text": system_text}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseSchema": GEMINI_COMPANY_ENRICHMENT_RESPONSE_SCHEMA,
                },
            }

            try:
                response = await request_with_retries(
                    lambda: client.post(url, params=params, content=orjson.dumps(body)),
                    max_retries=self._settings.GEMINI_MAX_RETRIES,
                )
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates")
                if not isinstance(candidates, list) or not candidates:
                    msg = "Gemini returned no candidates"
                    raise RuntimeError(msg)
                first = candidates[0]
                fr = first.get("finishReason") if isinstance(first, dict) else None
                if fr in {"SAFETY", "RECITATION"}:
                    msg = f"Gemini blocked response: finishReason={fr}"
                    raise RuntimeError(msg)
                content = first.get("content") if isinstance(first, dict) else None
                parts = content.get("parts") if isinstance(content, dict) else None
                if not isinstance(parts, list) or not parts:
                    msg = "Gemini response missing content.parts"
                    raise RuntimeError(msg)
                part0 = parts[0]
                text = part0.get("text") if isinstance(part0, dict) else None
                if not isinstance(text, str) or not text.strip():
                    hint = f" finishReason={fr!r}" if fr else ""
                    msg = f"Gemini returned empty or non-text content.{hint}"
                    raise RuntimeError(msg)
                try:
                    return parse_llm_json_object(text)
                except (orjson.JSONDecodeError, ValueError) as e:
                    msg = f"Gemini JSON parse failed: {e}"
                    raise RuntimeError(msg) from e
            finally:
                self._last_gemini_end_monotonic = time.monotonic()
