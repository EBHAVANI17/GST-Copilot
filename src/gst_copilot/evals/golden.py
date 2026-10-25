"""The golden set: questions with known answers, stored as JSON Lines.

One JSON object per line:
{"id": "q001",
 "question": "...",
 "type": "lookup" | "date" | "multihop" | "unanswerable",
 "expected_doc_ids": ["CGST-ACT-2017"],          # where the answer is (empty if unanswerable)
 "expected_sections": ["16"],                     # optional: section/rule numbers, no sub-section
 "expected_keywords": ["registration", "20 lakh"], # words a correct answer must contain
 "notes": "why this question matters"}

Write each question from the official document itself, never from memory.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

QuestionType = Literal["lookup", "date", "multihop", "unanswerable"]
TYPES = {"lookup", "date", "multihop", "unanswerable"}


@dataclass(frozen=True)
class GoldenItem:
    id: str
    question: str
    type: QuestionType
    expected_doc_ids: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    expected_sections: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def answerable(self) -> bool:
        return self.type != "unanswerable"


def load_golden(path: Path) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    ids: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        item = GoldenItem(
            id=raw["id"],
            question=raw["question"],
            type=raw["type"],
            expected_doc_ids=raw.get("expected_doc_ids", []),
            expected_keywords=raw.get("expected_keywords", []),
            expected_sections=[str(s) for s in raw.get("expected_sections", [])],
            notes=raw.get("notes", ""),
        )
        if item.type not in TYPES:
            raise ValueError(f"line {n}: type must be one of {sorted(TYPES)}")
        if item.id in ids:
            raise ValueError(f"line {n}: duplicate id {item.id}")
        if item.answerable and not item.expected_doc_ids:
            raise ValueError(f"line {n}: answerable questions need expected_doc_ids")
        if not item.answerable and item.expected_doc_ids:
            raise ValueError(f"line {n}: unanswerable questions must not list expected_doc_ids")
        if not item.answerable and item.expected_sections:
            raise ValueError(f"line {n}: unanswerable questions must not list expected_sections")
        bad = [s for s in item.expected_sections if "(" in s]
        if bad:
            raise ValueError(f"line {n}: use section numbers only, e.g. '16' not {bad[0]!r}")
        ids.add(item.id)
        items.append(item)
    return items
