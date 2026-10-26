# 17. Rerank 10 candidates instead of 20; keep the 8000-character context

Date: 2026-10-26
Status: Accepted

## Context

After streaming (ADR 0016) the user waits about 5 s before the first word. Two stages
dominate that wait: the cross-encoder reranker (CPU, scores every candidate) and the
LLM reading the prompt (first_token, grows with context size). The evals now report
both per stage (`rerank_p50`, `first_token_p50`, `ttft_p50`, `prompt_tokens_mean`).

Two single-change ablations on golden v2 (33 questions), qwen2.5:3b, prompt m2-v3,
run back to back on the laptop:

- A: `RERANK_CANDIDATES` 20 -> 10
- B: `CONTEXT_MAX_CHARS` 8000 -> 5000

## Results

Retrieval only:

| Metric | Baseline | A: 10 candidates | B: 5000 chars |
|---|---|---|---|
| section_hit@5 | 0.786 | 0.786 | 0.786 |
| section_mrr | 0.637 | 0.643 | 0.637 |
| hit@5 (document) | 0.929 | 0.893 | 0.929 |
| context_recall | 0.688 | 0.700 | **0.541** |
| rerank_p50 ms | 1749 | **961** | 1428 |

B removes key phrases from the prompt for six questions (q002, q004, q012, q022, q028,
q041), so it was rejected without an LLM run. Its rerank time differs from the
baseline although reranking is unchanged: CPU timings vary by about 20% between runs.

With the LLM (baseline vs A, one run each):

| Metric | Baseline | A: 10 candidates |
|---|---|---|
| keyword_recall | 0.413 | 0.454 |
| false_refusal | 0.179 | 0.143 |
| correct_refusal | 1.0 | 1.0 |
| answers_without_citation | 0.304 | 0.125 |
| citation_section_accuracy | 0.75 | 0.667 |
| rerank_p50 ms | 1881 | **850** |
| first_token_p50 ms | 1565 | 1015 |
| ttft_p50 ms | 3376 | **1927** |
| ttft_p95 ms | 7860 | **2865** |
| p95 total ms | 14625 | 9259 |
| prompt_tokens_mean | 2484 | 2425 |

## Decision

Default `RERANK_CANDIDATES=10`. Keep `CONTEXT_MAX_CHARS=8000`.

## Consequences

- About 1 s less before the first word, from reranking alone. The lower first_token
  in A is NOT caused by A (the prompt is only 2% smaller); it is run-to-run variation,
  so the honest gain is the rerank saving.
- Retrieval is unchanged at section level. hit@5 drops on q014, whose section was
  already missed. q004 loses "personal consumption" and "free samples" from its
  context; q005 and q015 gain phrases.
- Answer metrics moved in both directions within the run-to-run noise seen before
  (ADR 0007): more answers cite something, a smaller share of those cite the right
  section. One run each, so this is "no clear regression", not an improvement.
- Fewer candidates means the reranker can rescue fewer vector-search misses (ranks
  11-20). Misses ranked lower (q011, q015, q016 at 27-43, ADR 0011) were never
  reachable; they need better first-stage retrieval, not more candidates.
- first_token (about 1-1.5 s for ~2400 prompt tokens) is now the larger part of the
  wait; cutting the context saves it but loses law text (B). Faster prompt reading
  needs a different model or GPU, out of scope on this laptop (ADR 0009).
