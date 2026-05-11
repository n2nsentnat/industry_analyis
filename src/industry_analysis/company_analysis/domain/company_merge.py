from __future__ import annotations

import re
from typing import Any

from industry_analysis.company_analysis.domain.models import CompanyAggregate


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def company_key_from_display_name(display_name: str) -> str:
    slug = _SLUG_RE.sub("-", display_name.lower().strip())
    slug = slug.strip("-")
    return slug or "unknown"


def _uniq_preserve(items: list[str], add: list[str], *, cap: int) -> None:
    seen = set(items)
    for x in add:
        x = x.strip()
        if not x or x in seen:
            continue
        items.append(x)
        seen.add(x)
        if len(items) >= cap:
            break


def merge_job_into_companies(
    companies: dict[str, CompanyAggregate],
    job: dict[str, Any],
    *,
    category_tag: str,
    category_label: str,
) -> None:
    company = job.get("company") if isinstance(job.get("company"), dict) else {}
    display_name = str((company or {}).get("display_name") or "").strip()
    if not display_name:
        return

    job_id = str(job.get("id") or "").strip()
    title = str(job.get("title") or "").strip()
    description = job.get("description")
    desc = str(description).strip() if description is not None else ""

    key = company_key_from_display_name(display_name)
    existing = companies.get(key)
    if existing is not None and job_id and job_id in existing.job_ids:
        return
    if existing is None:
        companies[key] = CompanyAggregate(
            company_key=key,
            display_name=display_name,
            job_ids=[job_id] if job_id else [],
            sample_titles=[title] if title else [],
            category_tags=[category_tag] if category_tag else [],
            category_labels=[category_label] if category_label else [],
            sample_description=desc[:4000] if desc else None,
        )
        return

    if job_id and job_id not in existing.job_ids:
        existing.job_ids.append(job_id)
    _uniq_preserve(existing.sample_titles, [title], cap=25)
    _uniq_preserve(existing.category_tags, [category_tag], cap=50)
    _uniq_preserve(existing.category_labels, [category_label], cap=50)
    if not existing.sample_description and desc:
        existing.sample_description = desc[:4000]


def jobs_from_page_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    out: list[dict[str, Any]] = []
    for row in results:
        if isinstance(row, dict):
            out.append(row)
    return out
