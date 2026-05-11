from __future__ import annotations

import asyncio
from typing import Any

import httpx

from industry_analysis.company_analysis.domain.models import Category
from industry_analysis.company_analysis.infrastructure.http.retry import request_with_retries


class AdzunaJobSearchProvider:
    """Adzuna public Jobs API (categories + /search/{page})."""

    provider_id = "adzuna"

    def __init__(
        self,
        *,
        app_id: str,
        app_key: str,
        country: str,
        base_url: str = "https://api.adzuna.com",
        http_gate: asyncio.Semaphore,
        max_retries: int,
    ) -> None:
        self._app_id = app_id
        self._app_key = app_key
        self.country = country.lower()
        self._base = base_url.rstrip("/")
        self._http_gate = http_gate
        self._max_retries = max_retries

    def _params(self) -> dict[str, str]:
        return {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "content-type": "application/json",
        }

    async def _get_json(self, client: httpx.AsyncClient, url: str, params: dict[str, str]) -> Any:
        async with self._http_gate:
            response = await request_with_retries(
                lambda: client.get(url, params=params),
                max_retries=self._max_retries,
            )
        response.raise_for_status()
        return response.json()

    async def list_categories(self, client: httpx.AsyncClient) -> list[Category]:
        url = f"{self._base}/v1/api/jobs/{self.country}/categories"
        payload = await self._get_json(client, url, self._params())
        out: list[Category] = []
        for row in payload.get("results", []) or []:
            tag = str(row.get("tag") or "").strip()
            label = str(row.get("label") or "").strip()
            if tag:
                out.append(Category(tag=tag, label=label or tag))
        return out

    async def fetch_jobs_page(
        self,
        client: httpx.AsyncClient,
        *,
        category_tag: str,
        page: int,
        results_per_page: int,
    ) -> dict[str, Any]:
        url = f"{self._base}/v1/api/jobs/{self.country}/search/{page}"
        params = {
            **self._params(),
            "results_per_page": str(int(results_per_page)),
            "category": category_tag,
        }
        return await self._get_json(client, url, params)
