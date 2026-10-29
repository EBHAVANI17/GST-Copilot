"""M4.2: the matcher, its scoring and the CLI."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gst_copilot.recon import synth
from gst_copilot.recon.__main__ import main
from gst_copilot.recon.matcher import Result, invoice_key, reconcile
from gst_copilot.recon.models import Expected, Invoice
from gst_copilot.recon.score import score

GSTIN = "27AAPFU0939F1ZV"  # format example from GST documentation
B = Invoice("R1", "books", GSTIN, "Demo (synthetic)", "INV/26-27/0042", date(2026, 4, 10),
            Decimal("1000.00"), igst=Decimal("180.00"), period="2026-04")  # fmt: skip
G = replace(B, row_id="B1", source="gstr2b")


def labels(books: list[Invoice], twob: list[Invoice]) -> set[tuple[str | None, str | None, str]]:
    return {(r.books_id, r.gstr2b_id, r.label) for r in reconcile(books, twob)}


@pytest.mark.parametrize(
    "raw", ["INV/26-27/0042", "inv/26-27/0042", "INV-26-27-42", "INV 26 27 000042"]
)
def test_invoice_key_ignores_case_separators_and_leading_zeros(raw: str) -> None:
    assert invoice_key(raw) == "INV|26|27|42"


def test_invoice_key_keeps_different_numbers_apart() -> None:
    assert invoice_key("INV/26-27/0042") != invoice_key("INV/26-27/0420")
    assert invoice_key("0") == "0"


def test_tolerance_boundary_is_inclusive() -> None:
    assert labels([B], [replace(G, taxable_value=Decimal("1001.00"))]) == {("R1", "B1", "matched")}
    assert labels([B], [replace(G, taxable_value=Decimal("1001.01"))]) == {
        ("R1", "B1", "amount_diff")
    }
    assert labels([B], [replace(G, igst=Decimal("178.50"))]) == {("R1", "B1", "amount_diff")}


def test_each_rule_on_one_pair() -> None:
    cases = {
        "itc_unavailable": ([B], [replace(G, itc_available=False)]),
        "period_diff": ([B], [replace(G, period="2026-05")]),
        "invoice_no_format": ([B], [replace(G, invoice_no="inv-26-27-42")]),
        "gstin_typo": ([replace(B, supplier_gstin="27AAPFU0939F1ZW")], [G]),
        "tax_type": (
            [B],
            [replace(G, igst=Decimal("0"), cgst=Decimal("90.00"), sgst=Decimal("90.00"))],
        ),
    }
    for label, (books, twob) in cases.items():
        assert labels(books, twob) == {("R1", "B1", label)}, label


def test_left_over_rows_and_duplicates() -> None:
    other = replace(G, row_id="B2", invoice_no="INV/26-27/0099")
    dup = replace(B, row_id="R2")
    assert labels([B, dup], [G, other]) == {
        ("R1", "B1", "matched"),
        ("R2", None, "duplicate_in_books"),
        (None, "B2", "missing_in_books"),
    }
    assert labels([B], []) == {("R1", None, "missing_in_2b")}


def test_a_different_supplier_with_the_same_number_is_not_a_typo() -> None:
    # Two characters differ: two different suppliers, not a typing mistake.
    far = replace(G, supplier_gstin="27AAPFU0939F1ZV".replace("AAP", "AXQ"))
    assert labels([B], [far]) == {("R1", None, "missing_in_2b"), (None, "B1", "missing_in_books")}


def test_all_differences_are_reported_not_only_the_label() -> None:
    (r,) = reconcile([B], [replace(G, invoice_no="INV-26-27-42", period="2026-05")])
    assert r.label == "invoice_no_format"
    assert "period" in r.diffs and "invoice_no" in r.diffs


@pytest.mark.parametrize("seed", range(1, 11))
def test_finds_every_planted_problem(seed: int) -> None:
    books, twob, expected = synth.generate(seed=seed, invoices=150)
    s = score(reconcile(books, twob), expected)
    assert s["all"].correct == s["all"].expected == s["all"].predicted, seed


def test_score_counts_wrong_pairs_and_wrong_labels() -> None:
    truth = [Expected("R1", "B1", "matched"), Expected("R2", None, "missing_in_2b")]
    pred = [Result("R1", "B1", "amount_diff"), Result("R2", None, "missing_in_2b")]
    s = score(pred, truth)
    assert (s["matched"].recall, s["amount_diff"].precision) == (0.0, 0.0)
    assert s["missing_in_2b"].precision == 1.0 and s["all"].correct == 1


def test_cli_on_a_synthetic_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    synth.main(["--out", str(tmp_path), "--invoices", "60", "--seed", "3"])
    capsys.readouterr()
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Score against expected.csv" in out and "| all |" in out
    lines = (tmp_path / "reconciliation.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "books_id,gstr2b_id,label,details" and len(lines) > 60
