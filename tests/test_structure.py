"""Structure-aware chunking. The sample text mimics what pypdf extracts from the
CBIC PDFs: running chapter headers, amendment footnotes and '.—' headings.
The law wording is synthetic (Widget Levy Act), not real GST law."""

import re
from pathlib import Path

import pytest

from gst_copilot.ingest.structure import (
    Section,
    chunk_sections,
    split_sections,
    strip_noise,
    structured_chunks,
)

PAGE_HEADER = "CHAPTER V WIDGET CREDIT"
ACT = (Path(__file__).parent / "fixtures" / "widget_act.txt").read_text(encoding="utf-8")


def test_strip_noise_removes_headers_footnotes_and_markers() -> None:
    clean = strip_noise(ACT)
    assert PAGE_HEADER not in clean
    assert "Substituted w.e.f." not in clean
    assert "Act, 2022 (No. 6 of 2022)" not in clean
    assert "[thirtieth day\nof November] following" in clean
    assert "(3) Where the registered person has claimed depreciation" in clean


def test_strip_noise_keeps_lines_that_repeat_only_a_few_times() -> None:
    text = "(a) the same clause\n" * 5 + "Short line\n" * 3
    clean = strip_noise(text)
    assert clean.count("(a) the same clause") == 5  # clauses start with "(" and are kept
    assert clean.count("Short line") == 3


def test_split_sections_finds_headings_including_wrapped_and_inserted() -> None:
    sections = split_sections(strip_noise(ACT))
    numbered = [(s.number, s.heading) for s in sections if s.number]
    assert numbered == [
        ("16", "Eligibility and conditions for taking widget credit"),
        ("17", "Apportionment of credit and blocked credits"),
        ("17A", "Transfer of credit"),
    ]
    # The table of contents has no ".—", so it stays in the preamble.
    assert sections[0].number is None and "ARRANGEMENT OF SECTIONS" in sections[0].body
    s16 = sections[1]
    assert s16.body.startswith("(1) Every registered person")
    assert "(4) A registered person" in s16.body


def test_split_sections_without_headings_returns_one_block() -> None:
    assert split_sections("Circular No. 1. Some guidance text.") == [
        Section(None, None, "Circular No. 1. Some guidance text.")
    ]
    assert split_sections("   ") == []


def test_each_piece_has_a_context_header_and_section_number() -> None:
    pieces = structured_chunks(ACT, size=1200, overlap=200, doc_type="act")
    by_section = {p.section: p.text for p in pieces}
    assert by_section["16"].startswith(
        "Section 16. Eligibility and conditions for taking widget credit\n(1)"
    )
    assert by_section["17A"].startswith("Section 17A. Transfer of credit\n")
    assert "17" in by_section and None in by_section  # preamble kept, without a section


def test_long_section_splits_at_subsections_and_keeps_the_header() -> None:
    pieces = structured_chunks(ACT, size=200, overlap=40, doc_type="act")
    s16 = [p for p in pieces if p.section == "16"]
    assert len(s16) >= 2
    header = "Section 16. Eligibility and conditions for taking widget credit"
    assert all(p.text.startswith(header) for p in s16)
    # s.16(3) is now in a small piece of its own section, not diluted by s.17.
    piece3 = next(p for p in s16 if "(3) Where" in p.text)
    assert "Apportionment" not in piece3.text
    assert all(len(p.text) <= 200 + 5 for p in s16)


def test_rules_use_the_rule_label() -> None:
    sections = [Section("36", "Documentary requirements", "(1) Credit on an invoice.")]
    [piece] = chunk_sections(sections, size=500, overlap=50, doc_type="rule")
    assert piece.text == "Rule 36. Documentary requirements\n(1) Credit on an invoice."


@pytest.mark.parametrize("size", [60, 120, 400])
def test_no_text_is_lost(size: int) -> None:
    clean = strip_noise(ACT)
    pieces = structured_chunks(ACT, size=size, overlap=10, doc_type="act")
    joined = " ".join(p.text for p in pieces)
    # Heading punctuation (".—") is removed on purpose; every real word must survive.
    for word in set(re.findall(r"[A-Za-z]{3,}", clean)):
        assert word in joined, word
