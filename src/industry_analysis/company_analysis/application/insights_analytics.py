"""Load flat / wrapped insight JSON into pandas and aggregate by industry."""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
import pandas as pd
from pydantic import ValidationError

from industry_analysis.company_analysis.application.paths import sanitize_category_dir_segment
from industry_analysis.company_analysis.domain.models import CompanyEnrichment


# Heuristic keyword hits for scoring free-text LLM fields (English-oriented).
_CURRENT_AI_TERMS: frozenset[str] = frozenset(
    (
        r"\bai\b",
        r"\bml\b",
        r"\bllm\b",
        r"\bnlp\b",
        r"\bgpt\b",
        r"\bopenai\b",
        r"\bgenai\b",
        r"\bgen(erative)?\s+ai\b",
        r"\bmachine learning\b",
        r"\bdeep learning\b",
        r"\bneural\b",
        r"\bautomat(e|ion|ed)\b",
        r"\bchatbot\b",
        r"\bmodel(s)?\b",
        r"\bforecast(ing)?\b",
        r"\bcomputer vision\b",
        r"\brecommendation engine\b",
        r"\brag\b",
        r"\bembedding(s)?\b",
    )
)

_UPGRADE_TERMS: frozenset[str] = frozenset(
    (
        r"\bai\b",
        r"\bautomate\b",
        r"\bautomation\b",
        r"\bllm\b",
        r"\bml\b",
        r"\boptimize\b",
        r"\bstreamline\b",
        r"\bassist(ant)?\b",
        r"\bcopilot\b",
        r"\bpredict(ive)?\b",
        r"\bclassif(y|ication)\b",
        r"\bsummari[sz]e\b",
        r"\bworkflow\b",
        r"\bintegration\b",
        r"\bscale\b",
    )
)

_AVOID_TERMS: frozenset[str] = frozenset(
    (
        r"\bai\b",
        r"\bautomated?\b",
        r"\bmodel\b",
        r"\balgorithm(s)?\b",
        r"\bdecision\b",
        r"\bhuman\b",
        r"\bprivacy\b",
        r"\bbias\b",
        r"\bcompliance\b",
        r"\bethical\b",
        r"\boverride\b",
    )
)


def _count_regex_hits(text: str, patterns: frozenset[str]) -> int:
    if not text or not text.strip():
        return 0
    lowered = text.lower()
    n = 0
    for p in patterns:
        n += len(re.findall(p, lowered, flags=re.IGNORECASE))
    return n


def score_current_ai_mentions(text: str) -> float:
    """Rough signal for how much the text describes existing AI / ML use."""
    hits = _count_regex_hits(text, _CURRENT_AI_TERMS)
    return float(hits) + math.log1p(len(text)) * 0.02


def score_upgrade_mentions(text: str) -> float:
    """Rough signal for described opportunity to adopt or extend AI."""
    hits = _count_regex_hits(text, _UPGRADE_TERMS)
    return float(hits) + math.log1p(len(text)) * 0.02


def score_avoid_mentions(text: str) -> float:
    """Rough signal for caution / anti-AI themes (used as a soft penalty)."""
    hits = _count_regex_hits(text, _AVOID_TERMS)
    return float(hits) + math.log1p(len(text)) * 0.015


def _unwrap_insight(obj: dict[str, Any]) -> dict[str, Any] | None:
    inner = obj.get("enrichment")
    if isinstance(inner, dict):
        return inner
    return obj


def iter_insight_json_paths(data_dir: Path, *, category_tag: str | None) -> Iterator[Path]:
    """Yield insight JSON paths: ``<tag>/insights/*.json`` or all categories under ``data_dir``."""
    root = data_dir.resolve()
    if not root.is_dir():
        return
    if category_tag is not None:
        seg = sanitize_category_dir_segment(category_tag)
        insight_dir = root / seg / "insights"
        if insight_dir.is_dir():
            yield from sorted(insight_dir.glob("*.json"))
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        insight_dir = child / "insights"
        if insight_dir.is_dir():
            yield from sorted(insight_dir.glob("*.json"))


def iter_enriched_json_paths(data_dir: Path) -> Iterator[Path]:
    """Legacy wrapped insights under ``enriched/<provider>/<country>/*.json``."""
    enriched_root = data_dir.resolve() / "enriched"
    if not enriched_root.is_dir():
        return
    yield from sorted(enriched_root.rglob("*.json"))


def load_insights_dataframe(paths: list[Path]) -> pd.DataFrame:
    """
    Build a long-form table: one row per (company, industry label).

    ``company_key`` is taken from the filename stem when missing from JSON.
    """
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            raw = orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        payload = _unwrap_insight(raw)
        if payload is None:
            continue
        try:
            enr = CompanyEnrichment.model_validate(payload)
        except ValidationError:
            continue
        company_key = path.stem
        industries = [str(x).strip() for x in enr.Industry if str(x).strip()]
        if not industries:
            industries = ["(unspecified)"]
        cat_dir = path.parent.parent.name if path.parent.name == "insights" else ""
        base = {
            "company_key": company_key,
            "category_dir": cat_dir,
            "source_path": str(path),
            "Name": enr.Name,
            "current_use_of_AI": enr.current_use_of_AI,
            "possible_use_of_AI": enr.possible_use_of_AI,
            "avoid_AI_use": enr.avoid_AI_use,
            "current_score": score_current_ai_mentions(enr.current_use_of_AI),
            "possible_score": score_upgrade_mentions(enr.possible_use_of_AI),
            "avoid_score": score_avoid_mentions(enr.avoid_AI_use),
        }
        for ind in industries:
            row = dict(base)
            row["industry"] = ind
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame.from_records(rows)


def aggregate_by_industry(df: pd.DataFrame) -> pd.DataFrame:
    """One row per industry: company counts and mean heuristic scores."""
    if df.empty:
        return df
    g = df.groupby("industry", as_index=False).agg(
        companies=("company_key", "nunique"),
        mean_current_ai=("current_score", "mean"),
        mean_ai_upgrade=("possible_score", "mean"),
        mean_avoid_signal=("avoid_score", "mean"),
    )
    g["adoption_index"] = g["mean_current_ai"] - 0.2 * g["mean_avoid_signal"]
    g["upgrade_pressure"] = g["mean_ai_upgrade"] - 0.15 * g["mean_current_ai"]
    return g.sort_values("mean_current_ai", ascending=False).reset_index(drop=True)


def collect_insight_paths(data_dir: Path, *, category_tag: str | None) -> list[Path]:
    """All insight JSON paths (deduped), optionally scoped to one category tag."""
    paths = list(iter_insight_json_paths(data_dir, category_tag=category_tag))
    if category_tag is None:
        paths.extend(iter_enriched_json_paths(data_dir))
    uniq: dict[str, Path] = {}
    for p in paths:
        uniq[str(p.resolve())] = p
    return list(uniq.values())


def list_categories_with_insights(data_dir: Path) -> list[dict[str, Any]]:
    """Category folder names under ``data_dir`` that contain at least one ``insights/*.json``."""
    root = data_dir.resolve()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        insight_dir = child / "insights"
        if not insight_dir.is_dir():
            continue
        files = list(insight_dir.glob("*.json"))
        if files:
            out.append({"tag": child.name, "insight_count": len(files)})
    return out


def _dataframe_records_json_safe(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in df.to_dict(orient="records"):
        row: dict[str, Any] = {}
        for k, v in raw.items():
            if hasattr(v, "item"):
                try:
                    v = v.item()
                except (ValueError, AttributeError):
                    pass
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None
            else:
                row[k] = v
        rows.append(row)
    return rows


def industry_aggregate_as_records(
    data_dir: Path,
    *,
    category_tag: str | None,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Industry aggregates as JSON-serializable dicts (same logic as ``job-intel analyze``)."""
    paths = collect_insight_paths(data_dir, category_tag=category_tag)
    df = load_insights_dataframe(paths)
    if df.empty:
        return []
    agg = aggregate_by_industry(df)
    if top_n is not None and top_n > 0:
        agg = agg.head(top_n)
    return _dataframe_records_json_safe(agg)


def load_company_insight_summaries(paths: list[Path], *, limit: int) -> list[dict[str, Any]]:
    """Lightweight rows for UI tables (truncated text fields)."""
    out: list[dict[str, Any]] = []
    for path in paths[:limit]:
        try:
            raw = orjson.loads(path.read_bytes())
        except (OSError, orjson.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        payload = _unwrap_insight(raw)
        if payload is None:
            continue
        try:
            enr = CompanyEnrichment.model_validate(payload)
        except ValidationError:
            continue
        cur = enr.current_use_of_AI.strip()
        pos = enr.possible_use_of_AI.strip()
        out.append(
            {
                "company_key": path.stem,
                "category_dir": path.parent.parent.name if path.parent.name == "insights" else "",
                "Name": enr.Name,
                "Industry": enr.Industry,
                "current_use_preview": cur[:280] + ("…" if len(cur) > 280 else ""),
                "possible_use_preview": pos[:280] + ("…" if len(pos) > 280 else ""),
            },
        )
    return out
