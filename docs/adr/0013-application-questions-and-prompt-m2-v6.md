# 13. "Application" questions and prompt m2-v6

Date: 2026-10-26
Status: Accepted (m2-v6 kept opt-in; m2-v3 stays the default)

## Context

Real use (ask_logs, ADR 0012) produced three "not helpful" answers that no golden
question covered. Users describe their own facts ("my turnover is 15 lakh, do I
need to register?") and need the rule applied. The 3B model refused although the
rule was in the context, or inverted a rule. A new question type, `application`,
was added; q041-q043 come from those answers.

Prompt m2-v6 = m2-v3 + one rule: "If the question describes the user's own
situation, apply the rule from the CONTEXT to it: start with Yes, No or It depends,
then give the rule with its citation."

## Results (golden, 28 answerable incl. 3 application, qwen2.5:3b, mean of 3 runs)

| Metric | m2-v3 | m2-v6 |
|---|---|---|
| false_refusal | 0.179 | 0.083 |
| correct_refusal | 1.0 | 1.0 |
| keyword_recall | 0.396 | 0.42 |
| citation_accuracy | 0.781 | 0.85 |
| citation_section_accuracy | 0.76 | 0.678 |
| answers_without_citation | 0.275 | 0.313 |

Reading the three application answers under m2-v6:

- q041: correct verdict and reasoning; missed only an over-long keyword.
- q042: correct verdict ("No") for the wrong reason: it applied the 10 lakh special
  category limit and concluded 15 lakh does not meet it.
- q043: correct verdict, confused explanation.

## Decision

- m2-v3 stays the default. m2-v6 halves false refusals without hurting correct
  refusals, but it exposes the 3B model's reasoning errors as confident answers
  (q042), which is worse than a refusal for a tax question. Re-test m2-v6 with a
  stronger model.
- Neither keyword matching (misses correct paraphrases) nor a Yes/No verdict check
  (passes wrong reasoning) measures application answers. Next evaluation step: an
  LLM judge (a larger model, offline, where latency does not matter) grading each
  answer against a short reference answer, checked by hand on a sample.
- q041's keyword shortened to "received the goods" (still the law's exact words).
