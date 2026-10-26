"""Tokens and money per answer.

The answering model is local (Ollama), so there is no bill per token. To compare with
a hosted model, count the tokens a real workload uses and price them:

    cost of one answer = prompt_tokens * input price + completion_tokens * output price

Prices are per million tokens and change often, so they are never hard-coded: copy
them from the provider's official pricing page into LLM_PRICE_INPUT_PER_MTOK /
LLM_PRICE_OUTPUT_PER_MTOK, or re-price a saved eval report without re-running it:

    python -m gst_copilot.observe.cost reports/eval-XXXX.json --input-price 0.1 --output-price 0.4
"""

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gst_copilot.config import get_settings
from gst_copilot.evals.metrics import percentile


@dataclass(frozen=True)
class Prices:
    input_per_mtok: float
    output_per_mtok: float
    currency: str = "USD"


def prices_from_settings() -> Prices:
    s = get_settings()
    return Prices(s.llm_price_input_per_mtok, s.llm_price_output_per_mtok, s.llm_price_currency)


def token_summary(pairs: Iterable[tuple[int | None, int | None]]) -> dict[str, float]:
    """(prompt_tokens, completion_tokens) per answer -> means and p95s.
    Answers without token counts (retrieval-only, provider did not report) are skipped."""
    counted = [(p, c) for p, c in pairs if p is not None and c is not None]
    if not counted:
        return {}
    prompts = [float(p) for p, _ in counted]
    completions = [float(c) for _, c in counted]
    return {
        "answers_counted": len(counted),
        "prompt_tokens_mean": round(sum(prompts) / len(prompts)),
        "completion_tokens_mean": round(sum(completions) / len(completions)),
        "prompt_tokens_p95": percentile(prompts, 95),
        "completion_tokens_p95": percentile(completions, 95),
    }


def cost_per_1000(summary: dict[str, float], prices: Prices) -> float | None:
    """Expected cost of 1,000 answers like these, at the given prices."""
    if not summary:
        return None
    per_answer = (
        summary["prompt_tokens_mean"] * prices.input_per_mtok
        + summary["completion_tokens_mean"] * prices.output_per_mtok
    ) / 1_000_000
    return round(per_answer * 1000, 4)


def cost_section(pairs: Iterable[tuple[int | None, int | None]], prices: Prices) -> dict[str, Any]:
    summary = token_summary(pairs)
    if not summary:
        return {}
    return {**summary, f"{prices.currency}_per_1000_answers": cost_per_1000(summary, prices)}


def reprice_report(path: Path, prices: Prices) -> dict[str, Any]:
    """Cost section for a saved eval report, at other prices."""
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    return cost_section(
        ((r.get("prompt_tokens"), r.get("completion_tokens")) for r in rows), prices
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Price the token usage of a saved eval report.")
    p.add_argument("report", type=Path)
    p.add_argument("--input-price", type=float, required=True, help="per million tokens")
    p.add_argument("--output-price", type=float, required=True, help="per million tokens")
    p.add_argument("--currency", default="USD")
    args = p.parse_args(argv)
    section = reprice_report(
        args.report, Prices(args.input_price, args.output_price, args.currency)
    )
    if not section:
        print("No answers with token counts in this report (retrieval-only run?).")
        return 1
    print("| Metric | Value |\n|---|---|")
    for name, value in section.items():
        print(f"| {name} | {value} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
