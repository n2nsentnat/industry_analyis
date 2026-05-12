from __future__ import annotations

from typing import Any

from industry_analysis.company_analysis.domain.models import CompanyAggregate


def sanitize_category_dir_segment(tag: str) -> str:
    return tag.replace("/", "-").strip()


def categories_catalog_relpath() -> str:
    return "categories.json"


def scoped_checkpoint_relpath(category_tag: str) -> str:
    return f"{sanitize_category_dir_segment(category_tag)}/checkpoint.json"


def scoped_companies_relpath(category_tag: str) -> str:
    return f"{sanitize_category_dir_segment(category_tag)}/companies_index.json"


def scoped_raw_page_relpath(category_tag: str, page: int) -> str:
    return f"{sanitize_category_dir_segment(category_tag)}/raw/page-{page:05d}.json"


def scoped_flat_insight_relpath(category_tag: str, company_key: str) -> str:
    safe_key = company_key.replace("/", "-")
    return f"{sanitize_category_dir_segment(category_tag)}/insights/{safe_key}.json"


# Legacy paths (standalone ``enrich`` command)
def checkpoint_relpath(provider_id: str, country: str) -> str:
    return f"checkpoints/fetch_{provider_id}_{country}.json"


def companies_relpath(provider_id: str, country: str) -> str:
    return f"derived/companies_{provider_id}_{country}.json"


def raw_page_relpath(provider_id: str, country: str, category_tag: str, page: int) -> str:
    safe_tag = category_tag.replace("/", "-")
    return f"raw_jobs/{provider_id}/{country}/{safe_tag}/page-{page:05d}.json"


def enriched_relpath(provider_id: str, country: str, company_key: str) -> str:
    safe_key = company_key.replace("/", "-")
    return f"enriched/{provider_id}/{country}/{safe_key}.json"


def preview_company_keys(companies: dict[str, CompanyAggregate], *, limit: int = 20) -> list[dict[str, Any]]:
    keys = list(companies.keys())
    keys.sort()
    out: list[dict[str, Any]] = []
    for k in keys[:limit]:
        c = companies[k]
        out.append(
            {
                "company_key": k,
                "display_name": c.display_name,
                "job_count": len(c.job_ids),
            },
        )
    return out
