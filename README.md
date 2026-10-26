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

| M2.3 + cross-encoder reranker (MiniLM-L-6, default) | 1.0 | 0.938 | 0.25 | 0.83 | 1.00 | X s |

M2.3: section_hit@5 1.0, section_hit@1 0.875 (was 0.375). Hybrid candidates and bge-reranker-base gave no gain (ADR 0006). Retrieval is no longer the bottleneck: 2 of 8 answerable questions are still refused with the right section retrieved.

| M2.4 prompt m2-v3 + max_tokens (3 runs) | 1.0 | 0.938 | <keyword_recall> | <citation_section_accuracy> | 1.00 | <p95> s |

M2.4: prompt ablation (ADR 0007), one change each on m1-v1: "at most 6 points" (m2-v3) won; section headers hurt. New metrics: keyword_recall, context_recall, citation_section_accuracy, partial_answers; --runs 3 averages LLM noise.

| M2.5 + section expansion (small-to-big, 3 runs) | 1.0 | 0.938 | 0.616 | 0.905 | 1.00 | 12.6 s |

M2.5: context_recall 0.662 → 0.938 (ADR 0008). Retrieval is no longer the bottleneck; generation is. p95 12.6 s breaks the 5 s target: accepted for correctness, latency is the M3 focus.

| M2.5 with qwen2.5:7b q4 (18% CPU) | 1.0 | 0.938 | 0.756 | 0.857 | 1.00 | 49.6 s |
| M2.5 with qwen2.5:7b q3 (100% GPU) | 1.0 | 0.938 | 0.594 | 0.875 | 1.00 | 24.4 s* |

Model choice (ADR 0009): 7B q4 answers best but doesn't fit 6 GB VRAM; 3-bit fits but loses the gain. Default stays qwen2.5:3b. *includes first-load time.

| M2.6 + PDF text repair (3 runs) | 1.0 | 1.0 | 0.583 | 0.822 | 1.00 | 10.3 s |

M2.6: repaired PDF words (ADR 0010); context_recall 1.0, so every expected phrase reaches the LLM. Answer metrics did not improve (within noise on 8 questions): generation with the 3B model is now the only bottleneck (ADR 0009).

### Golden set v2 (30 questions: 25 answerable, 5 unanswerable)

Every keyword checked against the PDFs (`python -m gst_copilot.evals.check`). Retrieval only.

| Version | hit@5 | hit@1 | section_hit@5 | section_hit@1 | section MRR |
|---|---|---|---|---|---|
| M2.6 on golden v2 | 0.80 | 0.60 | 0.68 | 0.44 | 0.537 |
| M2.7 + GST glossary query expansion | 0.92 | 0.76 | 0.76 | 0.52 | 0.613 |

Golden v1 overstated quality: the system had been tuned on its 8 ITC questions (section_hit@5 1.0 on v1, 0.68 on v2). Wider candidate pool and hybrid search gave no gain (ADR 0011). Defaults chosen on v2; a held-out set measures the honest number.


| M2.7 on held-out set (10 new questions, run once) | 0.625 | 0.50 | 0.625 | 0.375 | 0.463 |


Held-out answers (3 runs): keyword_recall 0.271, citation_section_accuracy 0.667, correct refusal 1.0, false refusal 0.125, p95 7.0 s. This is the honest estimate on unseen GST topics; golden v1 and v2 overstate quality because defaults were tuned on them.


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
