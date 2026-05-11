from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APPLICATION_ID: str = Field(description="Adzuna application id")
    APPLICATION_KEY: str = Field(description="Adzuna application key")

    ADZUNA_COUNTRY: str = Field(default="gb", description="ISO country code used in Adzuna paths")
    ADZUNA_BASE_URL: str = Field(default="https://api.adzuna.com")

    DATA_DIR: Path = Field(default=Path("data/job_intel"))

    FETCH_CATEGORY_CONCURRENCY: int = Field(
        default=4,
        ge=1,
        le=32,
        description="How many categories to paginate in parallel",
    )
    HTTP_MAX_CONCURRENCY: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Global cap on concurrent HTTP calls (all providers)",
    )
    RESULTS_PER_PAGE: int = Field(default=100, ge=1, le=100)

    HTTP_TIMEOUT_S: float = Field(default=60.0)
    HTTP_MAX_RETRIES: int = Field(default=6)

    LLM_PROVIDER: Literal["gemini", "openai"] = Field(
        default="gemini",
        description="Which LLM backend enrich uses",
    )

    GEMINI_API_KEY: str | None = None
    GEMINI_API_BASE: str = Field(default="https://generativelanguage.googleapis.com")
    GEMINI_MODEL: str = Field(default="gemini-2.0-flash")

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    ENRICH_CONCURRENCY: int = Field(default=4, ge=1, le=32)
