from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from industry_analysis.company_analysis.application.categories_catalog import (
    categories_from_stored_payload,
    resolve_category_input,
)
from industry_analysis.company_analysis.application.dto import EnrichRunConfig, FetchRunConfig
from industry_analysis.company_analysis.application.enrich_orchestrator import EnrichOrchestrator
from industry_analysis.company_analysis.application.fetch_orchestrator import FetchOrchestrator
from industry_analysis.company_analysis.application.paths import (
    categories_catalog_relpath,
    checkpoint_relpath,
    companies_relpath,
    preview_company_keys,
    scoped_checkpoint_relpath,
    scoped_companies_relpath,
)
from industry_analysis.company_analysis.application.ports import JsonObjectLlmPort
from industry_analysis.company_analysis.domain.models import CompanyAggregate, FetchCheckpoint
from industry_analysis.company_analysis.infrastructure.config.settings import Settings
from industry_analysis.company_analysis.infrastructure.llm.gemini_json_llm import GeminiJsonObjectLlm
from industry_analysis.company_analysis.infrastructure.llm.ollama_json_llm import OllamaJsonObjectLlm
from industry_analysis.company_analysis.infrastructure.llm.openai_json_llm import OpenAiJsonObjectLlm
from industry_analysis.company_analysis.infrastructure.persistence.local_json_store import LocalJsonBlobStore
from industry_analysis.company_analysis.infrastructure.providers.adzuna_job_search import AdzunaJobSearchProvider


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="job-intel",
        description="Fetch job ads (Adzuna) by category to disk JSON, LLM insights per company, and pandas industry charts.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override Settings.DATA_DIR (default: data/job_intel)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser(
        "fetch",
        help="Fetch one Adzuna category (tag via --category); optional categories.json for label lookup",
    )
    p_fetch.add_argument(
        "--category",
        required=True,
        help="Adzuna category tag (e.g. accounting-finance-jobs), or label if categories.json exists",
    )
    p_fetch.add_argument("--country", default=None, help="Override ADZUNA_COUNTRY (default from settings/.env)")
    p_fetch.add_argument(
        "--pages",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of result pages to fetch for this category (optional)",
    )
    p_fetch.add_argument(
        "--max-pages-per-category",
        type=int,
        default=None,
        metavar="N",
        help="Same as --pages (deprecated name)",
    )
    p_fetch.add_argument(
        "--items-per-page",
        type=int,
        default=None,
        metavar="N",
        help="Adzuna results per page for each request (1–100; default: RESULTS_PER_PAGE from settings)",
    )
    p_fetch.add_argument(
        "--force-insights",
        action="store_true",
        help="Re-generate flat insight JSON under insights/ even if files already exist",
    )

    p_status = sub.add_parser("status", help="Inspect categories.json or a category run folder")
    p_status.add_argument("--country", default=None, help="Override ADZUNA_COUNTRY (legacy global checkpoint)")
    p_status.add_argument(
        "--category",
        default=None,
        help="Category tag or label: show checkpoint + companies under <category_tag>/",
    )

    p_enrich = sub.add_parser("enrich", help="LLM-enrich unique companies from derived/companies_*.json")
    p_enrich.add_argument("--provider-id", default="adzuna")
    p_enrich.add_argument("--country", default=None, help="Country code used during fetch (default: settings)")
    p_enrich.add_argument("--limit", type=int, default=None, help="Only process the first N companies (sorted)")
    p_enrich.add_argument("--force", action="store_true", help="Re-generate even if enriched JSON exists")
    p_enrich.add_argument(
        "--llm",
        choices=("ollama", "gemini", "openai"),
        default=None,
        help="Override LLM_PROVIDER: ollama (local), gemini (GEMINI_API_KEY), openai (OPENAI_API_KEY)",
    )

    p_analyze = sub.add_parser(
        "analyze",
        help="Pandas + charts: industry-wise AI usage / upgrade signals from insight JSON files",
    )
    p_analyze.add_argument(
        "--category",
        default=None,
        help="Only <category_tag>/insights/*.json; default scans every */insights/ under DATA_DIR",
    )
    p_analyze.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="PNG and CSV output directory (default: <DATA_DIR>/analysis_reports)",
    )
    p_analyze.add_argument(
        "--top-n",
        type=int,
        default=15,
        metavar="N",
        help="How many industries to show per chart (default 15)",
    )

    return parser.parse_args(argv)


@asynccontextmanager
async def _enrich_llm_client(
    settings: Settings,
) -> AsyncIterator[JsonObjectLlmPort]:
    if settings.LLM_PROVIDER == "gemini":
        async with GeminiJsonObjectLlm(settings) as llm:
            yield llm
    elif settings.LLM_PROVIDER == "ollama":
        async with OllamaJsonObjectLlm(settings) as llm:
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


def _require_llm_keys_for_fetch(settings: Settings) -> int | None:
    if settings.LLM_PROVIDER == "gemini" and not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set (required for fetch insights).", file=sys.stderr)
        return 2
    if settings.LLM_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        print("OPENAI_API_KEY is not set (required for fetch insights).", file=sys.stderr)
        return 2
    return None


async def _cmd_fetch(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(data_dir=args.data_dir, country=args.country)
    if (code := _require_llm_keys_for_fetch(settings)) is not None:
        return code

    if args.pages is not None and args.max_pages_per_category is not None:
        print("Use only one of --pages or --max-pages-per-category.", file=sys.stderr)
        return 2
    max_pages = args.pages if args.pages is not None else args.max_pages_per_category

    items_per_page = args.items_per_page
    if items_per_page is not None:
        if items_per_page < 1 or items_per_page > 100:
            print("--items-per-page must be between 1 and 100 (Adzuna limit).", file=sys.stderr)
            return 2
        results_per_page = items_per_page
    else:
        results_per_page = settings.RESULTS_PER_PAGE

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
        results_per_page=results_per_page,
        fetch_category_concurrency=settings.FETCH_CATEGORY_CONCURRENCY,
        http_timeout_s=settings.HTTP_TIMEOUT_S,
        http_max_connections=max(32, settings.HTTP_MAX_CONCURRENCY + 8),
    )
    async with _enrich_llm_client(settings) as llm:
        orch = FetchOrchestrator(
            config=fetch_config,
            store=store,
            provider=provider,
            llm=llm,
            enrich_concurrency=settings.ENRICH_CONCURRENCY,
            force_insights=args.force_insights,
        )
        await orch.run(
            user_category_input=args.category,
            max_pages=max_pages,
        )
    return 0


async def _cmd_status(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(data_dir=args.data_dir, country=args.country)
    store = LocalJsonBlobStore(settings.DATA_DIR)
    cat_path = (settings.DATA_DIR / categories_catalog_relpath()).resolve()
    print(f"categories_file: {cat_path}")
    raw_cat = await store.read_json(categories_catalog_relpath())
    if isinstance(raw_cat, dict):
        n = len(categories_from_stored_payload(raw_cat))
        print(f"categories_count: {n}")
    else:
        print("categories_count: 0 (optional: add categories.json with tag/label list for label lookup)")

    if args.category:
        catalog = categories_from_stored_payload(raw_cat) if isinstance(raw_cat, dict) else []
        try:
            resolved = resolve_category_input(catalog, args.category)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        tag = resolved.tag
        ck_rel = scoped_checkpoint_relpath(tag)
        print(f"\nscoped_checkpoint_file: {(settings.DATA_DIR / ck_rel).resolve()}")
        ck_raw = await store.read_json(ck_rel)
        if ck_raw is None:
            print("No checkpoint for this category yet.")
        else:
            cp = FetchCheckpoint.model_validate(ck_raw)
            print(json.dumps(cp.model_dump(mode="json"), indent=2, sort_keys=True))

        co_rel = scoped_companies_relpath(tag)
        companies_raw = await store.read_json(co_rel)
        print(f"\ncompanies_index_file: {(settings.DATA_DIR / co_rel).resolve()}")
        if isinstance(companies_raw, dict):
            companies: dict[str, CompanyAggregate] = {
                str(k): CompanyAggregate.model_validate(v) for k, v in companies_raw.items() if isinstance(v, dict)
            }
            print(f"unique_companies: {len(companies)}")
            preview = preview_company_keys(companies, limit=15)
            if preview:
                print("\nSample companies:")
                print(json.dumps(preview, indent=2))
        return 0

    print("\n(Legacy) global checkpoint path (unused by new fetch):")
    rel = checkpoint_relpath("adzuna", settings.ADZUNA_COUNTRY)
    print(f"legacy_checkpoint_file: {(settings.DATA_DIR / rel).resolve()}")
    raw = await store.read_json(rel)
    if raw is None:
        print("No legacy global checkpoint.")
    else:
        cp = FetchCheckpoint.model_validate(raw)
        print(json.dumps(cp.model_dump(mode="json"), indent=2, sort_keys=True))

    companies_raw = await store.read_json(companies_relpath("adzuna", settings.ADZUNA_COUNTRY))
    if isinstance(companies_raw, dict):
        companies = {
            str(k): CompanyAggregate.model_validate(v) for k, v in companies_raw.items() if isinstance(v, dict)
        }
        print(f"\nlegacy_unique_companies: {len(companies)}")
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

    if settings.LLM_PROVIDER == "gemini":
        model_label = settings.GEMINI_MODEL
    elif settings.LLM_PROVIDER == "openai":
        model_label = settings.OPENAI_MODEL
    else:
        model_label = settings.OLLAMA_MODEL

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


def _cmd_analyze(args: argparse.Namespace) -> int:
    from industry_analysis.company_analysis.application.insights_analytics import (
        aggregate_by_industry,
        collect_insight_paths,
        load_insights_dataframe,
    )
    from industry_analysis.company_analysis.presentation.insight_charts import write_industry_report_charts

    settings = _settings_with_overrides(data_dir=args.data_dir, country=None)
    data_dir = settings.DATA_DIR
    if not data_dir.is_dir():
        print(f"DATA_DIR is not a directory: {data_dir.resolve()}", file=sys.stderr)
        return 2
    paths = collect_insight_paths(data_dir, category_tag=args.category)
    if not paths:
        print(f"No insight JSON files under {data_dir.resolve()}", file=sys.stderr)
        return 2
    df = load_insights_dataframe(paths)
    if df.empty:
        print("No valid company insight records (expected CompanyEnrichment shape).", file=sys.stderr)
        return 2
    top_n = max(5, min(args.top_n, 50))
    out_dir = args.output_dir if args.output_dir is not None else (data_dir / "analysis_reports")
    agg = aggregate_by_industry(df)
    written = write_industry_report_charts(agg, out_dir, top_n=top_n)
    print(f"Wrote {len(written)} files under {out_dir.resolve()}")
    for w in written:
        print(f"  {w}")
    print("\nTop industries by inferred current-AI language (heuristic, not ground truth):")
    preview = agg.head(5)[["industry", "companies", "mean_current_ai", "mean_ai_upgrade"]]
    print(preview.to_string(index=False))
    return 0


async def _async_main(argv: list[str] | None) -> int:
    args = _parse_args(argv)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "fetch":
        return await _cmd_fetch(args)
    if args.command == "status":
        return await _cmd_status(args)
    if args.command == "enrich":
        return await _cmd_enrich(args)
    raise AssertionError(args.command)


def main() -> None:
    raise SystemExit(asyncio.run(_async_main(None)))
