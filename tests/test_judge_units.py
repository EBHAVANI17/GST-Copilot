"""LLM judge: prompt, robust parsing, errors."""

import json

import httpx
import pytest

from gst_copilot.evals.__main__ import _judge_passages
from gst_copilot.evals.judge import build_judge_messages, judge_answer, parse_judgement
from gst_copilot.rag.llm import OpenAICompatibleClient
from gst_copilot.rag.retriever import RetrievedChunk
from gst_copilot.rag.service import AskResult


@pytest.mark.parametrize(
    "raw",
    [
        '{"faithful": true, "correct": false, "explanation": "wrong limit"}',
        '```json\n{"faithful": true, "correct": false, "explanation": "wrong limit"}\n```',
        'Here is my review: {"faithful": "true", "correct": "False", "explanation": "wrong limit"}',
    ],
)
def test_parse_judgement_tolerates_formatting(raw: str) -> None:
    j = parse_judgement(raw)
    assert (j.faithful, j.correct, j.error) == (True, False, None)
    assert j.explanation == "wrong limit"


@pytest.mark.parametrize(
    "raw,error",
    [
        ("The answer looks fine.", "no JSON object"),
        ('{"faithful": true, "correct": }', "invalid JSON"),
        ('{"faithful": "maybe", "correct": true}', "missing true/false"),
    ],
)
def test_parse_judgement_reports_bad_output(raw: str, error: str) -> None:
    j = parse_judgement(raw)
    assert j.error is not None and error in j.error


def test_judge_prompt_contains_everything_and_reference_only_when_given() -> None:
    msgs = build_judge_messages("Q?", "No [A#1].", [("A#1", "law text")], reference="No, X.")
    user = msgs[1]["content"]
    assert "QUESTION:\nQ?" in user and "[A#1] law text" in user and "ANSWER:\nNo [A#1]." in user
    assert "REFERENCE ANSWER:\nNo, X." in user
    assert "wrong rule" in msgs[0]["content"]  # right verdict, wrong reason = not correct
    assert "REFERENCE" not in build_judge_messages("Q?", "A", [("A#1", "law")])[1]["content"]


async def test_judge_answer_end_to_end_and_on_server_error() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "judge-model" and body["max_tokens"] == 300
        content = '{"faithful": true, "correct": true, "explanation": "ok"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = OpenAICompatibleClient(
        "http://j/v1", "judge-model", max_tokens=300, transport=httpx.MockTransport(ok)
    )
    j = await judge_answer(client, "Q?", "A", [("A#1", "law")])
    assert (j.faithful, j.correct, j.error) == (True, True, None)

    down = OpenAICompatibleClient(
        "http://j/v1", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    j = await judge_answer(down, "Q?", "A", [("A#1", "law")])
    assert j.correct is None and j.error


def _chunk(i: int, text: str) -> RetrievedChunk:
    return RetrievedChunk("ACT", "t", "u", i, text, 0.5, "16")


def test_judge_gets_cited_passages_first() -> None:
    ctx = [_chunk(1, "one"), _chunk(2, "two"), _chunk(3, "three")]
    cited = AskResult("generated", "a", ctx, context=ctx, cited=["ACT#3"])
    assert _judge_passages(cited) == [("ACT#3", "three")]
    uncited = AskResult("generated", "a", ctx, context=ctx)
    assert [tag for tag, _ in _judge_passages(uncited)] == ["ACT#1", "ACT#2", "ACT#3"]
