from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx

from industry_analysis.company_analysis.domain.models import Category


@runtime_checkable
class BlobStore(Protocol):
    """Outbound port: persistence for JSON artifacts."""

    root: Any

    async def write_json(self, relative_path: str, payload: Any) -> None: ...
    async def read_json(self, relative_path: str) -> Any | None: ...
    async def exists(self, relative_path: str) -> bool: ...


@runtime_checkable
class JobSearchProvider(Protocol):
    """Outbound port: job listing provider (Adzuna, etc.)."""

    provider_id: str
    country: str

    async def list_categories(self, client: httpx.AsyncClient) -> list[Category]: ...

    async def fetch_jobs_page(
        self,
        client: httpx.AsyncClient,
        *,
        category_tag: str,
        page: int,
        results_per_page: int,
    ) -> dict[str, Any]: ...


@runtime_checkable
class JsonObjectLlmPort(Protocol):
    """Outbound port: LLM that returns a JSON object (e.g. OpenAI json mode)."""

    async def generate_company_profile_json(self, user_prompt: str) -> dict[str, Any]: ...
