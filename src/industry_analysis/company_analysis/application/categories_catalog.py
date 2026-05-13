from __future__ import annotations

from industry_analysis.company_analysis.application.paths import categories_catalog_relpath
from industry_analysis.company_analysis.application.ports import BlobStore
from industry_analysis.company_analysis.domain.models import Category


async def load_categories_catalog(store: BlobStore) -> list[Category]:
    """Load ``categories.json`` from disk only (no Adzuna categories API)."""
    raw = await store.read_json(categories_catalog_relpath())
    return categories_from_stored_payload(raw)


def categories_from_stored_payload(raw: object) -> list[Category]:
    """Parse categories list from persisted ``categories.json`` body (no network)."""
    if not isinstance(raw, dict):
        return []
    categories_raw = raw.get("categories")
    if not isinstance(categories_raw, list):
        return []
    out: list[Category] = []
    for row in categories_raw:
        if isinstance(row, dict) and row.get("tag"):
            out.append(Category.model_validate(row))
    return out


def resolve_category_input(catalog: list[Category], user_input: str) -> Category:
    """Match by exact ``tag`` then label from ``catalog``; if catalog is empty, ``user_input`` is the Adzuna tag."""
    needle = user_input.strip()
    if not needle:
        msg = "Category must be a non-empty tag (or label when categories.json lists it)."
        raise ValueError(msg)
    if not catalog:
        return Category(tag=needle, label=needle)
    for c in catalog:
        if c.tag == needle:
            return c
    needle_lower = needle.lower()
    for c in catalog:
        if c.label.strip().lower() == needle_lower:
            return c
    tags_sample = ", ".join(sorted(c.tag for c in catalog)[:12])
    msg = f"Unknown category {user_input!r}. Use a tag from categories.json or an exact label (e.g. {tags_sample})."
    raise ValueError(msg)
