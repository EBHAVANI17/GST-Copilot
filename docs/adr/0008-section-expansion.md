# 8. Section expansion (small-to-big retrieval)

Date: 2026-10-26
Status: Accepted (default on; latency regression accepted, see Results)

## Context

After the reranker (ADR 0006) and prompt m2-v3 (ADR 0007), section_hit@5 was 1.0
but context_recall only 0.662: a third of the expected key phrases were not in
the passages the LLM saw. Per-question diagnosis (`missing_in_context`):

| Question | Retrieved | Needed |
|---|---|---|
| q001 conditions for ITC | s.16 pieces 77, 80, 81 | 78-79 (s.16(2)(a)-(d)) |
| q002 time limit | s.16 piece 80 | 82 (s.16(4)) |
| q004 blocked credits | five s.17 pieces | the s.17(5) piece with clauses (g)-(i) |
| q003, q008 | (right piece) | PDF text broken: "o f", "Income -\ntax" |

Retrieval finds the right section every time but shows scattered pieces of it.
(q003 and q008 are extraction defects, a separate fix.)

## Decision

- Rank pieces as now (vector search + reranker), then give the LLM the **sections**
  of the ranked pieces, whole and in document order, best section first.
- Budget `CONTEXT_MAX_CHARS=8000` (~2,200 tokens): Ollama's default context is
  4,096 tokens and it silently drops the start of a longer prompt, which is where
  the rules are.
- A section larger than the remaining budget contributes its ranked pieces plus one
  neighbour on each side.
- `AskResult.retrieved` stays the ranked top k (retrieval metrics); the new
  `AskResult.context` is what the LLM saw (context_recall, citation checks, API).
- `CONTEXT_EXPANSION=none|section` for the ablation.

## Options rejected

- Bigger k (10 pieces): more fragments, still unordered, and more distraction
  (q005 was answered from an unrelated Rules passage).
- Smaller sub-section chunks: more precise ranking, but the same fragment problem.

## Consequences

- Fewer distinct sections reach the LLM when a top section is long (s.16 alone is
  ~5,500 characters). Questions needing two long sections may lose the second.

## Results (golden set v1, qwen2.5:3b, prompt m2-v3, mean of 3 runs)

| Metric | pieces (none) | whole sections |
|---|---|---|
| context_recall | 0.662 | 0.938 |
| keyword_recall | 0.506 | 0.616 |
| keyword_correctness | 0.25 | 0.375 |
| citation_accuracy | 0.857 | 1.0 |
| citation_section_accuracy | 0.857 | 0.905 |
| answers_without_citation | 0.125 | 0.167 (0.125-0.25) |
| p95 latency | 5.8 s | 12.6 s |

The only phrases still missing from the context are the two PDF extraction defects
(q003 "o f", q008 "Income -\ntax"). Retrieval is no longer the bottleneck;
generation is (q002 still answered with the s.16(2) 180-day rule although s.16(4)
is now in the context).

Decision: section expansion is the default. Correct answers matter more than speed
for tax questions, but p95 12.6 s breaks the 5 s target. Latency is the main M3
item (streaming, model warm-up, budget tuning).
