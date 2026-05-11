from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from industry_analysis.company_analysis.application.dto import FetchRunConfig
from industry_analysis.company_analysis.application.paths import (
    checkpoint_relpath,
    companies_relpath,
    raw_page_relpath,
)
from industry_analysis.company_analysis.application.ports import BlobStore, JobSearchProvider
from industry_analysis.company_analysis.domain.company_merge import jobs_from_page_payload, merge_job_into_companies
from industry_analysis.company_analysis.domain.models import Category, CategoryProgress, CompanyAggregate, FetchCheckpoint


class FetchOrchestrator:
    def __init__(
        self,
        *,
        config: FetchRunConfig,
        store: BlobStore,
        provider: JobSearchProvider,
    ) -> None:
        self._config = config
        self._store = store
        self._provider = provider
        self._checkpoint_lock = asyncio.Lock()
        self._companies_lock = asyncio.Lock()

    async def _load_checkpoint(self) -> FetchCheckpoint:
        rel = checkpoint_relpath(self._provider.provider_id, self._provider.country)
        raw = await self._store.read_json(rel)
        if raw is None:
            return FetchCheckpoint(provider_id=self._provider.provider_id, country=self._provider.country)
        return FetchCheckpoint.model_validate(raw)

    async def _save_checkpoint(self, cp: FetchCheckpoint) -> None:
        cp.updated_at = datetime.now(UTC).isoformat()
        rel = checkpoint_relpath(cp.provider_id, cp.country)
        await self._store.write_json(rel, cp.model_dump(mode="json"))

    async def _load_companies(self) -> dict[str, CompanyAggregate]:
        rel = companies_relpath(self._provider.provider_id, self._provider.country)
        raw = await self._store.read_json(rel)
        if raw is None or not isinstance(raw, dict):
            return {}
        out: dict[str, CompanyAggregate] = {}
        for k, v in raw.items():
            if isinstance(v, dict):
                out[str(k)] = CompanyAggregate.model_validate(v)
        return out

    async def _save_companies(self, companies: dict[str, CompanyAggregate]) -> None:
        rel = companies_relpath(self._provider.provider_id, self._provider.country)
        payload = {k: v.model_dump(mode="json") for k, v in companies.items()}
        await self._store.write_json(rel, payload)

    async def run(
        self,
        *,
        only_category: str | None = None,
        max_pages_per_category: int | None = None,
    ) -> None:
        limits = httpx.Limits(max_connections=self._config.http_max_connections)
        timeout = httpx.Timeout(self._config.http_timeout_s)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            categories = await self._provider.list_categories(client)
            if only_category:
                categories = [c for c in categories if c.tag == only_category]
                if not categories:
                    msg = f"Unknown category tag: {only_category}"
                    raise ValueError(msg)

            cp = await self._load_checkpoint()
            companies = await self._load_companies()

            category_sem = asyncio.Semaphore(self._config.fetch_category_concurrency)

            async def run_category(cat: Category) -> None:
                async with category_sem:
                    await self._paginate_category(
                        client=client,
                        category=cat,
                        checkpoint=cp,
                        companies=companies,
                        max_pages=max_pages_per_category,
                    )

            await asyncio.gather(*(run_category(c) for c in categories))

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
            except Exception as exc:  # noqa: BLE001 - surface provider/http errors to checkpoint
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
                    f"checkpoint={checkpoint_relpath(self._provider.provider_id, self._provider.country)}",
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

            rel = raw_page_relpath(self._provider.provider_id, self._provider.country, tag, page)
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
