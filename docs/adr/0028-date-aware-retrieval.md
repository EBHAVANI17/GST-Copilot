# 28. Date-aware retrieval: filtering provisions by effective dates

Date: 2026-10-31
Status: Accepted

## Context

GST statutory provisions evolve over time through Amendment Acts, Rules notifications, and CBIC circulars. A rule applicable today may not have applied in 2019, and a circular clarifying reconciliation for FY 2017-18 and 2018-19 (such as Circular 183/15/2022-GST or Circular 193/05/2023-GST) was issued on specific dates and may apply only to certain periods.

In M5 (ADR 0024), the corpus schema and database `documents` table added:
- `issued_on`: date the notification or circular was gazetted / issued.
- `effective_from`: date from which the statutory provision took legal effect.
- `effective_to`: date on which the provision was rescinded or superseded (`NULL` if currently in force).

**Prior gap (ADR 0024 Follow-up 2):**
Although effective dates were ingested and stored in Postgres, retrieval in `gst_copilot.rag.retriever` did not filter on them. A superseded document or a document issued years after the question's target period was still retrieved and shown in context.

## Decision

### 1. `as_of` Date in API & Service Layers

Add `as_of: date | None = None` to:
- `AskRequest` (`POST /ask` and `POST /ask/stream`): optional ISO date string (`YYYY-MM-DD`).
- `AskResult` and `Passage`: reports the `as_of` date evaluated.
- `ask()` and `ask_stream()` in `gst_copilot.rag.service`.
- `search()`, `candidate_pool()`, `vector_search()`, and `keyword_search()` in `gst_copilot.rag.retriever`.

When `as_of` is omitted in the request, it defaults to `None` (retrieves without temporal filtering, preserving full backwards compatibility). Clients or callers inquiring about a specific date or return period provide `as_of="YYYY-MM-DD"`.

### 2. SQL Retrieval Filtering

In `gst_copilot.rag.retriever._base()`:

```python
if as_of is not None:
    stmt = stmt.where(
        (Document.effective_from.is_(None) | (Document.effective_from <= as_of))
        & (Document.effective_to.is_(None) | (Document.effective_to >= as_of))
    )
```

This applies uniformly across:
- **Vector search (cosine distance over pgvector)**
- **Keyword search (ts_rank_cd over tsvector)**
- **Candidate pool generation for reranking**

### 3. Observability & Golden Evaluation

- **AskLog:** When `as_of` is passed, `AskRecorder` stores `as_of.isoformat()` in `AskLog.config["as_of"]`.
- **Golden Evaluations:** `GoldenItem` in `evals/golden.py` accepts an optional `as_of` date so historical and multi-period golden queries evaluate against the intended statutory point in time.

## Consequences

- Prevents anachronistic citations: queries for an invoice in 2020 will not cite Circular No. 170/02/2022 or Circular No. 193/05/2023.
- When an older circular is marked with `effective_to` upon being superseded, queries with `as_of >= effective_to` automatically omit the stale provision.
- Existing unit and integration tests without `as_of` remain unchanged and green.
