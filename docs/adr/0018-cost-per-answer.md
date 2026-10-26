# 18. Measure tokens and cost per answer; prices are configuration

Date: 2026-10-26
Status: Accepted

## Context

Answers come from a local model (qwen2.5:3b on Ollama), so there is no bill per token.
The question a team would ask before going to production is still: what would this
cost on a hosted model, and what drives that cost?

## Decision

- Every eval and the usage report record prompt and completion tokens per answer and
  report a `cost` section: means, p95s and `<currency>_per_1000_answers`.
- Prices are settings (`LLM_PRICE_INPUT_PER_MTOK`, `LLM_PRICE_OUTPUT_PER_MTOK`,
  `LLM_PRICE_CURRENCY`), default 0 for the local model. They are never hard-coded:
  they change often and must be copied from the provider's official pricing page.
- `python -m gst_copilot.observe.cost <report.json> --input-price X --output-price Y`
  re-prices a saved eval report, so comparing providers needs no new LLM run.

## Results

Golden v2 (33 questions), prompt m2-v3, 10 rerank candidates, 8000-char context:

| Tokens per answer | Mean | p95 |
|---|---|---|
| prompt (question + law passages) | 2425 | 2701 |
| completion (the answer) | 115 | 339 |

Priced with OpenAI's official model pages (checked 2026-10-26, USD per 1M tokens):

| Model | Input | Output | USD per 1,000 answers |
|---|---|---|---|
| local qwen2.5:3b | 0 | 0 | 0 (hardware and electricity instead) |
| GPT-5 mini | 0.25 | 2.00 | 0.84 |
| GPT-5 nano (marked deprecated) | 0.05 | 0.40 | 0.17 |

## Consequences

- The prompt is about 95% of the tokens and, for GPT-5 mini, about 72% of the cost
  (2425 x 0.25 vs 115 x 2.00). The context size is the main lever for cost, the same
  lever as for prompt-reading latency, and the 5000-char cap that would cut it lost
  law text (ADR 0017). Cost per answer is low either way; quality is the constraint.
- Two runs with the same configuration gave first_token_p50 1378 and 593 ms, ttft_p50
  2330 and 1518 ms, false_refusal 0.143 and 0.179, keyword_recall 0.479 and 0.454.
  This confirms ADR 0017: single-run differences of this size are noise, and only
  large, repeated effects (like the rerank saving) count.
- Estimates assume the hosted model writes answers as long as the local one does; a
  different model gives a different completion length. Re-measure before relying on it.
