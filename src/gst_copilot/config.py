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

    # --- Embeddings (M1) ---
    # "fastembed" runs a small open model locally on CPU (downloaded on first use).
    # "fake" is a deterministic word-hashing embedder for tests and CI: no download.
    embedding_provider: Literal["fastembed", "fake"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Must match the VECTOR(n) column in migration 0002. Changing it needs a new migration.
    embedding_dim: int = 384
    embedding_cache_dir: str | None = None

    # --- Chunking and retrieval (M1 baseline; M2 replaces naive chunking) ---
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    retrieval_top_k: int = 5

    # --- LLM (any OpenAI-compatible API: Ollama, OpenAI, Groq, OpenRouter...) ---
    # Leave llm_base_url empty to run in retrieval-only mode (no generation).
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """One Settings object per process, created on first use."""
    return Settings()
