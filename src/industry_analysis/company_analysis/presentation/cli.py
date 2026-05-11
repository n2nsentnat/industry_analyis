from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from industry_analysis.company_analysis.application.dto import EnrichRunConfig, FetchRunConfig
from industry_analysis.company_analysis.application.enrich_orchestrator import EnrichOrchestrator
from industry_analysis.company_analysis.application.fetch_orchestrator import FetchOrchestrator
from industry_analysis.company_analysis.application.paths import (
    checkpoint_relpath,
    companies_relpath,
    preview_company_keys,
)
from industry_analysis.company_analysis.application.ports import JsonObjectLlmPort
from industry_analysis.company_analysis.domain.models import CompanyAggregate, FetchCheckpoint
from industry_analysis.company_analysis.infrastructure.config.settings import Settings
from industry_analysis.company_analysis.infrastructure.llm.gemini_json_llm import GeminiJsonObjectLlm
from industry_analysis.company_analysis.infrastructure.llm.openai_json_llm import OpenAiJsonObjectLlm
from industry_analysis.company_analysis.infrastructure.persistence.local_json_store import LocalJsonBlobStore
from industry_analysis.company_analysis.infrastructure.providers.adzuna_job_search import AdzunaJobSearchProvider


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job-intel",
        description="Fetch job ads (Adzuna) to disk JSON, then enrich unique companies with an LLM.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override Settings.DATA_DIR (default: data/job_intel)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Download categories + job pages; maintain checkpoint + company index")
    p_fetch.add_argument("--country", default=None, help="Override ADZUNA_COUNTRY (default from settings/.env)")
    p_fetch.add_argument("--only-category", default=None, help="Only fetch a single category tag (e.g. it-jobs)")
    p_fetch.add_argument(
        "--max-pages-per-category",
        type=int,
        default=None,
        help="Safety valve: stop after N pages for each category (does not mark categories completed)",
    )

    p_status = sub.add_parser("status", help="Print fetch checkpoint + resume hints")
    p_status.add_argument("--country", default=None, help="Override ADZUNA_COUNTRY (default from settings/.env)")

    p_enrich = sub.add_parser("enrich", help="LLM-enrich unique companies from derived/companies_*.json")
    p_enrich.add_argument("--provider-id", default="adzuna")
    p_enrich.add_argument("--country", default=None, help="Country code used during fetch (default: settings)")
    p_enrich.add_argument("--limit", type=int, default=None, help="Only process the first N companies (sorted)")
    p_enrich.add_argument("--force", action="store_true", help="Re-generate even if enriched JSON exists")
    p_enrich.add_argument(
        "--llm",
        choices=("gemini", "openai"),
        default=None,
        help="Override LLM_PROVIDER from .env (gemini uses GEMINI_API_KEY; openai uses OPENAI_API_KEY)",
    )

    return parser.parse_args(argv)


@asynccontextmanager
async def _enrich_llm_client(
    settings: Settings,
) -> AsyncIterator[JsonObjectLlmPort]:
    if settings.LLM_PROVIDER == "gemini":
        async with GeminiJsonObjectLlm(settings) as llm:
            yield llm
    else:
        async with OpenAiJsonObjectLlm(settings) as llm:
            yield llm


def _settings_with_overrides(*, data_dir: Path | None, country: str | None) -> Settings:
    base = Settings()
    updates: dict[str, Path | str] = {}
    if data_dir is not None:
        updates["DATA_DIR"] = data_dir
    if country is not None:
        updates["ADZUNA_COUNTRY"] = country
    if updates:
        return base.model_copy(update=updates)
    return base


async def _cmd_fetch(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(data_dir=args.data_dir, country=args.country)
    store = LocalJsonBlobStore(settings.DATA_DIR)
    http_gate = asyncio.Semaphore(settings.HTTP_MAX_CONCURRENCY)
    provider = AdzunaJobSearchProvider(
        app_id=settings.APPLICATION_ID,
        app_key=settings.APPLICATION_KEY,
        country=settings.ADZUNA_COUNTRY,
        base_url=settings.ADZUNA_BASE_URL,
        http_gate=http_gate,
        max_retries=settings.HTTP_MAX_RETRIES,
    )
    fetch_config = FetchRunConfig(
        results_per_page=settings.RESULTS_PER_PAGE,
        fetch_category_concurrency=settings.FETCH_CATEGORY_CONCURRENCY,
        http_timeout_s=settings.HTTP_TIMEOUT_S,
        http_max_connections=max(32, settings.HTTP_MAX_CONCURRENCY + 8),
    )
    orch = FetchOrchestrator(config=fetch_config, store=store, provider=provider)
    await orch.run(
        only_category=args.only_category,
        max_pages_per_category=args.max_pages_per_category,
    )
    return 0


async def _cmd_status(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(data_dir=args.data_dir, country=args.country)
    store = LocalJsonBlobStore(settings.DATA_DIR)
    rel = checkpoint_relpath("adzuna", settings.ADZUNA_COUNTRY)
    raw = await store.read_json(rel)
    print(f"checkpoint_file: {(settings.DATA_DIR / rel).resolve()}")
    if raw is None:
        print("No checkpoint yet (fetch not run).")
        return 0
    cp = FetchCheckpoint.model_validate(raw)
    print(json.dumps(cp.model_dump(mode="json"), indent=2, sort_keys=True))

    companies_raw = await store.read_json(companies_relpath("adzuna", settings.ADZUNA_COUNTRY))
    if isinstance(companies_raw, dict):
        companies: dict[str, CompanyAggregate] = {
            str(k): CompanyAggregate.model_validate(v) for k, v in companies_raw.items() if isinstance(v, dict)
        }
        print(f"\nunique_companies: {len(companies)}")
        preview = preview_company_keys(companies, limit=15)
        if preview:
            print("\nSample companies:")
            print(json.dumps(preview, indent=2))
    return 0


async def _cmd_enrich(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(data_dir=args.data_dir, country=args.country)
    if args.llm is not None:
        settings = settings.model_copy(update={"LLM_PROVIDER": args.llm})

    if settings.LLM_PROVIDER == "gemini" and not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set (required when LLM_PROVIDER=gemini).", file=sys.stderr)
        return 2
    if settings.LLM_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        print("OPENAI_API_KEY is not set (required when LLM_PROVIDER=openai).", file=sys.stderr)
        return 2

    model_label = settings.GEMINI_MODEL if settings.LLM_PROVIDER == "gemini" else settings.OPENAI_MODEL

    store = LocalJsonBlobStore(settings.DATA_DIR)
    country = settings.ADZUNA_COUNTRY
    rel = companies_relpath(args.provider_id, country)
    raw = await store.read_json(rel)
    if raw is None or not isinstance(raw, dict):
        print(f"Missing companies index: {(settings.DATA_DIR / rel).resolve()}", file=sys.stderr)
        return 2
    companies = {str(k): CompanyAggregate.model_validate(v) for k, v in raw.items() if isinstance(v, dict)}
    enrich_config = EnrichRunConfig(
        enrich_concurrency=settings.ENRICH_CONCURRENCY,
        model_label=model_label,
    )
    async with _enrich_llm_client(settings) as llm:
        orch = EnrichOrchestrator(config=enrich_config, store=store, llm=llm)
        await orch.run(
            provider_id=args.provider_id,
            country=country,
            companies=companies,
            limit=args.limit,
            force=args.force,
        )
    return 0


async def _async_main(argv: list[str] | None) -> int:
    args = _parse_args(argv)
    if args.command == "fetch":
        return await _cmd_fetch(args)
    if args.command == "status":
        return await _cmd_status(args)
    if args.command == "enrich":
        return await _cmd_enrich(args)
    raise AssertionError(args.command)


def main() -> None:
    raise SystemExit(asyncio.run(_async_main(None)))
