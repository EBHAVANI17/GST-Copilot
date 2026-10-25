# GST Copilot

A date-aware GST compliance assistant for small businesses and their accountants:

- **Law Q&A:** answers correct for the transaction date, with section-level citations, and refusal when no source supports an answer
- **ITC reconciliation:** purchase register vs GSTR-2B, with explained mismatches
- **Invoice checker:** GSTIN, tax type, rate on date, totals
- **Return preparation:** a traceable draft GSTR-3B (drafts only; it never files returns)

> Information, not tax advice. Built on public law documents and synthetic transaction data.

## Status

| Milestone | Scope | Status |
|---|---|---|
| M0 | Skeleton: API, worker, Postgres + pgvector, Redis, migrations, CI/CD | ✅ |
| M1 | Baseline RAG: ingestion, embeddings, vector search, `/ask`, evaluation harness | ✅ |
| M2 | Retrieval quality + CI eval gate | |
| M3 | Observability, cost, latency | |
| M4 | ITC reconciliation + invoice checker | |
| M4b | Return preparation | |
| M5 | Data freshness + safety | |
| M6 | Hardening + launch | |

## Targets (SLOs)

| Metric | Target | Current |
|---|---|---|
| Retrieval hit@5 | ≥ 0.85 | – |
| Citation accuracy | ≥ 0.95 | – |
| Correct refusal on unanswerable | ≥ 0.90 | – |
| p95 latency, Q&A | ≤ 5 s | – |
| New notification indexed | within 24 h | – |

## Architecture (M1)

```
corpus/manifest.csv ─→ ingest (CLI or worker job): extract → chunk → embed ─→ Postgres + pgvector
                                                                              (documents, chunks, HNSW index)
client ─→ FastAPI /ask: embed question → vector search top-k → grounded prompt → LLM → citation check
              /health, /ready                                                     (any OpenAI-compatible API)
```

Design decisions are recorded in [docs/adr](docs/adr).

## Run locally

Requirements: Python 3.11+, Docker Desktop, Git.

```bash
cp .env.example .env              # Windows PowerShell: copy .env.example .env
docker compose up --build         # db, redis, migrations, api, worker
curl http://localhost:8000/ready  # {"status":"ready", ...}
```

Open http://localhost:8000/docs for the interactive API docs.

### Load documents and ask a question

```bash
# 1. Put official PDFs in corpus/raw/ and list them in corpus/manifest.csv (see corpus/README.md)
python -m gst_copilot.ingest corpus/manifest.csv

# 2. Ask (retrieval-only until an LLM is configured in .env)
curl -X POST http://localhost:8000/ask -H "content-type: application/json" \
     -d '{"question": "What does the Act say about registration?"}'

# 3. Evaluate on your golden set
python -m gst_copilot.evals evals/golden.jsonl
```

## Results

| Version | hit@5 | MRR | Keyword correctness | Citation accuracy | Correct refusal | p95 latency |
|---|---|---|---|---|---|---|
| M1 baseline (fixed chunks, vector only) | 0.875 | 0.635 | – | – | – | 58.5 ms (retrieval only) |


Golden set: 10 questions (8 answerable, 2 unanswerable), 3 documents. Document-level hit@k; section-level matching comes in M2. Missed: q008 (s.16(3) diluted inside a fixed-size chunk).

| M1 + qwen2.5:3b (Ollama, RTX 4050) | 0.875 | 0.635 | 0.25 | 0.60 | 1.00 | 3.0 s |
| M1 + qwen2.5:7b (18% on CPU) | 0.875 | 0.635 | 0.25 | 0.80 | 1.00 | 32.3 s |


Both models: false refusal 0.25, invalid citation rate 0.10. The 7B model improved citations only, at 10x latency, so the bottleneck is retrieval, not model size. Development stays on 3B; models are compared again after M2.

| M2.1 section chunks + qwen2.5:3b | 0.875 | 0.688 | 0.375 | 0.80 | 1.00 | 4.5 s |

M2.1: section_hit@5 0.875 (8 questions). q008 (s.16(3)) now found; q003 (s.16(2) 180-day proviso) lost. Invalid citations 0.10 → 0.00, false refusals 0.25 → 0.125; answers without citation 0.167 → 0.286.

| M2.2 + numbers in digits, vector (default) | 1.0 | 0.65 | 0.25 | 0.71 | 1.00 | 17.7 s* |
| M2.2 hybrid RRF (opt-in, not default) | 1.0 | 0.854 | 0.25 | 1.00 | 1.00 | 9.7 s* |

M2.2: section_hit@5 0.875 (vector) vs 0.75 (hybrid). Hybrid ranked documents better but lost the right section for q001/q002, so vector stays the default (ADR 0005). *p95 includes the LLM cold start.

## Develop

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install

ruff check . && ruff format --check .
mypy src
pytest -q                                    # unit tests
EMBEDDING_PROVIDER=fake pytest -m integration  # needs Postgres (docker compose up db)
```

## Project layout

```
src/gst_copilot/
  api/main.py        app factory, request-ID + logging middleware
  api/health.py      /health (liveness) and /ready (readiness)
  config.py          settings from environment variables
  logging.py         JSON logs with request IDs
  db/session.py      async SQLAlchemy engine and sessions
  db/models.py       tables
  worker.py          arq background worker (ping, ingest jobs)
  embeddings.py      Embedder interface: fastembed (local) and fake (tests)
  ingest/            manifest → extract → chunk → embed → store (idempotent)
  rag/               retriever (pgvector), prompt, LLM client, ask service
  api/ask.py         POST /ask
  evals/             golden set loader, metrics, evaluation CLI
corpus/              manifest.csv (committed) and raw/ documents (not committed)
evals/               golden.jsonl: your test questions
migrations/          alembic database migrations
tests/               unit tests (no external services needed)
docs/adr/            architecture decision records
.github/workflows/   CI: lint, types, tests, integration, image publish
```
