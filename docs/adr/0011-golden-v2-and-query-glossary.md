# 11. Golden set v2, overfitting, and a GST glossary for queries

Date: 2026-10-26
Status: Accepted (glossary on by default)

## Context

The golden set grew from 8 answerable questions (all input tax credit, s.16-18)
to 25 (levy, registration, invoices, returns, payment, refund, Rules 36-46,
multi-document and trap questions). Every keyword was checked against the PDFs
(`evals.check`). Same system, retrieval only:

| | golden v1 (8) | golden v2 (25) |
|---|---|---|
| section_hit@5 | 1.0 | 0.68 |
| section_hit@1 | 0.875 | 0.44 |
| context_recall | 1.0 | 0.68 |

The system had been tuned on the 8 questions it was measured on: overfitting.
Where the right section ranked (top 50, golden v2):

- 1-5: 17 questions; 6-20: q012, q019, q020, q029, q030 (ranking);
- 21-50: q011, q015, q016 (outside the 20 candidates the reranker sees);
- not in top 50: q014, q022 (vocabulary).

q022 ("documents ... before I can claim ITC") missed Rule 36, which q006 ("...
claim input tax credit") finds first. The law never writes "ITC".

## Decisions

1. Golden v2 is the measurement set. Rows measured on v1 are not comparable.
2. Query expansion with a small GST glossary (`QUERY_EXPANSION=glossary`): add the
   law's wording after everyday terms ("ITC (input tax credit)", "bill (invoice)",
   "sales (supplies)"), for search and reranking only; the LLM gets the original
   question. Standard GST vocabulary only, never a term chosen to fix one question.
3. Protect against tuning to the test: after the retrieval changes are chosen on
   golden v2, write 10 new questions not used for tuning and run them once.

## Consequences

- Expansion can add noise ("profile file (furnish)"): harmless for search, but the
  glossary must stay small and generic.
- The reranker sees `RERANK_CANDIDATES` (20) vector hits; q011/q015/q016 rank 27-43,
  so a wider pool is a separate experiment.

## Results (golden v2, 25 answerable, retrieval only, reranker MiniLM-L-6)

| Run | hit@5 | hit@1 | section_hit@5 | section_hit@1 | section MRR | p50 |
|---|---|---|---|---|---|---|
| A vector | 0.80 | 0.60 | 0.68 | 0.44 | 0.537 | 1.6 s |
| B + glossary | 0.92 | 0.76 | 0.76 | 0.52 | 0.613 | 1.5 s |
| C + glossary, 50 candidates | 0.92 | 0.76 | 0.76 | 0.52 | 0.605 | 3.6 s |
| D + glossary, hybrid | 0.92 | 0.76 | 0.76 | 0.52 | 0.613 | 2.8 s |

- The glossary fixed q012, q022 (the "ITC" question) and q030, and lost q019.
- A wider candidate pool (C) and keyword search (D) added nothing and cost latency,
  so q011/q015/q016 are not pool-size problems.
- Decision: B is the default. Still missed: q011 (s.9), q014 (s.39), q015 (s.49),
  q016 (s.54), q019 (rule 43), q020 (rule 46).
- These choices were made on golden v2, so v2 now overstates quality. The honest
  number comes from new questions not used for tuning.
