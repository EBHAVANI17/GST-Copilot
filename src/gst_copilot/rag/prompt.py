"""The grounded prompt. Prompts are code: versioned, reviewed and tested.

Each version stays in PROMPTS so any two can be compared on the golden set
(PROMPT_VERSION=...). Never edit a released version: add a new one.

History (golden set v1, qwen2.5:3b, 3 runs each; see ADR 0007):
- m1-v1: baseline.
- m2-v2: four changes at once (quote, at most 6 points, partial-answer rule,
  section headers). Shorter and faster, but answers without citation rose from
  0.125 to 0.625 and the model added "not covered" to most answers. Kept for the
  record; not used.
- m2-v3, m2-v4, m2-v5: m1-v1 plus exactly ONE change each, so each change can be
  measured on its own (an ablation). m2-v3 won and became the default.
- m2-v6: m2-v3 plus ONE rule for "application" questions (the user's own facts).
  Real use (ask_logs) showed false refusals on "my turnover is 15 lakh, do I need
  to register?": the rule ("exceeds twenty lakh rupees") was in the context, but
  the model read "does not contain the answer" literally and refused.
- m2-v7: m2-v6 plus rule distinguishing preconditions from reversal consequences
  (e.g. 180-day failure to pay triggers output tax add-back, not an initial claim condition).
"""

import re
from dataclasses import dataclass

from gst_copilot.config import get_settings
from gst_copilot.rag.retriever import RetrievedChunk

REFUSAL = "I could not find this in the indexed sources."
NOT_COVERED = "The indexed sources do not cover"


@dataclass(frozen=True)
class Prompt:
    system: str
    section_headers: bool = False  # passage header says "(title, section 16)"


_M1_V1 = f"""You are GST Copilot, an assistant for Indian GST law.
Rules:
1. Answer ONLY from the CONTEXT passages. Never use outside knowledge.
2. After every sentence that states a fact, cite its passage tag in square brackets,
   for example [CGST-ACT-2017#12]. Use only tags that appear in the CONTEXT.
3. If the CONTEXT does not contain the answer, reply exactly: {REFUSAL}
4. Be concise. This is information, not tax advice."""

_M2_V2 = f"""You are GST Copilot, an assistant for Indian GST law.

Rules:
1. Use ONLY the CONTEXT passages. Never use outside knowledge, even if you know the answer.
2. Cite the passage tag in square brackets after every fact, e.g. [CGST-ACT-2017#12].
   Use only tags shown in the CONTEXT.
3. Quote the law's exact words for conditions, numbers, time limits and lists.
   Do not paraphrase them.
4. Answer in at most 6 short points. Do not repeat yourself.
5. If the CONTEXT answers only part of the question, answer that part, then write:
   "{NOT_COVERED}: <the missing part>."
6. If the CONTEXT contains nothing relevant, reply exactly: {REFUSAL}
7. This is information, not tax advice."""

# m1-v1 + one rule: short answers.
_M2_V3 = f"""You are GST Copilot, an assistant for Indian GST law.
Rules:
1. Answer ONLY from the CONTEXT passages. Never use outside knowledge.
2. After every sentence that states a fact, cite its passage tag in square brackets,
   for example [CGST-ACT-2017#12]. Use only tags that appear in the CONTEXT.
3. If the CONTEXT does not contain the answer, reply exactly: {REFUSAL}
4. Answer in at most 6 short points. Do not repeat yourself.
5. Be concise. This is information, not tax advice."""

# m1-v1 + one rule: the law's exact words.
_M2_V4 = f"""You are GST Copilot, an assistant for Indian GST law.
Rules:
1. Answer ONLY from the CONTEXT passages. Never use outside knowledge.
2. After every sentence that states a fact, cite its passage tag in square brackets,
   for example [CGST-ACT-2017#12]. Use only tags that appear in the CONTEXT.
3. If the CONTEXT does not contain the answer, reply exactly: {REFUSAL}
4. Use the law's exact words for conditions, numbers and time limits.
5. Be concise. This is information, not tax advice."""

# m2-v3 + one rule: apply the rule to the user's own facts.
_M2_V6 = f"""You are GST Copilot, an assistant for Indian GST law.
Rules:
1. Answer ONLY from the CONTEXT passages. Never use outside knowledge.
2. After every sentence that states a fact, cite its passage tag in square brackets,
   for example [CGST-ACT-2017#12]. Use only tags that appear in the CONTEXT.
3. If the CONTEXT does not contain the answer, reply exactly: {REFUSAL}
4. Answer in at most 6 short points. Do not repeat yourself.
5. If the question describes the user's own situation, apply the rule from the CONTEXT
   to it: start with Yes, No or It depends, then give the rule with its citation.
6. Be concise. This is information, not tax advice."""

# m2-v6 + one rule: distinguish preconditions from reversal consequences.
_M2_V7 = f"""You are GST Copilot, an assistant for Indian GST law.
Rules:
1. Answer ONLY from the CONTEXT passages. Never use outside knowledge.
2. After every sentence that states a fact, cite its passage tag in square brackets,
   for example [CGST-ACT-2017#12]. Use only tags that appear in the CONTEXT.
3. If the CONTEXT does not contain the answer, reply exactly: {REFUSAL}
4. Answer in at most 6 short points. Do not repeat yourself.
5. Distinguish conditions from consequences: state requirements to claim credit first.
   Describe reversal or add-back rules (such as failure to pay within 180 days) as
   consequences of subsequent non-payment, not conditions for claiming credit.
6. If the question describes the user's own situation, apply the rule from the CONTEXT
   to it: start with Yes, No or It depends, then give the rule with its citation.
7. Be concise. This is information, not tax advice."""

PROMPTS: dict[str, Prompt] = {
    "m1-v1": Prompt(_M1_V1),
    "m2-v2": Prompt(_M2_V2, section_headers=True),
    "m2-v3": Prompt(_M2_V3),
    "m2-v4": Prompt(_M2_V4),
    # m1-v1 text, one change: passage headers name the section.
    "m2-v5": Prompt(_M1_V1, section_headers=True),
    "m2-v6": Prompt(_M2_V6),
    "m2-v7": Prompt(_M2_V7),
}

_CITATION = re.compile(r"\[([A-Za-z0-9._/\-]+#\d+)\]")


def build_messages(
    question: str, chunks: list[RetrievedChunk], version: str | None = None
) -> list[dict[str, str]]:
    version = version or get_settings().prompt_version
    if version not in PROMPTS:
        raise ValueError(f"unknown prompt version {version!r}; known: {sorted(PROMPTS)}")
    prompt = PROMPTS[version]
    context = "\n\n".join(
        f"[{c.ref}] {_where(c) if prompt.section_headers else f'({c.title})'}\n{c.text}"
        for c in chunks
    )
    user = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"
    return [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]


def _where(c: RetrievedChunk) -> str:
    return f"({c.title}, section {c.section})" if c.section else f"({c.title})"


def cited_refs(answer: str) -> list[str]:
    """Citation tags found in the answer, in order, without duplicates."""
    seen: dict[str, None] = {}
    for ref in _CITATION.findall(answer):
        seen.setdefault(ref, None)
    return list(seen)


def is_refusal(answer: str) -> bool:
    """A full refusal: the answer is (essentially) only the refusal sentence.

    An answer that gives facts and also says something was not found is partial,
    not a refusal. m1-v1 counted any answer containing the sentence as refused.
    """
    rest = answer.lower().replace(REFUSAL.lower().rstrip("."), "")
    rest = _CITATION.sub("", rest)
    has_sentence = REFUSAL.lower().rstrip(".") in answer.lower()
    return has_sentence and len(re.sub(r"[\W_]+", "", rest)) < 40


def is_partial(answer: str) -> bool:
    """Answers part of the question and says what the sources don't cover."""
    lowered = answer.lower()
    says_missing = NOT_COVERED.lower() in lowered or REFUSAL.lower().rstrip(".") in lowered
    return says_missing and not is_refusal(answer)
