"""Read-only HTTP API for the job-intel React dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from industry_analysis.company_analysis.application.insights_analytics import (
    collect_insight_paths,
    industry_aggregate_as_records,
    list_categories_with_insights,
    load_company_insight_summaries,
)
from industry_analysis.presentation.job_intel_view_settings import JobIntelViewSettings

router = APIRouter(prefix="/api/job-intel", tags=["job-intel"])


def _data_dir() -> Path:
    return JobIntelViewSettings().DATA_DIR.resolve()


@router.get("/categories")
async def categories() -> list[dict[str, str | int]]:
    root = _data_dir()
    if not root.is_dir():
        return []
    return list_categories_with_insights(root)


@router.get("/aggregates")
async def aggregates(
    category: str | None = Query(default=None, description="Category tag folder, or omit for all + enriched"),
    top_n: int = Query(default=35, ge=5, le=150),
) -> dict[str, object]:
    root = _data_dir()
    if not root.is_dir():
        raise HTTPException(
            status_code=404,
            detail="DATA_DIR does not exist or is not a directory. Set DATA_DIR in .env to your job-intel root.",
        )
    rows = industry_aggregate_as_records(root, category_tag=category, top_n=top_n)
    return {"data": rows, "category": category}


@router.get("/companies")
async def companies(
    category: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=300),
) -> dict[str, object]:
    root = _data_dir()
    if not root.is_dir():
        raise HTTPException(
            status_code=404,
            detail="DATA_DIR does not exist or is not a directory. Set DATA_DIR in .env to your job-intel root.",
        )
    paths = collect_insight_paths(root, category_tag=category)
    rows = load_company_insight_summaries(paths, limit=limit)
    return {"data": rows, "category": category}
