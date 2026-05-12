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
    ADZUNA_BASE_URL: str = Field(
        default="https://api.adzuna.com",
        description="Host only (e.g. https://api.adzuna.com). Paths /v1/api/jobs/... are appended by the client.",
    )

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

    LLM_PROVIDER: Literal["ollama", "gemini", "openai"] = Field(
        default="ollama",
        description="Which LLM backend fetch insights and enrich use (local Ollama by default)",
    )

    OLLAMA_BASE_URL: str = Field(
        default="http://127.0.0.1:11434",
        description="Ollama HTTP API root (no path suffix; client calls /api/chat)",
    )
    OLLAMA_MODEL: str = Field(
        default="llama3.2",
        description="Ollama model name (must be pulled locally, e.g. ollama pull llama3.2)",
    )
    OLLAMA_TIMEOUT_S: float = Field(
        default=300.0,
        ge=10.0,
        le=7200.0,
        description="Per-request read timeout for Ollama /api/chat (local inference; raise if you see ReadTimeout)",
    )

    GEMINI_API_KEY: str | None = None
    GEMINI_API_BASE: str = Field(default="https://generativelanguage.googleapis.com")
    GEMINI_MODEL: str = Field(
        default="gemini-2.0-flash",
        description="Model id for generateContent (e.g. gemini-2.0-flash), not models/gemini/...",
    )
    GEMINI_MIN_REQUEST_INTERVAL_S: float = Field(
        default=1.0,
        ge=0.0,
        description="Minimum spacing between Gemini generateContent calls (serial); reduces 429",
    )
    GEMINI_MAX_RETRIES: int = Field(
        default=10,
        ge=0,
        le=32,
        description="Retries for Gemini HTTP 429/5xx per request",
    )

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    ENRICH_CONCURRENCY: int = Field(default=4, ge=1, le=32)
