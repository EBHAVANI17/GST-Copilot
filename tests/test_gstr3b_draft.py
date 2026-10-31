"""Unit tests for Draft GSTR-3B Table 4 compilation and statutory arithmetic (M4b, ADR 0027)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.recon import synth
from gst_copilot.recon.__main__ import main
from gst_copilot.recon.csvio import write_invoices
from gst_copilot.recon.gstr3b import TaxBreakdown, compile_table4
from gst_copilot.recon.matcher import Result, reconcile
from gst_copilot.recon.models import Invoice


def test_tax_breakdown_arithmetic() -> None:
    t1 = TaxBreakdown(Decimal("100.00"), Decimal("50.00"), Decimal("50.00"), Decimal("10.00"))
    t2 = TaxBreakdown(Decimal("20.00"), Decimal("10.00"), Decimal("10.00"), Decimal("0.00"))

    assert t1.total == Decimal("210.00")
    added = t1 + t2
    assert added == TaxBreakdown(
        Decimal("120.00"), Decimal("60.00"), Decimal("60.00"), Decimal("10.00")
    )
    subbed = t1 - t2
    assert subbed == TaxBreakdown(
        Decimal("80.00"), Decimal("40.00"), Decimal("40.00"), Decimal("10.00")
    )


def test_table4_arithmetic_consistency() -> None:
    books, twob, _ = synth.generate(seed=42, invoices=100)
    results = reconcile(books, twob, Decimal("1.0"))
    t4 = compile_table4(books, twob, results)

    # 4(C) Net ITC MUST equal 4(A) - [4(B)(1) + 4(B)(2)] across all heads
    expected_c_igst = (
        t4.a5_all_other_itc.tax.igst
        - t4.b1_permanent_reversals.tax.igst
        - t4.b2_temporary_reversals.tax.igst
    )
    expected_c_cgst = (
        t4.a5_all_other_itc.tax.cgst
        - t4.b1_permanent_reversals.tax.cgst
        - t4.b2_temporary_reversals.tax.cgst
    )
    expected_c_sgst = (
        t4.a5_all_other_itc.tax.sgst
        - t4.b1_permanent_reversals.tax.sgst
        - t4.b2_temporary_reversals.tax.sgst
    )

    assert t4.c_net_itc.tax.igst == expected_c_igst
    assert t4.c_net_itc.tax.cgst == expected_c_cgst
    assert t4.c_net_itc.tax.sgst == expected_c_sgst
    assert t4.c_net_itc.tax.total == expected_c_igst + expected_c_cgst + expected_c_sgst


def test_missing_in_2b_excluded_from_table_4() -> None:
    books, twob, _ = synth.generate(seed=1, invoices=50)
    results = reconcile(books, twob, Decimal("1.0"))
    m2b_results = [r for r in results if r.label == "missing_in_2b"]
    assert len(m2b_results) > 0

    t4 = compile_table4(books, twob, results)
    m2b_books_ids = {r.books_id for r in m2b_results}

    # None of the missing_in_2b book IDs should appear in 4(A)(5) or 4(C)
    for ref in t4.a5_all_other_itc.invoice_refs:
        assert ref not in m2b_books_ids


def test_missing_in_books_temporary_reversal() -> None:
    books, twob, _ = synth.generate(seed=2, invoices=60)
    results = reconcile(books, twob, Decimal("1.0"))
    mb_results = [r for r in results if r.label == "missing_in_books"]
    assert len(mb_results) > 0

    t4 = compile_table4(books, twob, results)
    mb_gstr2b_ids = {r.gstr2b_id for r in mb_results}

    # All missing_in_books invoices must appear in both 4(A)(5) and 4(B)(2)
    for gid in mb_gstr2b_ids:
        assert gid in t4.a5_all_other_itc.invoice_refs
        assert gid in t4.b2_temporary_reversals.invoice_refs


def test_itc_unavailable_reported_in_4d2_only() -> None:
    books, twob, _ = synth.generate(seed=3, invoices=60)
    results = reconcile(books, twob, Decimal("1.0"))
    iu_results = [r for r in results if r.label == "itc_unavailable"]
    assert len(iu_results) > 0

    t4 = compile_table4(books, twob, results)
    iu_gstr2b_ids = {r.gstr2b_id for r in iu_results}

    # Must be in 4(D)(2) and NOT in 4(A)(5)
    for gid in iu_gstr2b_ids:
        assert gid in t4.d2_ineligible.invoice_refs
        assert gid not in t4.a5_all_other_itc.invoice_refs


def test_period_diff_in_4a5_and_4d1() -> None:
    books, twob, _ = synth.generate(seed=4, invoices=60)
    results = reconcile(books, twob, Decimal("1.0"))
    pd_results = [r for r in results if r.label == "period_diff"]
    assert len(pd_results) > 0

    t4 = compile_table4(books, twob, results)
    assert t4.d1_reclaimed.invoice_count > 0
    assert t4.d1_reclaimed.tax.total > Decimal("0")


def test_cli_gstr3b_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    synth.main(["--out", str(tmp_path), "--invoices", "30", "--seed", "1"])
    capsys.readouterr()
    assert main([str(tmp_path), "--gstr3b"]) == 0
    out = capsys.readouterr().out
    assert "### Draft Form GSTR-3B Table 4 (Eligible ITC)" in out
    assert "4(A)(5)" in out
    assert "4(B)(2)" in out
    assert "4(C)" in out
    assert "4(D)(1)" in out
    assert "4(D)(2)" in out


async def test_reconcile_api_returns_draft_3b(tmp_path: Path) -> None:
    books, twob, _ = synth.generate(seed=1, invoices=40)
    write_invoices(tmp_path / "b.csv", books, "books")
    write_invoices(tmp_path / "g.csv", twob, "gstr2b")
    files = {
        "purchase_register": ("b.csv", (tmp_path / "b.csv").read_bytes(), "text/csv"),
        "gstr2b": ("g.csv", (tmp_path / "g.csv").read_bytes(), "text/csv"),
    }

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://t"
    ) as client:
        r = await client.post("/reconcile", files=files)
        assert r.status_code == 200
        body = r.json()
        assert "draft_3b" in body and body["draft_3b"] is not None
        d3b = body["draft_3b"]
        assert d3b["a5_all_other_itc"]["row_key"] == "4(A)(5)"
        assert d3b["b2_temporary_reversals"]["row_key"] == "4(B)(2)"
        assert d3b["c_net_itc"]["row_key"] == "4(C)"
        assert d3b["d1_reclaimed"]["row_key"] == "4(D)(1)"
        assert d3b["d2_ineligible"]["row_key"] == "4(D)(2)"
        assert Decimal(d3b["c_net_itc"]["tax"]["total"]) > Decimal("0")


def test_amount_diff_reversals_in_table4_both_directions() -> None:
    """Verify statutory Table 4 behavior for amount_diff when 2B > books and when 2B < books."""
    # Case 1: 2B > Books (supplier reported more tax in GSTR-1 than buyer recorded)
    # Circular 170: Gross 2B enters 4(A)(5), excess reversed in 4(B)(2), net 4(C) = books.
    b1 = Invoice(
        row_id="R0001",
        source="books",
        supplier_gstin="27AAPFU0939F1ZV",
        supplier_name="Vendor A",
        invoice_no="INV-001",
        invoice_date=date(2026, 4, 10),
        taxable_value=Decimal("10000.00"),
        igst=Decimal("1800.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        period="2026-04",
    )
    g1 = Invoice(
        row_id="B0001",
        source="gstr2b",
        supplier_gstin="27AAPFU0939F1ZV",
        supplier_name="Vendor A",
        invoice_no="INV-001",
        invoice_date=date(2026, 4, 10),
        taxable_value=Decimal("12000.00"),
        igst=Decimal("2160.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        period="2026-04",
    )
    res1 = [Result("R0001", "B0001", "amount_diff")]
    t4_1 = compile_table4([b1], [g1], res1)

    assert t4_1.a5_all_other_itc.tax.igst == Decimal("2160.00")
    assert t4_1.b2_temporary_reversals.tax.igst == Decimal("360.00")  # 2160 - 1800
    assert "R0001:B0001" in t4_1.b2_temporary_reversals.invoice_refs
    assert t4_1.c_net_itc.tax.igst == Decimal("1800.00")  # Net equals books

    # Case 2: 2B < Books (supplier under-reported tax in GSTR-1)
    # Circular 170 / s.16(2)(aa): 4(A)(5) capped at 2B, no excess in 2B to reverse in 4(B)(2).
    b2 = Invoice(
        row_id="R0002",
        source="books",
        supplier_gstin="27AAPFU0939F1ZV",
        supplier_name="Vendor B",
        invoice_no="INV-002",
        invoice_date=date(2026, 4, 10),
        taxable_value=Decimal("10000.00"),
        igst=Decimal("1800.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        period="2026-04",
    )
    g2 = Invoice(
        row_id="B0002",
        source="gstr2b",
        supplier_gstin="27AAPFU0939F1ZV",
        supplier_name="Vendor B",
        invoice_no="INV-002",
        invoice_date=date(2026, 4, 10),
        taxable_value=Decimal("8000.00"),
        igst=Decimal("1440.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        period="2026-04",
    )
    res2 = [Result("R0002", "B0002", "amount_diff")]
    t4_2 = compile_table4([b2], [g2], res2)

    assert t4_2.a5_all_other_itc.tax.igst == Decimal("1440.00")
    assert t4_2.b2_temporary_reversals.tax.igst == Decimal("0.00")  # No excess in 2B
    assert "R0002:B0002" not in t4_2.b2_temporary_reversals.invoice_refs
    assert t4_2.c_net_itc.tax.igst == Decimal("1440.00")  # Net capped at 2B
