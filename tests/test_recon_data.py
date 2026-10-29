"""M4.1: invoice model, CSV files, GSTIN check character and the synthetic generator."""

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from gst_copilot.recon import synth
from gst_copilot.recon.csvio import (
    BOOKS_COLUMNS,
    read_expected,
    read_invoices,
    write_expected,
    write_invoices,
)
from gst_copilot.recon.gstin import check_char, is_valid


def test_gstin_check_character() -> None:
    # The format example used in GST documentation.
    assert check_char("27AAPFU0939F1Z") == "V" and is_valid("27AAPFU0939F1ZV")
    assert not is_valid("27AAPFU0939F1ZA")  # wrong check character
    assert not is_valid("27AAPFU0939F1Z")  # too short


def test_fake_gstins_are_valid_and_a_typo_never_is() -> None:
    import random

    rng = random.Random(3)
    for _ in range(200):
        g = synth.fake_gstin(rng, "29")
        assert is_valid(g) and g.startswith("29")
        # One changed character always breaks the check character.
        assert not is_valid(synth.gstin_typo(rng, g))


def test_same_seed_same_data_other_seed_other_data() -> None:
    assert synth.generate(seed=5, invoices=50) == synth.generate(seed=5, invoices=50)
    assert synth.generate(seed=5, invoices=50) != synth.generate(seed=6, invoices=50)


def test_every_row_has_exactly_one_truth_and_the_mix_is_planted() -> None:
    books, gstr2b, expected = synth.generate(seed=1, invoices=200)
    book_ids = [e.books_id for e in expected if e.books_id]
    twob_ids = [e.gstr2b_id for e in expected if e.gstr2b_id]
    assert sorted(book_ids) == sorted(r.row_id for r in books)
    assert sorted(twob_ids) == sorted(r.row_id for r in gstr2b)
    assert len(set(book_ids)) == len(book_ids) and len(set(twob_ids)) == len(twob_ids)
    counts = Counter(e.label for e in expected)
    for label, share in synth.MIX.items():
        assert counts[label] == round(share * 200), label
    # Each duplicate adds one "matched" pair and one extra book row.
    assert (
        counts["matched"]
        == 200 - sum(round(s * 200) for s in synth.MIX.values()) + counts["duplicate_in_books"]
    )


def test_planted_problems_look_like_their_label() -> None:
    books, gstr2b, expected = synth.generate(seed=2, invoices=300)
    b = {r.row_id: r for r in books}
    g = {r.row_id: r for r in gstr2b}
    one = Decimal("1.00")
    for e in expected:
        if e.books_id is None or e.gstr2b_id is None:
            continue
        x, y = b[e.books_id], g[e.gstr2b_id]
        if e.label == "matched":
            assert x.supplier_gstin == y.supplier_gstin and x.invoice_no == y.invoice_no
            assert abs(x.taxable_value - y.taxable_value) <= one and y.itc_available
        elif e.label == "amount_diff":
            assert abs(x.taxable_value - y.taxable_value) > one
        elif e.label == "invoice_no_format":
            assert x.invoice_no != y.invoice_no
        elif e.label == "period_diff":
            assert x.period != y.period
        elif e.label == "gstin_typo":
            assert x.supplier_gstin != y.supplier_gstin and not is_valid(x.supplier_gstin)
        elif e.label == "tax_type":
            assert x.total_tax == y.total_tax and (x.igst > 0) != (y.igst > 0)
        elif e.label == "itc_unavailable":
            assert not y.itc_available


def test_csv_round_trip(tmp_path: Path) -> None:
    books, gstr2b, expected = synth.generate(seed=4, invoices=40)
    write_invoices(tmp_path / "b.csv", books, "books")
    write_invoices(tmp_path / "g.csv", gstr2b, "gstr2b")
    write_expected(tmp_path / "e.csv", expected)
    assert read_invoices(tmp_path / "b.csv", "books") == books
    assert read_invoices(tmp_path / "g.csv", "gstr2b") == gstr2b
    assert read_expected(tmp_path / "e.csv") == expected


def test_bad_rows_name_the_line(tmp_path: Path) -> None:
    header = ",".join(BOOKS_COLUMNS) + "\n"
    path = tmp_path / "b.csv"
    path.write_text(header + "R1,X,Y,1,2026-04-01,12x,0,0,0,2026-04\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2: taxable_value"):
        read_invoices(path, "books")
    path.write_text(header + "R1,X,Y,1,01/04/2026,100,0,0,0,2026-04\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2: invoice_date must be YYYY-MM-DD"):
        read_invoices(path, "books")
    path.write_text("row_id,invoice_no\nR1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        read_invoices(path, "books")


def test_amounts_accept_commas_and_keep_paise(tmp_path: Path) -> None:
    header = ",".join(BOOKS_COLUMNS) + "\n"
    path = tmp_path / "b.csv"
    path.write_text(header + '"",x,Y,1,2026-04-01,"1,00,000.5",0,9000.25,9000.25,2026-04\n',
                    encoding="utf-8")  # fmt: skip
    row = read_invoices(path, "books")[0]
    assert row.taxable_value == Decimal("100000.50") and row.total_tax == Decimal("18000.50")
    assert row.row_id == "R0001" and row.supplier_gstin == "X"


def test_cli_writes_three_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert synth.main(["--out", str(tmp_path), "--invoices", "30"]) == 0
    assert {p.name for p in tmp_path.iterdir()} == {
        "purchase_register.csv", "gstr2b.csv", "expected.csv"
    }  # fmt: skip
    assert "| matched |" in capsys.readouterr().out
