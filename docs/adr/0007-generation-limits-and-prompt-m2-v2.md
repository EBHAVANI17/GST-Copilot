# 7. Generation limits, prompt m2-v2, and less noisy answer metrics

Date: 2026-10-25
Status: Accepted. m2-v2 rejected; m2-v3 is the default prompt (see Ablation)

## Context

With the reranker (ADR 0006), the right section was in the top 5 for every
answerable question, yet answers were still weak. Error analysis of one run:

- q001's answer was 2,563 characters (others 160-880). With 10 questions p95 is
  the slowest answer, so one runaway answer made p95 12.4 s.
- q004 was counted as a refusal although it was 623 characters long: it answered
  part of the question and then wrote the refusal sentence. `is_refusal` matched
  the sentence anywhere, so some "false refusals" were a measurement error.
- Two identical runs gave different answer metrics (false refusal 0.25 vs 0.125):
  local LLM output is not fully deterministic even at temperature 0.
- keyword_correctness requires every keyword, so 4 of 5 key phrases scores 0.

## Decisions

1. **`LLM_MAX_TOKENS=512`** on every call; answers cut off by it are flagged
   (`truncated`). Optional `LLM_FREQUENCY_PENALTY` (default 0, because legal
   answers repeat terms legitimately).
2. **Prompt m2-v2** (m1-v1 kept for comparison, `PROMPT_VERSION`): quote the law's
   exact words for conditions, numbers and lists; at most 6 points; answer the
   supported part and name the missing part ("The indexed sources do not cover:
   ..."); refuse only when nothing is relevant. Passage headers include the section.
3. **Refusal vs partial.** A refusal is an answer that is only the refusal sentence;
   an answer with facts plus a "not covered" note is `partial`.
4. **Less brittle, less noisy metrics:** `keyword_recall` (share of key phrases
   present) next to all-or-nothing keyword_correctness; per-question latency and
   answer length in the report; `--runs N` repeats the golden set and reports mean
   and min-max.

## Consequences

- Answers longer than 512 tokens are cut; `truncated_answers` shows how often.
- Results recorded before this change used the old refusal rule, so
  false_refusal is not directly comparable across the change. Compare m1-v1 and
  m2-v2 with the new rule (both are available).

## Results: m1-v1 vs m2-v2 (golden set v1, qwen2.5:3b, mean of 3 runs, new refusal rule)

| Metric | m1-v1 | m2-v2 |
|---|---|---|
| keyword_recall | 0.40 | 0.40 |
| answers_without_citation | 0.125 | 0.625 |
| citation_accuracy (document) | 0.857 | 0.667 |
| partial_answers | 0.125 | 0.667 |
| truncated_answers | 1 | 0 |
| false_refusal | 0.0 | 0.0 |
| p95 latency | 10.3 s | 6.6 s |

- With the new refusal rule, m1-v1's false refusals are 0.0 (previously 0.125-0.25):
  most earlier "false refusals" were partial answers counted as refusals.
- m2-v2 was shorter and faster but dropped citations, and appended "The indexed
  sources do not cover ..." to most answers even when nothing was missing.
- Mistake in method: m2-v2 changed four things at once, so the cause cannot be
  isolated. Follow-up: m2-v3 (+ at most 6 points), m2-v4 (+ the law's exact words),
  m2-v5 (+ section headers), each m1-v1 plus one change.
- q002 ("time limit for ITC", s.16(4)) was answered with the s.16(2) 180-day rule
  and a citation to a s.16 chunk. Document-level citation accuracy and
  section-level hit@k both counted it as correct. Added: `citation_section_accuracy`
  and `context_recall` (are the expected phrases in the retrieved passages at all).
  Both still accept any piece of a long section; sub-section granularity is future work.

## Ablation: one change each on top of m1-v1 (mean of 3 runs)

| Metric | m1-v1 | m2-v3 short | m2-v4 exact words | m2-v5 headers |
|---|---|---|---|---|
| keyword_recall | 0.40 | 0.506 | 0.431 | 0.375 |
| answers_without_citation | 0.125 | 0.125 | 0.0 | 0.125 |
| citation_section_accuracy | 0.857 | 0.857 | 0.875 | 0.857 |
| partial_answers | 0.167 | 0.0 | 0.0 | 0.25 |
| truncated_answers | 0.67 | 0 | 0 | 0 |
| p95 latency | 9.3 s | 5.8 s | 7.9 s | 5.0 s |

context_recall was 0.569 for all: the passages contain only 57% of the expected
phrases, a ceiling no prompt can pass. Decision: **m2-v3 is the default**. Section
headers (part of m2-v2) hurt on their own. Next: m2-v3 + exact words.

Measurement fix found here: keyword matching now ignores the "(180)" digits added
at index time, which had hidden phrases like "one hundred and eighty days" from
context_recall and keyword metrics. Numbers above were measured before this fix.
