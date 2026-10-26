# 15. Warm-up at startup, gated by readiness

Date: 2026-10-26
Status: Accepted

## Context

ask_logs and evals showed the first question after a restart taking 17-34 s: the
embedding model, the reranker and the LLM were all loaded on first use. Ollama also
unloads an idle model after 5 minutes (OLLAMA_KEEP_ALIVE), so the next user pays
the LLM load again.

## Decision

- On startup (FastAPI lifespan) a background task loads the embedder and the
  reranker (in a thread, so the event loop keeps serving) and sends the LLM one tiny
  request so Ollama loads it into GPU memory. `WARMUP_ENABLED=true` by default.
- `/ready` gets a `models` check: not ready until warm-up has finished, or if the
  embedder or reranker failed to load. An unreachable LLM is logged but does not
  block readiness, because retrieval-only answers still work.
- `/health` (liveness) is unaffected: the process is alive while it warms up, so
  the platform must not restart it.
- Warm-up timings and errors are logged ("warm-up finished", ms per step).
- Operators keep the LLM loaded with `OLLAMA_KEEP_ALIVE` (e.g. 1h) on the Ollama side.

## Consequences

- A restarted instance is not ready for the model-loading time instead of serving
  one very slow request.
- Each process warms up separately (several uvicorn workers = several loads).
