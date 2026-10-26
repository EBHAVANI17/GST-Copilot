"""Prompt versions, refusal vs partial answers, LLM limits, and eval aggregation."""

import json

import httpx
import pytest

from gst_copilot.evals.__main__ import _as_ranges, aggregate
from gst_copilot.evals.metrics import keyword_recall
from gst_copilot.rag.llm import OpenAICompatibleClient
from gst_copilot.rag.prompt import (
    NOT_COVERED,
    PROMPTS,
    REFUSAL,
    build_messages,
    is_partial,
    is_refusal,
)
from gst_copilot.rag.retriever import RetrievedChunk

CHUNK = RetrievedChunk("CGST-ACT-2017", "CGST Act", "u", 78, "(2) no credit unless", 0.8, "16")


def test_both_prompt_versions_exist_and_differ() -> None:
    assert set(PROMPTS) >= {"m1-v1", "m2-v2"}
    v1 = build_messages("q?", [CHUNK], "m1-v1")
    v2 = build_messages("q?", [CHUNK], "m2-v2")
    assert v1[0]["content"] != v2[0]["content"]
    assert "(CGST Act)" in v1[1]["content"] and "section 16" not in v1[1]["content"]
    assert "[CGST-ACT-2017#78] (CGST Act, section 16)" in v2[1]["content"]
    assert NOT_COVERED in v2[0]["content"] and REFUSAL in v2[0]["content"]


def test_unknown_prompt_version_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown prompt version"):
        build_messages("q?", [CHUNK], "m9-v9")


@pytest.mark.parametrize(
    "answer,refused,partial",
    [
        (REFUSAL, True, False),
        (f"{REFUSAL} [CGST-ACT-2017#78]", True, False),
        ("Credit needs a tax invoice [CGST-ACT-2017#78].", False, False),
        (
            "Credit needs a tax invoice and receipt of goods [CGST-ACT-2017#78]. "
            f"{NOT_COVERED}: the rate of tax.",
            False,
            True,
        ),
        (
            "Blocked credits include motor vehicles and food and beverages "
            f"[CGST-ACT-2017#90]. {REFUSAL}",
            False,
            True,
        ),
    ],
)
def test_refusal_versus_partial(answer: str, refused: bool, partial: bool) -> None:
    assert (is_refusal(answer), is_partial(answer)) == (refused, partial)


def test_keyword_recall_gives_partial_credit() -> None:
    text = "He must possess a tax invoice and must have received the goods."
    assert keyword_recall(text, ["tax invoice", "received the goods", "actually paid"]) == (
        pytest.approx(2 / 3)
    )
    assert keyword_recall(text, []) == 1.0


async def test_llm_sends_limits_and_reports_truncation() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "cut off"}, "finish_reason": "length"}],
            },
        )

    llm = OpenAICompatibleClient(
        "http://llm/v1",
        "m",
        max_tokens=256,
        frequency_penalty=0.2,
        transport=httpx.MockTransport(handler),
    )
    out = await llm.complete([{"role": "user", "content": "x"}])
    assert seen["max_tokens"] == 256 and seen["frequency_penalty"] == 0.2
    assert out.truncated and out.finish_reason == "length"


async def test_llm_omits_penalty_when_zero() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=httpx.MockTransport(handler))
    out = await llm.complete([{"role": "user", "content": "x"}])
    assert "frequency_penalty" not in seen and "max_tokens" not in seen
    assert not out.truncated


def test_aggregate_reports_mean_and_range() -> None:
    a = {"retrieval": {"hit@5": 1.0}, "answers": {"false_refusal": 0.25, "llm_errors": 0}}
    b = {"retrieval": {"hit@5": 1.0}, "answers": {"false_refusal": 0.125, "llm_errors": 0}}
    summary = aggregate([a, b])
    assert summary["answers"]["false_refusal"] == {"mean": 0.188, "min": 0.125, "max": 0.25}
    shown = _as_ranges(summary)
    assert shown["retrieval"]["hit@5"] == "1.0"
    assert shown["answers"]["false_refusal"] == "0.188 (0.125-0.25)"


def test_summary_warns_only_when_llm_calls_failed(capsys: pytest.CaptureFixture[str]) -> None:
    from gst_copilot.evals.__main__ import print_summary

    base = {"golden_file": "g", "questions": 0, "config": {"k": 5}, "rows": []}
    print_summary({**base, "answers": {"llm_errors": "0.0"}, "llm_errors_total": 0})
    assert "WARNING" not in capsys.readouterr().out
    print_summary({**base, "answers": {"llm_errors": 2}})
    assert "WARNING: 2 LLM call(s) failed" in capsys.readouterr().out


async def test_repeated_runs_share_one_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: --runs used a new event loop per run, which broke keep-alive
    connections to Ollama ("Event loop is closed")."""
    import asyncio
    from pathlib import Path

    from gst_copilot.evals import __main__ as cli

    loops: list[object] = []

    async def fake_run(golden: Path, k: int, retrieval_only: bool) -> dict[str, object]:
        loops.append(asyncio.get_running_loop())
        return {"retrieval": {}}

    class FakeEngine:
        async def dispose(self) -> None:
            loops.append("disposed")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "get_engine", FakeEngine)
    reports = await cli.run_many(Path("g"), 5, False, 3)
    assert len(reports) == 3
    assert loops[:3] == [asyncio.get_running_loop()] * 3 and loops[3] == "disposed"


def test_ablation_variants_differ_from_m1_v1_by_exactly_one_change() -> None:
    base = PROMPTS["m1-v1"]
    base_rules = set(base.system.splitlines())
    for name in ("m2-v3", "m2-v4"):
        variant = PROMPTS[name]
        added = set(variant.system.splitlines()) - base_rules
        # One new rule; the final "Be concise" rule is only renumbered (4. -> 5.).
        assert len(added) == 2, (name, added)
        assert not variant.section_headers
    assert PROMPTS["m2-v5"].system == base.system and PROMPTS["m2-v5"].section_headers


def test_section_headers_only_where_enabled() -> None:
    v1 = build_messages("q?", [CHUNK], "m1-v1")[1]["content"]
    v5 = build_messages("q?", [CHUNK], "m2-v5")[1]["content"]
    assert "[CGST-ACT-2017#78] (CGST Act)\n" in v1
    assert "[CGST-ACT-2017#78] (CGST Act, section 16)\n" in v5


def test_keyword_metrics_ignore_digits_added_at_index_time() -> None:
    from gst_copilot.evals.metrics import contains_all

    passage = "within a period of one hundred and eighty (180) days from the date"
    assert contains_all(passage, ["one hundred and eighty days"])
    assert keyword_recall(passage, ["one hundred and eighty days", "date"]) == 1.0
    # Real numbers in parentheses elsewhere are not touched.
    assert contains_all("section 16 (2) applies", ["section 16 (2)"])


def test_keyword_normalisation_keeps_subsection_numbers() -> None:
    from gst_copilot.evals.metrics import contains_all

    assert contains_all("under sub-section (2) of section 16", ["sub-section (2)"])
    assert not contains_all("under sub-section (2)", ["sub-section (3)"])
    assert contains_all("thirty (30) days", ["thirty days"])


def test_missing_keywords_lists_what_is_absent() -> None:
    from gst_copilot.evals.metrics import missing_keywords

    text = "tax invoice and one hundred and eighty (180) days"
    assert missing_keywords(text, ["tax invoice", "one hundred and eighty days", "September"]) == [
        "September"
    ]


@pytest.mark.parametrize(
    "answer",
    ["within thirty days", "within thirty (30) days", "within 30 days", "within Thirty days"],
)
def test_numbers_match_in_words_or_digits(answer: str) -> None:
    from gst_copilot.evals.metrics import contains_all

    assert contains_all(answer, ["thirty days"])


def test_digit_matching_does_not_confuse_different_numbers() -> None:
    from gst_copilot.evals.metrics import contains_all, keyword_recall

    assert not contains_all("within 60 days", ["thirty days"])
    assert keyword_recall("useful life of 5 years", ["useful life", "five years"]) == 1.0
    assert contains_all("180 days from the date", ["one hundred and eighty days"])
