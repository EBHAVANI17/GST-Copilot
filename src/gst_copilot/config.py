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

    # --- Chunking and retrieval ---
    # "section": one section/rule per chunk with a context header (M2, default).
    # "fixed": the M1 baseline of fixed-size windows, kept for comparison.
    chunking_strategy: Literal["section", "fixed"] = "section"
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    retrieval_top_k: int = 5
    # "vector": embeddings only (default). "hybrid": vector + keyword (full-text) search
    # merged with Reciprocal Rank Fusion. Hybrid lowered section_hit@5 (0.875 -> 0.75) on
    # the golden set, so it stays opt-in until a reranker is added (see ADR 0005).
    retrieval_mode: Literal["hybrid", "vector"] = "vector"
    # How many candidates each search returns before fusion.
    retrieval_candidates: int = 30
    # RRF constant: score = sum of 1 / (rrf_k + rank). 60 is the usual default.
    rrf_k: int = 60
    # Reranker (M2): re-score candidates with a cross-encoder, then keep the top k.
    # "none" = off, "cross-encoder" = a fastembed model (downloads on first use),
    # "fake" = word overlap, for tests and CI.
    # Default on: it raised section_hit@1 from 0.375 to 0.875 on the golden set (ADR 0006).
    reranker: Literal["none", "cross-encoder", "fake"] = "cross-encoder"
    # Small and fast (80 MB). Stronger, slower: BAAI/bge-reranker-base (1 GB).
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Candidates per search list given to the reranker (hybrid: up to 2x this).
    rerank_candidates: int = 20
    # "glossary": add the law's wording to everyday terms in the question before
    # searching ("ITC" -> "ITC (input tax credit)"), see rag/glossary.py.
    # Default on: section_hit@5 0.68 -> 0.76 on golden v2 (ADR 0011).
    query_expansion: Literal["none", "glossary"] = "glossary"
    # What the LLM sees. "none": the top-k ranked pieces. "section": the sections of
    # those pieces, whole and in order (small-to-big), up to context_max_chars.
    # Default "section": context_recall 0.662 -> 0.938 on the golden set (ADR 0008).
    context_expansion: Literal["none", "section"] = "section"
    # ~2,200 tokens: leaves room for rules + answer in Ollama's default 4,096 window.
    context_max_chars: int = 8000

    # --- Observability (M3) ---
    # Store every /ask in the ask_logs table (question, passages, answer, timings).
    # Questions can contain personal or business details: see ADR 0012 on retention.
    ask_log_enabled: bool = True

    # --- LLM (any OpenAI-compatible API: Ollama, OpenAI, Groq, OpenRouter...) ---
    # Leave llm_base_url empty to run in retrieval-only mode (no generation).
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 60.0
    # Hard cap on answer length. Stops runaway answers (one m1-v1 answer ran to
    # 2,500 characters and dominated p95 latency). Truncated answers are flagged.
    llm_max_tokens: int = 512
    # > 0 discourages repeating the same words (0 = off). Legal answers repeat terms
    # like "input tax credit" legitimately, so keep it small if you use it.
    llm_frequency_penalty: float = 0.0
    # --- LLM judge for evaluation (offline; see evals/judge.py, ADR 0014) ---
    # Empty base URL / key = use the same server as the answering LLM.
    judge_base_url: str = ""
    judge_api_key: str = ""
    judge_model: str = "qwen2.5:7b"
    judge_timeout_seconds: float = 300.0
    # Which prompt in rag/prompt.py PROMPTS to use. m2-v3 won the ablation (ADR 0007).
    prompt_version: Literal["m1-v1", "m2-v2", "m2-v3", "m2-v4", "m2-v5", "m2-v6"] = "m2-v3"

    @property
    def chunker_version(self) -> str:
        """Stored with each document; a change triggers re-chunking on the next ingest."""
        from gst_copilot.ingest.structure import STRUCTURE_VERSION

        version = STRUCTURE_VERSION if self.chunking_strategy == "section" else "v1"
        return (
            f"{self.chunking_strategy}-{version}-{self.chunk_size_chars}-{self.chunk_overlap_chars}"
        )


@lru_cache
def get_settings() -> Settings:
    """One Settings object per process, created on first use."""
    return Settings()
