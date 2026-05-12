from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from industry_analysis.company_analysis.application.categories_catalog import (
    load_categories_catalog,
    resolve_category_input,
)
from industry_analysis.company_analysis.application.company_prompt import build_company_enrichment_prompt
from industry_analysis.company_analysis.application.dto import FetchRunConfig
from industry_analysis.company_analysis.application.paths import (
    scoped_checkpoint_relpath,
    scoped_companies_relpath,
    scoped_flat_insight_relpath,
    scoped_raw_page_relpath,
)
from industry_analysis.company_analysis.application.ports import BlobStore, JobSearchProvider, JsonObjectLlmPort
from industry_analysis.company_analysis.domain.company_merge import jobs_from_page_payload, merge_job_into_companies
from industry_analysis.company_analysis.domain.models import (
    Category,
    CategoryProgress,
    CompanyAggregate,
    CompanyEnrichment,
    FetchCheckpoint,
)


class FetchOrchestrator:
    """Fetch one category into ``<category_tag>/`` and optionally write flat LLM JSON per company."""

    def __init__(
        self,
        *,
        config: FetchRunConfig,
        store: BlobStore,
        provider: JobSearchProvider,
        llm: JsonObjectLlmPort | None,
        enrich_concurrency: int,
        force_insights: bool = False,
    ) -> None:
        self._config = config
        self._store = store
        self._provider = provider
        self._llm = llm
        self._enrich_concurrency = max(1, enrich_concurrency)
        self._force_insights = force_insights
        self._checkpoint_lock = asyncio.Lock()
        self._companies_lock = asyncio.Lock()
        self._category_tag: str = ""

    def _checkpoint_rel(self) -> str:
        return scoped_checkpoint_relpath(self._category_tag)

    async def _load_checkpoint(self) -> FetchCheckpoint:
        raw = await self._store.read_json(self._checkpoint_rel())
        if raw is None:
            return FetchCheckpoint(provider_id=self._provider.provider_id, country=self._provider.country)
        return FetchCheckpoint.model_validate(raw)

    async def _save_checkpoint(self, cp: FetchCheckpoint) -> None:
        cp.updated_at = datetime.now(UTC).isoformat()
        await self._store.write_json(self._checkpoint_rel(), cp.model_dump(mode="json"))

    async def _load_companies(self) -> dict[str, CompanyAggregate]:
        rel = scoped_companies_relpath(self._category_tag)
        raw = await self._store.read_json(rel)
        if raw is None or not isinstance(raw, dict):
            return {}
        out: dict[str, CompanyAggregate] = {}
        for k, v in raw.items():
            if isinstance(v, dict):
                out[str(k)] = CompanyAggregate.model_validate(v)
        return out

    async def _save_companies(self, companies: dict[str, CompanyAggregate]) -> None:
        rel = scoped_companies_relpath(self._category_tag)
        payload = {k: v.model_dump(mode="json") for k, v in companies.items()}
        await self._store.write_json(rel, payload)

    async def run(
        self,
        *,
        user_category_input: str,
        max_pages: int | None,
    ) -> None:
        limits = httpx.Limits(max_connections=self._config.http_max_connections)
        timeout = httpx.Timeout(self._config.http_timeout_s)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            catalog = await load_categories_catalog(self._store)
            category = resolve_category_input(catalog, user_category_input)
            self._category_tag = category.tag

            cp = await self._load_checkpoint()
            companies = await self._load_companies()

            await self._paginate_category(
                client=client,
                category=category,
                checkpoint=cp,
                companies=companies,
                max_pages=max_pages,
            )

            if self._llm is not None and companies:
                await self._write_flat_insight_files(companies)

    async def _write_flat_insight_files(self, companies: dict[str, CompanyAggregate]) -> None:
        llm = self._llm
        assert llm is not None
        sem = asyncio.Semaphore(self._enrich_concurrency)

        async def one(key: str) -> None:
            aggregate = companies[key]
            rel = scoped_flat_insight_relpath(self._category_tag, aggregate.company_key)
            if not self._force_insights and await self._store.exists(rel):
                return
            async with sem:
                prompt = build_company_enrichment_prompt(aggregate)
                obj = await llm.generate_company_profile_json(prompt)
                enrichment = CompanyEnrichment.model_validate(obj)
                await self._store.write_json(rel, enrichment.model_dump(mode="json"))

        keys = sorted(companies.keys())
        await asyncio.gather(*(one(k) for k in keys))

    async def _paginate_category(
        self,
        *,
        client: httpx.AsyncClient,
        category: Category,
        checkpoint: FetchCheckpoint,
        companies: dict[str, CompanyAggregate],
        max_pages: int | None,
    ) -> None:
        tag = category.tag
        async with self._checkpoint_lock:
            progress = checkpoint.categories.get(tag) or CategoryProgress()
            checkpoint.categories[tag] = progress

        pages_fetched = 0
        while True:
            async with self._checkpoint_lock:
                progress = checkpoint.categories[tag]
                if progress.completed:
                    return
                page = progress.next_page

            if max_pages is not None and pages_fetched >= max_pages:
                async with self._checkpoint_lock:
                    checkpoint.categories[tag] = progress
                    await self._save_checkpoint(checkpoint)
                return

            try:
                payload = await self._provider.fetch_jobs_page(
                    client,
                    category_tag=tag,
                    page=page,
                    results_per_page=self._config.results_per_page,
                )
            except Exception as exc:  # noqa: BLE001
                async with self._checkpoint_lock:
                    progress = checkpoint.categories.get(tag) or CategoryProgress()
                    progress.last_error = f"{type(exc).__name__}: {exc}"
                    progress.failed_page = page
                    checkpoint.categories[tag] = progress
                    await self._save_checkpoint(checkpoint)
                raise RuntimeError(
                    "Fetch failed; checkpoint updated. "
                    f"Resume with the same command. provider={self._provider.provider_id} "
                    f"country={self._provider.country} category={tag} page={page} "
                    f"checkpoint={self._checkpoint_rel()}",
                ) from exc

            jobs = jobs_from_page_payload(payload)
            if not jobs:
                async with self._checkpoint_lock:
                    progress = checkpoint.categories.get(tag) or CategoryProgress()
                    progress.completed = True
                    progress.failed_page = None
                    progress.last_error = None
                    progress.last_fetched_page = page
                    progress.last_success_at = datetime.now(UTC).isoformat()
                    checkpoint.categories[tag] = progress
                async with self._companies_lock:
                    await self._save_companies(companies)
                async with self._checkpoint_lock:
                    await self._save_checkpoint(checkpoint)
                return

            rel = scoped_raw_page_relpath(tag, page)
            await self._store.write_json(rel, payload)

            cat_label = category.label
            async with self._companies_lock:
                for job in jobs:
                    merge_job_into_companies(
                        companies,
                        job,
                        category_tag=tag,
                        category_label=cat_label,
                    )
                await self._save_companies(companies)

            async with self._checkpoint_lock:
                progress = checkpoint.categories.get(tag) or CategoryProgress()
                progress.last_fetched_page = page
                progress.last_success_at = datetime.now(UTC).isoformat()
                progress.last_error = None
                progress.failed_page = None
                progress.next_page = page + 1
                checkpoint.categories[tag] = progress
                await self._save_checkpoint(checkpoint)

            pages_fetched += 1
