# 5. Hybrid retrieval and numbers in digits

Date: 2026-10-25
Status: Accepted (numbers in digits); hybrid retrieval kept opt-in, see Results

## Context

After structure-aware chunking (ADR 0004), q003 ("180 days" non-payment rule,
s.16(2) second proviso) was not retrieved. The top 5 were refund and revocation
rules: chunks about time limits in general. Two causes:

- The Act writes "one hundred and eighty days"; users write "180 days". A small
  embedding model does not reliably connect the two.
- Pure vector search matches meaning and blurs exact terms: numbers, section
  numbers, form names such as GSTR-3B.

## Decisions

1. **Numbers in digits at index time.** "one hundred and eighty days" becomes
   "one hundred and eighty (180) days". Only number phrases followed by a unit
   (days, months, years, per cent, lakh, ...) are annotated. Part of the section
   chunker, version v2, so documents are re-chunked on the next ingest.
2. **Keyword search with Postgres full-text search**: a generated `tsvector` column
   with a GIN index (migration 0004). Words of the question are ORed; `ts_rank_cd`
   prefers chunks with more of them, closer together. No new service.
3. **Hybrid = vector + keyword, merged with Reciprocal Rank Fusion** (RRF, k = 60):
   score = sum of 1 / (60 + rank) over both lists, top 30 candidates from each.
   RRF uses ranks only, so cosine similarity and ts_rank never need calibrating.
4. **Switchable** with `RETRIEVAL_MODE=hybrid|vector` for ablations. Each passage
   reports its rank in both lists (`vector_rank`, `keyword_rank`) for debugging.
5. **The evaluation survives LLM failures**: a failed call is recorded per question
   (`llm_errors`) instead of stopping the run.

## Options rejected

- A separate search engine (Elasticsearch, OpenSearch): another service to run and
  sync. Postgres full-text search is enough at this corpus size (ADR 0002).
- BM25 proper (e.g. the pg_search / ParadeDB extension): better ranking than
  ts_rank_cd, but not in the standard pgvector image. Revisit if keyword quality
  limits retrieval.
- Weighted score blending (a * cosine + b * keyword score): needs tuning and breaks
  whenever either score scale changes.

## Consequences

- Two queries per question instead of one; both use indexes, so latency stays low.
- `ts_rank_cd` is not BM25: it ignores how rare a word is across the corpus. A
  reranker (next M2 step) is expected to matter more than better keyword scoring.

## Results (golden set v1, 8 answerable questions, qwen2.5:3b)

| Run | hit@5 | hit@1 | MRR | section_hit@5 | section MRR |
|---|---|---|---|---|---|
| ADR 0004 section chunks, vector | 0.875 | 0.5 | 0.688 | 0.875 | 0.688 |
| + numbers in digits, vector | 1.0 | 0.375 | 0.65 | 0.875 | 0.625 |
| + hybrid (RRF) | 1.0 | 0.75 | 0.854 | 0.75 | 0.521 |

Hybrid improved document-level ranking but lost the right section for q001 and
q002. Error analysis: the best vector hits (including s.16) were not in the keyword
top 30, because common words ("input tax credit") appear in hundreds of chunks and
ts_rank_cd does not down-weight them. RRF then preferred chunks ranked mid-table in
both lists (e.g. vector #9 + keyword #7 scores 0.029) over vector #1 alone (0.016).

Decision: default `RETRIEVAL_MODE=vector`; keep hybrid behind the flag. Next step:
a cross-encoder reranker over the union of both candidate lists, so keyword search
adds recall and the reranker decides the order.
