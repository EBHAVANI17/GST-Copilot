"""The golden set: questions with known answers, stored as JSON Lines.

One JSON object per line:
{"id": "q001",
 "question": "...",
 "type": "lookup" | "date" | "multihop" | "application" | "unanswerable",
 # application = the user gives their own facts and the rule must be applied to them
 "expected_doc_ids": ["CGST-ACT-2017"],          # where the answer is (empty if unanswerable)
 "expected_sections": ["16"],                     # optional: section/rule numbers, no sub-section
                                                  # with several documents, name the document:
                                                  # ["CGST-ACT-2017:18", "CGST-RULES-2017:40"]
 "expected_keywords": ["registration", "20 lakh"], # words a correct answer must contain
 "notes": "why this question matters"}

Write each question from the official document itself, never from memory.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

QuestionType = Literal["lookup", "date", "multihop", "application", "unanswerable"]
TYPES = {"lookup", "date", "multihop", "application", "unanswerable"}


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

    @property
    def section_pairs(self) -> set[str]:
        """Expected (document, section) pairs as "DOC:SECTION" strings.

        "CGST-RULES-2017:40" names one document; a bare "16" applies to every
        expected document (fine when there is only one)."""
        pairs: set[str] = set()
        for s in self.expected_sections:
            if ":" in s:
                pairs.add(s)
            else:
                pairs.update(f"{d}:{s}" for d in self.expected_doc_ids)
        return pairs


def load_golden(path: Path) -> list[GoldenItem]:
    items: list[GoldenItem] = []
    ids: set[str] = set()
    # utf-8-sig: also accept files that Windows tools saved with a byte-order mark.
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
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
        for s in item.expected_sections:
            doc = s.split(":", 1)[0] if ":" in s else None
            if doc is not None and doc not in item.expected_doc_ids:
                raise ValueError(
                    f"line {n}: section {s!r} names a document not in expected_doc_ids"
                )
        if len(item.expected_doc_ids) > 1 and any(":" not in s for s in item.expected_sections):
            raise ValueError(
                f"line {n}: with several expected_doc_ids, write sections as 'DOC:NUMBER', "
                f"e.g. '{item.expected_doc_ids[0]}:{item.expected_sections[0].split(':')[-1]}'"
            )
        bad = [s for s in item.expected_sections if "(" in s]
        if bad:
            raise ValueError(f"line {n}: use section numbers only, e.g. '16' not {bad[0]!r}")
        ids.add(item.id)
        items.append(item)
    return items
