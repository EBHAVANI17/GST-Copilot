"""M4.2: the matcher, its scoring and the CLI."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gst_copilot.recon import synth
from gst_copilot.recon.__main__ import main
from gst_copilot.recon.gstin import ALPHABET, check_char, is_valid
from gst_copilot.recon.matcher import Result, invoice_key, reconcile
from gst_copilot.recon.models import Expected, Invoice
from gst_copilot.recon.score import LabelScore, add_up, score
from gst_copilot.recon.score import main as score_main

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


@pytest.mark.parametrize("gstr2b_tax", ["180.00", "162.00"])  # same amounts, and not
def test_different_suppliers_are_never_paired(gstr2b_tax: str) -> None:
    # ADR 0022: the typo rule no longer needs equal amounts, so check it still never
    # pairs two suppliers whose GSTINs are 2 or more characters apart.
    for far in ("27AXQFU0939F1ZV", "27AAPFU0939F1YW", "29AAPFU0939F1ZX", "27BBBBB0000B1ZV"):
        assert sum(x != y for x, y in zip(far, GSTIN, strict=True)) >= 2
        twob = replace(G, supplier_gstin=far, igst=Decimal(gstr2b_tax))
        assert labels([B], [twob]) == {
            ("R1", None, "missing_in_2b"),
            (None, "B1", "missing_in_books"),
        }, far


def test_two_valid_gstins_are_never_one_character_apart() -> None:
    # Why a one-character difference can be treated as a typo: the check character
    # catches every single changed character, at every position.
    for gstin in (GSTIN, "29ABCCE1234F1Z" + check_char("29ABCCE1234F1Z")):
        assert is_valid(gstin)
        for i in range(15):
            for c in ALPHABET:
                if c != gstin[i]:
                    assert not is_valid(gstin[:i] + c + gstin[i + 1 :]), (gstin, i, c)


def test_a_pairing_problem_is_the_label_only_when_nothing_else_is_wrong() -> None:
    # ADR 0022, change (a): the more serious problem wins; the other stays in details.
    typo = replace(B, supplier_gstin="27AAPFU0939F1ZW")
    cut = replace(G, taxable_value=Decimal("900.00"), igst=Decimal("162.00"))
    cases = {
        "format+amount": ([B], [replace(cut, invoice_no="inv-26-27-42")], "amount_diff"),
        "format+period": (
            [B],
            [replace(G, invoice_no="INV-26-27-42", period="2026-05")],
            "period_diff",
        ),
        "typo+period": ([typo], [replace(G, period="2026-05")], "period_diff"),
        "typo+itc": ([typo], [replace(G, itc_available=False)], "itc_unavailable"),
        # change (b): the typo rule pairs these even though the amounts differ
        "typo+amount": ([typo], [cut], "amount_diff"),
    }
    for case, (books, twob, label) in cases.items():
        (r,) = reconcile(books, twob)
        assert (r.books_id, r.gstr2b_id, r.label) == ("R1", "B1", label), case
        assert {"invoice_no", "supplier_gstin"} & set(r.diffs), case


def test_all_differences_are_reported_not_only_the_label() -> None:
    (r,) = reconcile([B], [replace(G, invoice_no="INV-26-27-42", period="2026-05")])
    assert r.label == "period_diff"
    assert "period" in r.diffs and "invoice_no" in r.diffs


@pytest.mark.parametrize("hard", [False, True])
@pytest.mark.parametrize("seed", range(1, 11))
def test_finds_every_planted_problem(seed: int, hard: bool) -> None:
    books, twob, expected = synth.generate(seed=seed, invoices=150, hard=hard)
    s = score(reconcile(books, twob), expected)
    assert s["all"].correct == s["all"].expected == s["all"].predicted, seed


def test_add_up_sums_counts_per_label() -> None:
    one = score([Result("R1", "B1", "matched")], [Expected("R1", "B1", "matched")])
    two = score([Result("R1", None, "missing_in_2b")], [Expected("R1", "B1", "matched")])
    total = add_up([one, two])
    assert list(total) == ["matched", "missing_in_2b", "all"]
    assert total["matched"] == LabelScore(expected=2, predicted=1, correct=1)
    assert total["all"].precision == 0.5


def test_score_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert score_main(["--seeds", "1-2", "--invoices", "60", "--hard"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("hard data, seeds 1-2, 60 invoices each") and "| all |" in out


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
