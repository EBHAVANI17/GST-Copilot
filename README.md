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
| M1 | Baseline RAG + golden set | ⏳ |
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

## Architecture (M0)

```
client → FastAPI (/health, /ready) ──→ PostgreSQL + pgvector
                    │                     ↑ alembic migrations
                    └─→ Redis ←── arq worker (background jobs)
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

## Develop

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install

ruff check . && ruff format --check .
mypy src
pytest -q
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
  worker.py          arq background worker
migrations/          alembic database migrations
tests/               unit tests (no external services needed)
docs/adr/            architecture decision records
.github/workflows/   CI: lint, types, tests, integration, image publish
```
