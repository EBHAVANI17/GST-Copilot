# 14. An LLM judge for answer quality

Date: 2026-10-26
Status: Accepted as an experimental triage tool; its numbers are not reported (see validation)

## Context

ADR 0013 showed two blind spots: keyword matching fails correct paraphrases (q041),
and a Yes/No check would pass a right verdict with wrong reasoning (q042). Grading
every answer by hand does not scale past a few dozen.

## Decision

- `python -m gst_copilot.evals <golden> --judge`: after all answers are generated, a
  judge model (`JUDGE_MODEL`, default qwen2.5:7b, same Ollama server) grades each
  answered question. Two passes, so the 3B and 7B models are not swapped in GPU
  memory per question.
- The judge sees the question, the passages the answer cited (else the passages it
  was shown; at most 4 / 6,000 characters), the answer, and the golden item's
  `reference_answer` if present. It returns JSON: `faithful` (every claim supported
  by the passages) and `correct` (right conclusion AND right rule, applied
  correctly). Prompt version `j1`.
- Report: `judge.correct` (over all answerable questions; refusals count as not
  correct), `judge.faithful` (over judged answers), `judge.judged`, `judge.errors`.
  Each row stores the judge's explanation for audit.
- Reference answers are written by a person from the law, never generated.

## Validation before use

The judge is itself a model. Before its numbers go in the README, compare it with
hand grades: q041 (correct), q042 (right verdict, wrong rule: must be judged NOT
correct) and q043 (muddled). Record the agreement here.

## Consequences

- Slow: one 7B call per answer (minutes for the golden set). Use `--runs 1` with
  `--judge`; it is for decisions, not every quick check.
- A judge from the same model family may share the answerer's blind spots. A
  stronger or different judge (hosted API) would be more independent.

## Validation, round 1 (judge j1, qwen2.5:7b; answers from m2-v6)

| Question | Hand grade | Judge verdict | Judge's reason |
|---|---|---|---|
| q041 | correct | correct | sound |
| q042 | not fully correct (gives "sells only within the State" as the reason; no special category caveat) | not correct | wrong: "cites #105 instead of section 22(1)", but #105 is section 22(1) |
| q043 | not correct (contradicts itself) | not correct, not faithful | wrong law: says the add-back applies "regardless of the reverse charge status" |

Verdicts agreed 3/3; the judge's reasoning was sound in 1/3. Not trusted for the
README yet. One cause was ours: j1 labelled passages [1], [2], so the judge could
not match citation tags to passages. j2 labels passages with their tags. Also seen:
with m2-v6, correct_refusal fell to 0.8 in this run (one out-of-scope question
answered), supporting m2-v3 as the default (ADR 0013).

Next: re-validate j2 on the same three, then grow hand grades to ~20 answers and
report the judge's agreement rate before using its numbers.

## Validation, round 2 (judge j2; the same answers, word for word, as round 1)

| Question | Strict hand grade | j1 | j2 |
|---|---|---|---|
| q041 | correct | correct, sound reason | correct, sound reason |
| q042 | not fully correct (borderline): right rule, but concludes from "sells only within the State" and omits the special category caveat | not correct, for a wrong reason | correct (lenient) |
| q043 | not correct (self-contradictory) | not correct, wrong law in its reason | not correct, sound reason |

j2 fixed the tag confusion (reasons sound in 2/3), but accepted the right-verdict,
wrong-reason answer that the judge exists to catch. With qwen2.5:7b, neither j1 nor
j2 is reliable for subtle legal reasoning; both catch unsupported claims.

Decision: the judge stays an experimental triage tool (it flags answers for human
review); judge.* numbers are not reported in the README. To trust it: a stronger
judge model (hosted, via JUDGE_BASE_URL) and about 20 hand-graded answers to
measure agreement.
