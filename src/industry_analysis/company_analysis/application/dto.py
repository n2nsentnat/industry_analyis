from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FetchRunConfig:
    results_per_page: int
    fetch_category_concurrency: int
    http_timeout_s: float
    http_max_connections: int


@dataclass(frozen=True, slots=True)
class EnrichRunConfig:
    enrich_concurrency: int
    model_label: str
