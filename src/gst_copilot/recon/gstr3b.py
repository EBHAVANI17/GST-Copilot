"""Draft GSTR-3B Table 4 Return Preparation (Milestone M4b, ADR 0027).

Compiles statutory Form GSTR-3B Table 4 (Eligible ITC) directly from the
reconciliation between the purchase register and GSTR-2B, in strict compliance with:
- CBIC Circular No. 170/02/2022-GST (dated 06.07.2022)
- GSTN Advisory on Table 4 Changes (dated 02.09.2022 / Notification No. 14/2022-CT)

Every rupee in Table 4 is traceable to specific invoice row IDs.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from gst_copilot.recon.matcher import Result
from gst_copilot.recon.models import ZERO, Invoice


@dataclass(frozen=True)
class TaxBreakdown:
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def __add__(self, other: "TaxBreakdown") -> "TaxBreakdown":
        return TaxBreakdown(
            igst=self.igst + other.igst,
            cgst=self.cgst + other.cgst,
            sgst=self.sgst + other.sgst,
            cess=self.cess + other.cess,
        )

    def __sub__(self, other: "TaxBreakdown") -> "TaxBreakdown":
        return TaxBreakdown(
            igst=self.igst - other.igst,
            cgst=self.cgst - other.cgst,
            sgst=self.sgst - other.sgst,
            cess=self.cess - other.cess,
        )


@dataclass(frozen=True)
class Table4Row:
    row_key: str
    description: str
    tax: TaxBreakdown
    invoice_count: int
    invoice_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DraftTable4:
    a5_all_other_itc: Table4Row
    b1_permanent_reversals: Table4Row
    b2_temporary_reversals: Table4Row
    c_net_itc: Table4Row
    d1_reclaimed: Table4Row
    d2_ineligible: Table4Row
    disclaimer: str = (
        "Draft GSTR-3B return preparation aid, not tax advice. Traceable to input invoices."
    )


def compile_table4(
    books: list[Invoice],
    twob: list[Invoice],
    results: list[Result],
) -> DraftTable4:
    """Compile Form GSTR-3B Table 4 from reconciliation results."""
    by_books = {inv.row_id: inv for inv in books}
    by_twob = {inv.row_id: inv for inv in twob}

    a5_tax = TaxBreakdown()
    a5_refs: list[str] = []

    b1_tax = TaxBreakdown()
    b1_refs: list[str] = []

    b2_tax = TaxBreakdown()
    b2_refs: list[str] = []

    d1_tax = TaxBreakdown()
    d1_refs: list[str] = []

    d2_tax = TaxBreakdown()
    d2_refs: list[str] = []

    for r in results:
        # 1. ITC Unavailable: GSTR-2B restricts credit under s.16(4) / PoS.
        # Circular 170 (Para 4.3(A) & (F)): Excluded from 4(A); reported in 4(D)(2).
        if r.label == "itc_unavailable":
            g_inv = by_twob[r.gstr2b_id or ""]
            d2_tax += TaxBreakdown(g_inv.igst, g_inv.cgst, g_inv.sgst)
            if r.gstr2b_id:
                d2_refs.append(r.gstr2b_id)
            continue

        # 2. Missing in GSTR-2B: In books only.
        # Under s.16(2)(aa) & r.36(4), cannot be claimed in Table 4 of the current return.
        if r.label == "missing_in_2b":
            continue

        # 3. Missing in Books: In GSTR-2B, but invoice/goods not yet recorded.
        # Circular 170 (Para 4.3(C) & Annexure Note 3):
        # Gross in 4(A)(5), temporary reversal in 4(B)(2).
        if r.label == "missing_in_books":
            g_inv = by_twob[r.gstr2b_id or ""]
            t = TaxBreakdown(g_inv.igst, g_inv.cgst, g_inv.sgst)
            a5_tax += t
            b2_tax += t
            if r.gstr2b_id:
                a5_refs.append(r.gstr2b_id)
                b2_refs.append(r.gstr2b_id)
            continue

        # 4. Period Difference: Reclaim of temporary reversal from earlier periods.
        # Circular 170 (Para 4.3(E) & Annexure Note 4): Avail in 4(A)(5), track in 4(D)(1).
        if r.label == "period_diff":
            inv = by_twob[r.gstr2b_id] if r.gstr2b_id else by_books[r.books_id or ""]
            t = TaxBreakdown(inv.igst, inv.cgst, inv.sgst)
            a5_tax += t
            d1_tax += t
            ref = r.gstr2b_id or r.books_id or ""
            if ref:
                a5_refs.append(ref)
                d1_refs.append(ref)
            continue

        # 5. Amount Difference: Tax mismatch between books and 2B.
        # Gross 2B enters 4(A)(5). If 2B > books, reverse the excess in 4(B)(2).
        if r.label == "amount_diff":
            b_inv = by_books[r.books_id or ""]
            g_inv = by_twob[r.gstr2b_id or ""]
            a5_tax += TaxBreakdown(g_inv.igst, g_inv.cgst, g_inv.sgst)
            ref = f"{r.books_id}:{r.gstr2b_id}"
            a5_refs.append(ref)

            if g_inv.total_tax > b_inv.total_tax:
                excess_igst = max(ZERO, g_inv.igst - b_inv.igst)
                excess_cgst = max(ZERO, g_inv.cgst - b_inv.cgst)
                excess_sgst = max(ZERO, g_inv.sgst - b_inv.sgst)
                b2_tax += TaxBreakdown(excess_igst, excess_cgst, excess_sgst)
                b2_refs.append(ref)
            continue

        # 6. Tax Type Mismatch: Conflict in tax heads (Place of Supply).
        # Populates 4(A)(5) from 2B, temporarily reversed in 4(B)(2) to prevent wrong availment.
        if r.label == "tax_type":
            g_inv = by_twob[r.gstr2b_id or ""]
            t = TaxBreakdown(g_inv.igst, g_inv.cgst, g_inv.sgst)
            a5_tax += t
            b2_tax += t
            ref = f"{r.books_id}:{r.gstr2b_id}"
            a5_refs.append(ref)
            b2_refs.append(ref)
            continue

        # 7. Duplicate in Books: Present only once in GSTR-2B.
        # If matched to GSTR-2B, enters 4(A)(5) once. The duplicate in books does not add extra.
        if r.label == "duplicate_in_books":
            if r.gstr2b_id and r.gstr2b_id in by_twob:
                g_inv = by_twob[r.gstr2b_id]
                a5_tax += TaxBreakdown(g_inv.igst, g_inv.cgst, g_inv.sgst)
                a5_refs.append(r.gstr2b_id)
            continue

        # 8. Matched, Invoice No Format, Supplier GSTIN Typo:
        # Standard eligible inward supply. Auto-populates 4(A)(5).
        inv = by_twob[r.gstr2b_id] if r.gstr2b_id else by_books[r.books_id or ""]
        a5_tax += TaxBreakdown(inv.igst, inv.cgst, inv.sgst)
        ref = (
            f"{r.books_id}:{r.gstr2b_id}"
            if (r.books_id and r.gstr2b_id)
            else (r.gstr2b_id or r.books_id or "")
        )
        if ref:
            a5_refs.append(ref)

    # 4(C) Net ITC Available = 4(A) - [4(B)(1) + 4(B)(2)]
    c_tax = a5_tax - (b1_tax + b2_tax)

    return DraftTable4(
        a5_all_other_itc=Table4Row(
            row_key="4(A)(5)",
            description="ITC Available: (5) All other ITC",
            tax=a5_tax,
            invoice_count=len(a5_refs),
            invoice_refs=a5_refs,
        ),
        b1_permanent_reversals=Table4Row(
            row_key="4(B)(1)",
            description="ITC Reversed: (1) As per rules 38, 42 & 43 and section 17(5)",
            tax=b1_tax,
            invoice_count=len(b1_refs),
            invoice_refs=b1_refs,
        ),
        b2_temporary_reversals=Table4Row(
            row_key="4(B)(2)",
            description="ITC Reversed: (2) Others (temporary / reclaimable reversals)",
            tax=b2_tax,
            invoice_count=len(b2_refs),
            invoice_refs=b2_refs,
        ),
        c_net_itc=Table4Row(
            row_key="4(C)",
            description="Net ITC Available: 4(A) - 4(B)",
            tax=c_tax,
            invoice_count=len(a5_refs),
            invoice_refs=a5_refs,
        ),
        d1_reclaimed=Table4Row(
            row_key="4(D)(1)",
            description="Other Details: (1) ITC reclaimed which was reversed under 4(B)(2)",
            tax=d1_tax,
            invoice_count=len(d1_refs),
            invoice_refs=d1_refs,
        ),
        d2_ineligible=Table4Row(
            row_key="4(D)(2)",
            description="Other Details: (2) Ineligible ITC under section 16(4) & PoS",
            tax=d2_tax,
            invoice_count=len(d2_refs),
            invoice_refs=d2_refs,
        ),
    )
