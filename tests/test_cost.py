"""Token counts and cost estimates (observe/cost.py)."""

import json
from pathlib import Path

import pytest

from gst_copilot.observe.cost import (
    Prices,
    cost_per_1000,
    cost_section,
    main,
    reprice_report,
    token_summary,
)


def test_summary_skips_answers_without_counts() -> None:
    s = token_summary([(2000, 300), (3000, 100), (None, None), (1000, None)])
    assert s["answers_counted"] == 2
    assert (s["prompt_tokens_mean"], s["completion_tokens_mean"]) == (2500, 200)
    assert token_summary([(None, None)]) == {}


def test_cost_per_1000_answers() -> None:
    summary = {"prompt_tokens_mean": 2500, "completion_tokens_mean": 200}
    # 2500 * 0.10 + 200 * 0.40 = 330 per million answers' worth -> 0.33 per 1000 answers
    assert cost_per_1000(summary, Prices(0.10, 0.40)) == pytest.approx(0.33)
    assert cost_per_1000(summary, Prices(0, 0)) == 0  # local model
    assert cost_per_1000({}, Prices(1, 1)) is None


def test_cost_section_names_the_currency() -> None:
    section = cost_section([(1000, 100)], Prices(1.0, 2.0, "INR"))
    assert section["INR_per_1000_answers"] == pytest.approx(1.2)
    assert cost_section([], Prices(1, 1)) == {}


def test_reprice_a_saved_eval_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "eval.json"
    rows = [{"prompt_tokens": 2000, "completion_tokens": 200}, {"prompt_tokens": None}]
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    assert reprice_report(path, Prices(0.5, 1.5))["USD_per_1000_answers"] == pytest.approx(1.3)
    assert main([str(path), "--input-price", "0.5", "--output-price", "1.5"]) == 0
    assert "| USD_per_1000_answers | 1.3 |" in capsys.readouterr().out
