from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Category(BaseModel):
    tag: str
    label: str


class CategoryProgress(BaseModel):
    """Per-category pagination cursor for resume after crash."""

    next_page: int = Field(default=1, ge=1, description="Next Adzuna page number to fetch")
    completed: bool = False
    last_fetched_page: int | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    failed_page: int | None = None


class FetchCheckpoint(BaseModel):
    provider_id: str
    country: str
    categories: dict[str, CategoryProgress] = Field(default_factory=dict)
    updated_at: str | None = None


class CompanyAggregate(BaseModel):
    """De-duplicated company view built from job ads."""

    company_key: str
    display_name: str
    job_ids: list[str] = Field(default_factory=list)
    sample_titles: list[str] = Field(default_factory=list)
    category_tags: list[str] = Field(default_factory=list)
    category_labels: list[str] = Field(default_factory=list)
    sample_description: str | None = None


class CompanyEnrichment(BaseModel):
    """LLM output shape requested by the product."""

    Name: str
    Industry: list[str]
    current_use_of_AI: str
    possible_use_of_AI: str
    avoid_AI_use: str


class CompanyEnrichmentRecord(BaseModel):
    enrichment: CompanyEnrichment
    source: dict[str, Any] = Field(default_factory=dict)
