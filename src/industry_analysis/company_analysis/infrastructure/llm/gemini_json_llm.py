from __future__ import annotations

from typing import Any

import httpx
import orjson

from industry_analysis.company_analysis.infrastructure.config.settings import Settings
from industry_analysis.company_analysis.infrastructure.http.retry import request_with_retries


class GeminiJsonObjectLlm:
    """Google Gemini `generateContent` with JSON output (`responseMimeType: application/json`)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

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

        base = self._settings.GEMINI_API_BASE.rstrip("/")
        model = self._settings.GEMINI_MODEL.strip()
        url = f"{base}/v1beta/models/{model}:generateContent"
        params = {"key": self._settings.GEMINI_API_KEY}

        system_text = (
            "You output compact JSON only. Follow the user's key names exactly for the JSON object."
        )
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        response = await request_with_retries(
            lambda: client.post(url, params=params, content=orjson.dumps(body)),
            max_retries=self._settings.HTTP_MAX_RETRIES,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            msg = "Gemini returned no candidates"
            raise RuntimeError(msg)
        first = candidates[0]
        if isinstance(first, dict) and first.get("finishReason") in {"SAFETY", "RECITATION"}:
            msg = f"Gemini blocked response: finishReason={first.get('finishReason')}"
            raise RuntimeError(msg)
        content = first.get("content") if isinstance(first, dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts:
            msg = "Gemini response missing content.parts"
            raise RuntimeError(msg)
        part0 = parts[0]
        text = part0.get("text") if isinstance(part0, dict) else None
        if not isinstance(text, str):
            msg = "Gemini response text was not a string"
            raise RuntimeError(msg)
        parsed = orjson.loads(text)
        if not isinstance(parsed, dict):
            msg = "Gemini JSON was not an object"
            raise RuntimeError(msg)
        return parsed
