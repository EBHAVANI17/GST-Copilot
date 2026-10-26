"""Golden-set linting and DOC:SECTION entries."""

import json
from pathlib import Path

import pytest

from gst_copilot.evals.check import Corpus, check_item
from gst_copilot.evals.golden import GoldenItem, load_golden

CORPUS = Corpus(
    sections={
        "ACT:18": "within thirty (30) days ... inputs held in stock",
        "ACT:40": "first return",
        "RULES:40": "declaration in FORM GST ITC-01",
        "RULES:18": "display of registration certificate",
    },
    documents={"ACT": "...", "RULES": "..."},
)


def item(**kw: object) -> GoldenItem:
    base: dict[str, object] = {"id": "x", "question": "q?", "type": "lookup"}
    return GoldenItem(**{**base, **kw})  # type: ignore[arg-type]


def test_qualified_sections_name_one_document_each() -> None:
    i = item(expected_doc_ids=["ACT", "RULES"], expected_sections=["ACT:18", "RULES:40"])
    assert i.section_pairs == {"ACT:18", "RULES:40"}  # not ACT:40 or RULES:18
    assert item(expected_doc_ids=["ACT"], expected_sections=["16"]).section_pairs == {"ACT:16"}


def test_check_passes_when_keywords_are_in_the_expected_sections() -> None:
    i = item(
        expected_doc_ids=["ACT", "RULES"],
        expected_sections=["ACT:18", "RULES:40"],
        expected_keywords=["thirty days", "FORM GST ITC-01"],
    )
    assert check_item(i, CORPUS) == []


def test_check_reports_wrong_section_missing_section_and_invented_phrase() -> None:
    wrong = item(expected_doc_ids=["ACT"], expected_sections=["40"], expected_keywords=["stock"])
    assert check_item(wrong, CORPUS) == [
        "keyword 'stock' not in expected section(s); found in ACT:18"
    ]
    missing = item(expected_doc_ids=["ACT"], expected_sections=["99"], expected_keywords=[])
    assert check_item(missing, CORPUS) == ["section ACT:99 not found (check the number)"]
    invented = item(expected_doc_ids=["ACT"], expected_sections=["18"], expected_keywords=["zz"])
    assert check_item(invented, CORPUS) == [
        "keyword 'zz' not found anywhere: copy it from the text"
    ]


def test_unanswerable_items_are_not_checked() -> None:
    assert check_item(item(type="unanswerable"), CORPUS) == []


def _write(tmp_path: Path, row: dict[str, object]) -> Path:
    p = tmp_path / "g.jsonl"
    p.write_text(json.dumps({"id": "a", "question": "q?", "type": "multihop", **row}) + "\n")
    return p


def test_multi_document_items_must_qualify_sections(tmp_path: Path) -> None:
    bare = {"expected_doc_ids": ["ACT", "RULES"], "expected_sections": ["18", "40"]}
    with pytest.raises(ValueError, match="DOC:NUMBER"):
        load_golden(_write(tmp_path, bare))
    unknown = {"expected_doc_ids": ["ACT"], "expected_sections": ["RULES:40"]}
    with pytest.raises(ValueError, match="not in expected_doc_ids"):
        load_golden(_write(tmp_path, unknown))
    ok = {"expected_doc_ids": ["ACT", "RULES"], "expected_sections": ["ACT:18", "RULES:40"]}
    assert load_golden(_write(tmp_path, ok))[0].section_pairs == {"ACT:18", "RULES:40"}
