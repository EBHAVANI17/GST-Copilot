# 25. /ask safety: input limit, injection guarantees in code, model behaviour by eval

Date: 2026-10-30
Status: Accepted (code part); the safety eval set is the owner's to write

## Context

M5 asks for three things on `/ask`: input limits, prompt-injection tests, and refusal of
questions outside GST or asking for help to evade tax. The first two can be tested in
code with a fake model. The third is how a language model behaves, which unit tests
cannot show: it needs eval questions, written by the owner.

## Decision

**Input limit.** The question is trimmed, must have 3 characters or more and at most
`ASK_MAX_QUESTION_CHARS` (default 1000, the old fixed limit), else 422 with the reason.
Same for `/ask/stream`. Before, `"   "` passed the 3-character minimum.

**What the code guarantees, whatever the question or the model says** (`tests/test_safety.py`):

1. The question never reaches the system prompt, for every prompt version.
2. The question cannot add passages: the context block is built only from retrieved
   passages, and a fake `CONTEXT:` block in the question stays inside the question.
3. Instructions written inside a retrieved passage stay in the context, not the system
   prompt.
4. A citation tag the question makes up (`[FAKE-NOTICE#1]`) is reported in
   `invalid_citations`, never as cited, even when the model obeys the injection.

**Known gap (pinned by a test, not fixed):** if the question quotes a *real* tag next to
a false claim and the model repeats it, the tag check passes, because it only knows
the tag was shown to the model, not that the claim is in that passage. Fixing it
(e.g. removing tag-like text from questions, or checking claims against passages) is a
change to measure with an eval run first, so it is not done here.

**No prompt change.** Prompts are versioned and each change needs a golden run (ADR 0007).

**Owner's eval set.** `evals/safety.jsonl` is created empty, in the golden format with
`type: unanswerable` (the right answer is a refusal). Kinds to cover are listed in
`evals/README.md`. No questions were written by an agent.

## Consequences

- No numbers yet: refusal rates on the safety set are measured once the owner writes it.
- The 1000-character limit is unchanged by default; only now it is configurable and
  blank questions are refused.
