"""Load the models when the server starts, not on the first user's question.

Without this, the first /ask after a restart paid for loading the embedding model,
the reranker and the LLM (17-34 s seen in ask_logs and evals). Warm-up runs in the
background at startup; /ready reports "models" as down until it finishes, so a load
balancer (or docker compose healthchecks) does not send users to a cold instance.

The LLM step only makes Ollama load the model into GPU memory. Ollama unloads it
again after OLLAMA_KEEP_ALIVE (default 5 minutes) without requests; set e.g.
OLLAMA_KEEP_ALIVE=1h on the Ollama side to keep it loaded.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field

from gst_copilot.embeddings import get_embedder
from gst_copilot.rag.llm import LLMError, get_llm
from gst_copilot.rag.rerank import get_reranker

log = logging.getLogger("gst_copilot.warmup")


@dataclass
class WarmupState:
    started: bool = False
    done: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


# One per process: the models are cached per process too (lru_cache in get_*).
STATE = WarmupState()


async def _timed(state: WarmupState, name: str, step: Awaitable[None]) -> None:
    start = time.perf_counter()
    try:
        await step
    except Exception as exc:  # a failed step is reported, never crashes startup
        state.errors[name] = f"{type(exc).__name__}: {exc}"[:200]
        log.warning("warm-up step failed", extra={"fields": {"step": name, "error": str(exc)}})
    finally:
        state.timings_ms[name] = round((time.perf_counter() - start) * 1000, 1)


async def warm_up(state: WarmupState = STATE) -> WarmupState:
    """Embedder, reranker, then LLM. CPU-bound model work runs in a thread, so the
    server keeps answering /health while it loads."""
    state.started = True

    async def embed() -> None:
        embedder = await asyncio.to_thread(get_embedder)
        await asyncio.to_thread(embedder.embed_query, "warm up")

    async def rerank() -> None:
        reranker = await asyncio.to_thread(get_reranker)
        if reranker is not None:
            await asyncio.to_thread(reranker.score, "warm up", ["warm up"])

    async def llm() -> None:
        client = get_llm()
        if client is not None:
            try:
                await client.complete([{"role": "user", "content": "Reply with OK."}])
            except LLMError as exc:
                raise RuntimeError("LLM not reachable; /ask will return 502") from exc

    await _timed(state, "embedder", embed())
    await _timed(state, "reranker", rerank())
    await _timed(state, "llm", llm())
    state.done = True
    log.info(
        "warm-up finished",
        extra={"fields": {**{f"ms_{k}": v for k, v in state.timings_ms.items()},
                          "errors": list(state.errors)}},
    )  # fmt: skip
    return state


async def models_ready() -> None:
    """Readiness check: raises until warm-up has finished (see api/health.py)."""
    if not STATE.done:
        raise RuntimeError("warming up" if STATE.started else "warm-up not started")
    # The LLM is optional (retrieval-only mode works without it), so only the
    # embedder and reranker make the instance not ready.
    blocking = {k: v for k, v in STATE.errors.items() if k != "llm"}
    if blocking:
        raise RuntimeError(f"model load failed: {', '.join(blocking)}")
