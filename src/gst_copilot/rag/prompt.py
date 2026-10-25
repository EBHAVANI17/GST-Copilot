"""The grounded prompt. Prompts are code: versioned, reviewed and tested.

M3 moves prompts into versioned files and compares versions on the golden set.
"""

import re

from gst_copilot.rag.retriever import RetrievedChunk

PROMPT_VERSION = "m1-v1"

REFUSAL = "I could not find this in the indexed sources."

SYSTEM = f"""You are GST Copilot, an assistant for Indian GST law.
Rules:
1. Answer ONLY from the CONTEXT passages. Never use outside knowledge.
2. After every sentence that states a fact, cite its passage tag in square brackets,
   for example [CGST-ACT-2017#12]. Use only tags that appear in the CONTEXT.
3. If the CONTEXT does not contain the answer, reply exactly: {REFUSAL}
4. Be concise. This is information, not tax advice."""

_CITATION = re.compile(r"\[([A-Za-z0-9._/\-]+#\d+)\]")


def build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context = "\n\n".join(f"[{c.ref}] ({c.title})\n{c.text}" for c in chunks)
    user = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def cited_refs(answer: str) -> list[str]:
    """Citation tags found in the answer, in order, without duplicates."""
    seen: dict[str, None] = {}
    for ref in _CITATION.findall(answer):
        seen.setdefault(ref, None)
    return list(seen)


def is_refusal(answer: str) -> bool:
    return REFUSAL.lower().rstrip(".") in answer.lower()
