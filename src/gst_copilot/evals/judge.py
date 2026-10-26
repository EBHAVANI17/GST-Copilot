"""LLM-as-judge: grade answers that keyword matching cannot.

Keyword checks miss correct paraphrases, and a Yes/No check passes a right verdict
reached by wrong reasoning (ADR 0013, q042). So a larger model reads the question,
the law passages the answer was based on, the answer, and (if the golden item has
one) a short reference answer, and returns JSON:

    {"faithful": true|false, "correct": true|false, "explanation": "..."}

- faithful: every claim in the answer is supported by the passages.
- correct:  the answer actually answers the question: right verdict AND right reason.

The judge is a model too, so it can be wrong. Its explanations are stored with each
row, and it must agree with hand-graded answers before its numbers are trusted.
"""

import json
import re
from dataclasses import dataclass

from gst_copilot.rag.llm import LLMClient, LLMError

# j1 labelled passages [1], [2], ...: the judge could not match the answer's citation
# tags (e.g. [CGST-ACT-2017#105]) to passages and called correct citations wrong.
# j2 labels each passage with its real tag.
JUDGE_VERSION = "j2"

_SYSTEM = """You are a strict reviewer of answers about Indian GST law.
You get a QUESTION, LAW PASSAGES, an ANSWER and sometimes a REFERENCE ANSWER.
Each passage starts with its tag in square brackets, e.g. [CGST-ACT-2017#105]; the
ANSWER cites passages by these tags. A passage's first line names its section.
Judge only from the passages (and the reference, if given). Do not use outside knowledge.

Return ONLY a JSON object, nothing else:
{"faithful": true or false, "correct": true or false, "explanation": "one or two sentences"}

faithful = true only if every factual claim in the ANSWER is supported by the LAW PASSAGES.
correct = true only if the ANSWER gives the right conclusion for the QUESTION AND the
reason it gives is the right rule, applied correctly to the facts in the QUESTION.
A right conclusion reached with a wrong rule or wrong arithmetic is NOT correct."""


@dataclass(frozen=True)
class Judgement:
    faithful: bool | None
    correct: bool | None
    explanation: str
    error: str | None = None


def build_judge_messages(
    question: str, answer: str, passages: list[tuple[str, str]], reference: str = ""
) -> list[dict[str, str]]:
    """passages: (tag, text) pairs, e.g. ("CGST-ACT-2017#105", "Section 22. ...")."""
    law = "\n\n".join(f"[{tag}] {text}" for tag, text in passages)
    parts = [f"QUESTION:\n{question}", f"LAW PASSAGES:\n{law}"]
    if reference:
        parts.append(f"REFERENCE ANSWER:\n{reference}")
    parts.append(f"ANSWER:\n{answer}")
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]


_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_judgement(text: str) -> Judgement:
    """Read the judge's JSON, tolerating code fences or text around it."""
    m = _OBJECT.search(text)
    if not m:
        return Judgement(None, None, "", error="no JSON object in judge output")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return Judgement(None, None, "", error=f"invalid JSON: {exc.msg}")

    def as_bool(v: object) -> bool | None:
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.strip().lower() in {"true", "false"}:
            return v.strip().lower() == "true"
        return None

    faithful, correct = as_bool(data.get("faithful")), as_bool(data.get("correct"))
    error = None if faithful is not None and correct is not None else "missing true/false fields"
    return Judgement(faithful, correct, str(data.get("explanation", ""))[:500], error)


async def judge_answer(
    client: LLMClient,
    question: str,
    answer: str,
    passages: list[tuple[str, str]],
    reference: str = "",
) -> Judgement:
    try:
        completion = await client.complete(
            build_judge_messages(question, answer, passages, reference)
        )
    except LLMError as exc:
        return Judgement(None, None, "", error=str(exc))
    return parse_judgement(completion.text)
