# 6. Cross-encoder reranker

Date: 2026-10-25
Status: Accepted (default on, vector candidates, MiniLM-L-6)

## Context

ADR 0005: hybrid retrieval found more of the right documents but put the right
section lower, because Reciprocal Rank Fusion only sees ranks, and the keyword list
was noisy. Neither search ever reads the question and a chunk together.

## Decision

Two-stage retrieval:

1. **Candidates** (fast, for recall): top `RERANK_CANDIDATES` (20) from vector search,
   plus top 20 from keyword search when `RETRIEVAL_MODE=hybrid`.
2. **Rerank** (slower, for precision): a cross-encoder scores each
   (question, chunk) pair; the top k by that score go to the LLM.

- Model through fastembed (ONNX, CPU), so no PyTorch and no new dependency.
  Default `Xenova/ms-marco-MiniLM-L-6-v2` (80 MB, fast); `BAAI/bge-reranker-base`
  (1 GB) is the stronger option to compare.
- `RERANKER=none|cross-encoder|fake` (fake = word overlap, for tests and CI).
- Passages report `rerank_score`; timings report `rerank` ms separately.
- `evals --retrieval-only` skips the LLM, so retrieval experiments take seconds.

## Options rejected

- An LLM as reranker ("which passage answers this?"): slow on a laptop GPU, and
  non-deterministic.
- A hosted rerank API: costs money and sends every question outside.

## Consequences

- Extra latency per question: about 40 cross-encoder passes on CPU.
- MS MARCO models were trained on web search, not law; the golden set decides
  whether they help here. If neither model helps, the reranker stays off.

## Results (golden set v1, 8 answerable questions, retrieval only)

| Run | section_hit@5 | section_hit@1 | section MRR | p95 latency | Missed |
|---|---|---|---|---|---|
| A vector, no reranker | 0.875 | 0.375 | 0.625 | 0.07 s | q003 |
| B vector + MiniLM-L-6 | 1.0 | 0.875 | 0.917 | 1.9 s | - |
| C hybrid + MiniLM-L-6 | 1.0 | 0.875 | 0.917 | 2.7 s | - |
| D hybrid + bge-reranker-base | 0.875 | 0.875 | 0.875 | 13.2 s | q005 |

Decision: **B** becomes the default. Hybrid candidates (C) gave no gain over B at
+0.8 s, so retrieval stays vector-only. The larger reranker (D) was worse and 7x
slower. Caveat: 8 questions; one question moves section_hit@5 by 0.125. The golden
set must grow before these numbers are treated as stable.
