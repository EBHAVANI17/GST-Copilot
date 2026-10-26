"""Glossary query expansion."""

import pytest

from gst_copilot.rag.glossary import GLOSSARY, expand_query


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Can I claim ITC?", "Can I claim ITC (input tax credit)?"),
        ("can i claim itc?", "can i claim itc (input tax credit)?"),
        ("What must a bill show?", "What must a bill (invoice) show?"),
        ("What is input tax credit?", "What is input tax credit?"),  # nothing to add
        ("ITC (input tax credit) rules", "ITC (input tax credit) rules"),  # already there
        ("Exhibition of bills", "Exhibition of bills (invoice)"),
    ],
)
def test_expand_query(question: str, expected: str) -> None:
    assert expand_query(question) == expected


def test_whole_words_only() -> None:
    assert expand_query("profitability and wholesale") == "profitability and wholesale"


def test_glossary_entries_are_short_legal_terms() -> None:
    assert all(0 < len(v) <= 60 for v in GLOSSARY.values())
