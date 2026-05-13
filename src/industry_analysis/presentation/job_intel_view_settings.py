"""Minimal settings for read-only job-intel dashboard APIs (no Adzuna keys required)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobIntelViewSettings(BaseSettings):
    """Load ``DATA_DIR`` from env / ``.env`` for dashboard JSON reads."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATA_DIR: Path = Field(default=Path("data/job_intel"))
