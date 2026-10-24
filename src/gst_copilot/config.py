"""Application settings.

All configuration comes from environment variables (or a local .env file),
never from values hard-coded in the code. This is the "config" rule of the
twelve-factor app: the same Docker image runs in dev, CI and production,
and only the environment changes.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "ci", "staging", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://gst:gst@localhost:5432/gst_copilot"
    redis_url: str = "redis://localhost:6379/0"

    # How long a readiness check may wait on a dependency before reporting it down.
    dependency_timeout_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """One Settings object per process, created on first use."""
    return Settings()
