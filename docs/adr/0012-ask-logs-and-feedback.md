# 12. Ask logs, feedback and usage reports

Date: 2026-10-26
Status: Accepted

## Context

M2 improved quality on golden questions written by the developer. Real users ask
differently, and nothing about real use was kept: a wrong answer could not be
studied afterwards.

## Decision

- Every `/ask` writes one row to `ask_logs` (migration 0005): question, query after
  glossary expansion, mode, answer, refusal/partial/truncated flags, cited and
  invented citations, retrieved passages with all ranks and scores, the passages
  the LLM saw, timings per stage, model, prompt version, token counts and the
  retrieval configuration.
- The response carries `ask_id`. `POST /feedback {ask_id, rating: 1 | -1, note}`
  stores helpful / not helpful.
- `python -m gst_copilot.observe --days 7` summarises usage: rates, latency per
  stage (p50/p95), feedback, and lists every "not helpful" answer and every
  refusal: the queue for new golden questions or corpus gaps.
- Logging never breaks answering: a failed write is logged and `ask_id` is null.
- The eval CLI does not log (it calls the service, not the API), so golden runs do
  not pollute usage data.

## Privacy

Questions may contain business or personal details. The log stays in the project's
own database, is never sent to third parties, and can be switched off with
`ASK_LOG_ENABLED=false`. Before any real deployment: a retention period (e.g. 90
days) with automatic deletion, and a notice to users that questions are stored.

## Consequences

- One extra INSERT per question (milliseconds).
- `ask_logs` grows without limit until retention is implemented.
