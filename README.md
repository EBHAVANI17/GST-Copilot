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
| M2 | Retrieval and answer quality, measured by ablations | ✅ |
| M3 | Observability, cost, latency | ✅ |
| M4 | ITC reconciliation + invoice checker | ✅ |
| M4b | Return preparation | ✅ |
| M5 | Data freshness + safety | ✅ |
| M6 | Hardening + launch | ✅ |

Milestone summaries: [M3](docs/milestones/m3.md), [M4](docs/milestones/m4.md), [M5](docs/milestones/m5.md), [M6](docs/milestones/m6.md)

## Targets (SLOs)

| Metric | Target | Current |
|---|---|---|
| Retrieval section_hit@5 | ≥ 0.85 | 0.786 golden v2, 0.625 held-out |
| Citation accuracy | ≥ 0.95 | 0.74 (3B model; ADR 0009) |
| Correct refusal on unanswerable | ≥ 0.90 | 1.0 |
| Time to first word, Q&A (p95) | ≤ 5 s | 2.5 s (streaming) |
| Full answer, Q&A (p95) | ≤ 5 s | 7.6 s |
| New notification indexed | within 24 h | – (M5) |

## Architecture

```
corpus/manifest.csv ─→ ingest: extract → repair → section chunks → embed ─→ Postgres + pgvector
client ─→ FastAPI /ask, /ask/stream:
          glossary expansion → vector search → cross-encoder rerank → whole sections
          → grounded prompt → LLM (any OpenAI-compatible API) → citation + refusal checks
          → ask_logs (answers, timings, tokens) ← /feedback
          /health, /ready (waits for model warm-up)
```

## Design decisions

### What this is
GST Copilot helps with Indian GST input tax credit (ITC): it answers
law questions with citations, reconciles a purchase register against
GSTR-2B, checks single invoices, and drafts GSTR-3B Table 4.
It is a reconciliation and information aid, not tax advice.
All reconcile and invoice testing uses synthetic data.

### 1. Scope and assumptions
- **Users:** small businesses and accountants preparing monthly returns.
- **Human in the loop:** the AI only answers law questions; a person decides what to file.
- **Statutory law source:** law is loaded from official CBIC PDFs. Versions and as-of dates are listed in `corpus/manifest.csv` and dynamically surfaced in every `/ask` response. The loaded Act is as of 30-09-2020, so answers reflect that statutory snapshot.
- **Unverified rules:** the place-of-supply (tax type) rule is explicitly marked unverified in code and ADRs.

### 2. Architecture
- **Law Q&A (`/ask`):** vector search over section-wise chunks in Postgres + pgvector ([ADR 0002](docs/adr/0002-postgres-pgvector-as-single-store.md), [ADR 0004](docs/adr/0004-structure-aware-chunking.md)), section context expansion ([ADR 0008](docs/adr/0008-section-expansion.md)), a cross-encoder reranker ([ADR 0006](docs/adr/0006-cross-encoder-reranker.md), [ADR 0017](docs/adr/0017-rerank-10-candidates.md)), then a local LLM (Ollama, `qwen2.5:3b`) that must cite chunk references. Keyword search exists but is off by default ([ADR 0005](docs/adr/0005-hybrid-retrieval.md)), so retrieval is vector + rerank, not hybrid.
- **Numbers use plain code, not AI ([ADR 0019](docs/adr/0019-itc-reconciliation-data.md)):** reconciliation matching, GSTIN Mod-36 checksum, invoice arithmetic, and the Table 4 draft are deterministic, so the same input always gives the exact same output.
- **Reconciliation engine (`/reconcile`):** compares purchase register and GSTR-2B CSVs, labels each invoice across 10 categories ([ADR 0020](docs/adr/0020-reconciliation-matcher.md), [ADR 0022](docs/adr/0022-hard-reconciliation-data.md)), totals tax per label, provides statutory action guidance ([ADR 0026](docs/adr/0026-reconciliation-explanations.md)), and compiles an auditable Table 4 draft ([ADR 0027](docs/adr/0027-draft-gstr3b-table4.md)) linking every amount back to invoice IDs. Uploaded files are processed strictly in memory and never stored on disk or in the database.
- **Date-aware corpus ([ADR 0028](docs/adr/0028-date-aware-retrieval.md)):** documents carry `effective_from` / `effective_to`, so superseded law can be excluded for current questions.

### 3. Observability and evaluation
- **Audit logging:** each `/ask` call is logged (`AskLog`; [ADR 0012](docs/adr/0012-ask-logs-and-feedback.md)); users can send feedback via `/feedback`.
- **Golden set:** 34 questions (29 answerable with expected sections, 5 unanswerable) with keywords verified against real PDFs (`python -m gst_copilot.evals.check`). Scores under `m2-v7`: `section_hit@5` 0.793, `citation_section_accuracy` 0.812 (81.2%), `correct_refusal` 1.0 (100%), `false_refusal` 0.103 (10.3%).
- **Known failure & prompt iteration:** the 3B model can invert the 180-day proviso (an add-back consequence turned into an entitlement condition). Logged as `q044` in `evals/golden.jsonl`. Prompt change `m2-v7` vs `m2-v3` on the full golden set: citation section accuracy jumped from 0.611 to 0.812 (+20.1%), false refusals dropped from 0.138 to 0.103 (-3.5%), and the 180-day rule is accurately formulated as an output-tax add-back consequence.
- **Citation boundary:** citation checks confirm that a cited chunk exists, not that the generated claim matches it. Answers always require human review.

### 4. Production and operations
- **Hardened stack ([ADR 0029](docs/adr/0029-m6-hardening-and-launch.md)):** FastAPI, Docker Compose (Postgres with pgvector, Redis), `/health` and `/ready`, request IDs, security headers, CORS, SQLAlchemy QueuePool tuning, graceful shutdown, and 274 automated tests.
- **Freshness monitoring:** `/ready` reports corpus age so stale law is visible; 24-hour CBIC notification monitoring procedure defined in [ADR 0024](docs/adr/0024-notification-watcher.md).
- **Safety boundaries ([ADR 0025](docs/adr/0025-ask-safety.md)):** input length limits (1,000 chars) and prompt-injection resistance verified.

### 5. Limits and what I'd do next
- **Local model capacity:** 3.6 s median latency (p50); switching to a larger model (e.g. `qwen2.5:7b`) is a single configuration line in `.env` and natively handles complex proviso reasoning without prompt tradeoffs.
- **Corpus updates:** index current amendments to the CGST Act and Rules (e.g. the post-2022 30-November cut-off under Notification 18/2022-CT), then re-run the golden set.
- **Tax-type rules:** verify place-of-supply exceptions (e.g. SEZ supplies) against the IGST Act.
- **Hybrid search tuning:** evaluate BM25 / ParadeDB once term-frequency dilution in Postgres `ts_rank_cd` is addressed.

### Statutory Corpus Coverage

Built on public statutory law:
- **Acts & Rules:** Central Goods and Services Tax (CGST) Act 2017 (updated to 30-09-2020), Integrated Goods and Services Tax (IGST) Act 2017, and CGST Rules 2017 (Part A, amended up to 24-09-2021).
- **Circulars & Notifications:** Key administrative and clarification circulars including Circular No. 170/02/2022-GST (GSTR-3B Table 4 reporting) and Circular No. 193/05/2023-GST.
- **Temporal Freshness:** Monitored against CBIC gazette releases under ADR 0024. Ingest new notifications or amendments by updating `corpus/manifest.csv` and running `python -m gst_copilot.ingest corpus/manifest.csv`.

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

# 2b. Watch a streamed answer in the terminal
python -m gst_copilot.client "What are the conditions for taking input tax credit?"

# 3. Evaluate on your golden set; usage report from real questions
python -m gst_copilot.evals evals/golden.jsonl
python -m gst_copilot.observe --days 7
```

## Results

### Golden set v1 (10 questions: 8 answerable, 2 unanswerable)

| Version | hit@5 | MRR | Keyword correctness | Citation accuracy | Correct refusal | p95 latency |
|---|---|---|---|---|---|---|
| M1 baseline (fixed chunks, vector only) | 0.875 | 0.635 | – | – | – | 58.5 ms (retrieval only) |
| M1 + qwen2.5:3b (Ollama, RTX 4050) | 0.875 | 0.635 | 0.25 | 0.60 | 1.00 | 3.0 s |
| M1 + qwen2.5:7b (18% on CPU) | 0.875 | 0.635 | 0.25 | 0.80 | 1.00 | 32.3 s |
| M2.1 section chunks + qwen2.5:3b | 0.875 | 0.688 | 0.375 | 0.80 | 1.00 | 4.5 s |
| M2.2 + numbers in digits, vector (default) | 1.0 | 0.65 | 0.25 | 0.71 | 1.00 | 17.7 s* |
| M2.2 hybrid RRF (opt-in, not default) | 1.0 | 0.854 | 0.25 | 1.00 | 1.00 | 9.7 s* |
| M2.3 + cross-encoder reranker (default) | 1.0 | 0.938 | 0.25 | 0.83 | 1.00 | – |
| M2.5 + section expansion (3 runs) | 1.0 | 0.938 | 0.616 | 0.905 | 1.00 | 12.6 s |
| M2.5 with qwen2.5:7b q4 (18% CPU) | 1.0 | 0.938 | 0.756 | 0.857 | 1.00 | 49.6 s |
| M2.5 with qwen2.5:7b q3 (100% GPU) | 1.0 | 0.938 | 0.594 | 0.875 | 1.00 | 24.4 s* |
| M2.6 + PDF text repair (3 runs) | 1.0 | 1.0 | 0.583 | 0.822 | 1.00 | 10.3 s |

*includes the LLM's first-load time. From M2.5 the keyword column is keyword_recall and
the citation column is citation_section_accuracy (stricter: the right section, not only
the right document).

- **M1:** the 7B model improved citations only, at 10x latency: the bottleneck was retrieval, not model size.
- **M2.1:** section_hit@5 0.875; s.16(3) found, the s.16(2) 180-day proviso lost.
- **M2.2:** hybrid ranked documents better but lost the right section for q001/q002, so vector stays the default (ADR 0005).
- **M2.3:** section_hit@1 0.375 → 0.875. Retrieval stopped being the bottleneck (ADR 0006).
- **M2.4:** prompt ablation, one change at a time; "at most 6 points" (m2-v3) won, section headers hurt (ADR 0007).
- **M2.5:** context_recall 0.662 → 0.938 (ADR 0008).
- **Model choice (ADR 0009):** 7B q4 answers best but does not fit 6 GB VRAM; 3-bit fits but loses the gain. Default stays qwen2.5:3b.
- **M2.6:** context_recall 1.0; answer metrics did not improve, so generation with the 3B model is the bottleneck.

### Golden set v2 and held-out set (retrieval)

Every keyword checked against the PDFs (`python -m gst_copilot.evals.check`).

| Version | hit@5 | hit@1 | section_hit@5 | section_hit@1 | section MRR |
|---|---|---|---|---|---|
| M2.6 on golden v2 (30 questions) | 0.80 | 0.60 | 0.68 | 0.44 | 0.537 |
| M2.7 + GST glossary query expansion | 0.92 | 0.76 | 0.76 | 0.52 | 0.613 |
| M2.7 on held-out set (10 new questions, run once) | 0.625 | 0.50 | 0.625 | 0.375 | 0.463 |
| M3 on golden v2 + 3 application questions (33) | 0.893 | 0.75 | 0.786 | 0.536 | 0.643 |

Golden v1 overstated quality: the system had been tuned on its 8 ITC questions. Held-out
answers (3 runs): keyword_recall 0.271, citation_section_accuracy 0.667, correct refusal
1.0, false refusal 0.125. This is the honest estimate on unseen GST topics.

### M3: latency and cost (golden v2, 33 questions)

| Change | Before | After | ADR |
|---|---|---|---|
| Warm-up at startup | first question 17 s | models loaded before /ready | 0015 |
| Streaming (`/ask/stream`) | first word with the whole answer (~13 s) | first word while writing | 0016 |
| Rerank 10 candidates | ttft p50 3.4 s | ttft p50 1.5-2.3 s | 0017 |

Cost (ADR 0018): 2425 prompt + 115 answer tokens per answer. Local model: no per-token
cost; on GPT-5 mini about 0.84 USD per 1,000 answers.

## What M2 changed, and how it was measured

Every change was an ablation (one variable at a time) with an ADR in docs/adr.

| Step | Change | Effect | ADR |
|---|---|---|---|
| 1 | Section-aware chunks + noise removal | right section found for s.16(3) | 0004 |
| 2 | Numbers in digits; hybrid search tried | hybrid lowered section_hit, kept off | 0005 |
| 3 | Cross-encoder reranker | section_hit@1 0.375 → 0.875 (v1) | 0006 |
| 4 | Answer limits, prompt ablation | p95 9.3 s → 5.8 s; "≤ 6 points" prompt won | 0007 |
| 5 | Whole sections to the LLM | context_recall 0.66 → 0.94 | 0008 |
| 6 | Model comparison on 6 GB GPU | 7B best but 4x slower; 3B default | 0009 |
| 7 | PDF word repair | context_recall 1.0 (v1) | 0010 |
| 8 | Golden v2 + glossary query expansion | section_hit@5 0.68 → 0.76 (v2) | 0011 |

Evaluation in three levels: golden v1 (8 questions) and v2 (25) were used for tuning;
a held-out set (8 answerable + 2 unanswerable, run once) gives the honest estimate:
section_hit@5 0.625, correct refusal 1.0. Golden keywords are checked against the
PDFs before every run (python -m gst_copilot.evals.check).

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
  api/main.py        app factory, request-ID + logging middleware, warm-up at startup
  api/health.py      /health (liveness) and /ready (readiness, waits for warm-up)
  api/ask.py         POST /ask and POST /ask/stream (server-sent events)
  api/feedback.py    POST /feedback
  config.py          settings from environment variables
  logging.py         JSON logs with request IDs
  db/                async SQLAlchemy engine, sessions, tables
  worker.py          arq background worker (ping, ingest jobs)
  embeddings.py      Embedder interface: fastembed (local) and fake (tests)
  ingest/            manifest → extract → repair → section chunks → embed → store
  rag/               retriever, reranker, glossary, section expansion, prompt, LLM, ask service
  observe/           ask logs, usage report, tokens and cost
  evals/             golden sets, metrics, checker, LLM judge, evaluation CLI
  client.py          terminal client for streamed answers
corpus/              manifest.csv (committed) and raw/ documents (not committed)
evals/               golden.jsonl and holdout.jsonl
migrations/          alembic database migrations
tests/               unit and integration tests
docs/adr/            architecture decision records
docs/milestones/     milestone summaries
.github/workflows/   CI: lint, types, tests, integration, image publish
```
