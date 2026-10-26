"""PDF text repair. Broken phrases are the real ones from the CBIC CGST Act PDF."""

import pytest

from gst_copilot.ingest.repair import repair_text
from gst_copilot.ingest.structure import structured_chunks

# Realistic word frequencies: common words appear many times, intact.
CORPUS = (
    "The date of the invoice shall be issued under the Act, and the details of goods "
    "are available to the registered person. "
) * 40 + "Credit is taken into account in the period to pay tax. " * 10


def fix(fragment: str) -> str:
    return repair_text(CORPUS + fragment)[len(CORPUS) :]


@pytest.mark.parametrize(
    "broken,fixed",
    [
        ("date of issue o f invoice", "date of issue of invoice"),
        ("it sh all be deemed", "it shall be deemed"),
        ("received by t he supplier", "received by the supplier"),
        ("und er the Act", "under the Act"),
        ("det ails and availab le", "details and available"),
        ("the Income -\ntax Act", "the Income-tax Act"),
        ("under sub -section (1)", "under sub-section (1)"),
        ("financial year 2017 -18", "financial year 2017-18"),
    ],
)
def test_repairs_broken_pdf_words(broken: str, fixed: str) -> None:
    assert fix(broken) == fixed


@pytest.mark.parametrize(
    "fine",
    [
        "taken in to account",  # both "in" and "to" are common words alone: keep
        "a person in the State",
        "goods - including services",  # a real dash with spaces on both sides
        "Rule 36 (4) applies",
    ],
)
def test_leaves_correct_text_alone(fine: str) -> None:
    assert fix(fine) == fine


def test_rare_joined_words_are_not_invented() -> None:
    # "xy" never appears intact, so "x y" must not be joined.
    assert repair_text("x y " + "plain words " * 50) == "x y " + "plain words " * 50


def test_structured_chunks_apply_the_repair() -> None:
    text = CORPUS + "\n\n16. Eligibility.—(1) Credit on the date of issue o f invoice."
    pieces = structured_chunks(text, 1200, 200, "act")
    s16 = next(p for p in pieces if p.section == "16")
    assert "date of issue of invoice" in s16.text
