"""Statutory explanations, recommended actions, and GSTR-3B Table 4 placements
for each reconciliation mismatch label (ADR 0026).

Grounded in:
- CGST Act, 2017 (ss. 16, 17, 77)
- CGST Rules, 2017 (rr. 36(4), 37, 42, 43, 46)
- CBIC Circular No. 170/02/2022-GST (GSTR-3B Table 4 reporting)
- GSTN Advisory dated 02.09.2022 (Notification No. 14/2022-CT)
"""

from dataclasses import dataclass

from gst_copilot.recon.models import Label


@dataclass(frozen=True)
class LabelExplanation:
    label: Label
    title: str
    explanation: str
    action: str
    gstr3b_row: str
    citation: str


EXPLANATIONS: dict[Label, LabelExplanation] = {
    "matched": LabelExplanation(
        label="matched",
        title="Matched (Eligible for ITC)",
        explanation=(
            "Invoice details in the purchase register match the supplier's GSTR-2B "
            "statement within tolerance."
        ),
        action="Claim eligible input tax credit in full in the current period return.",
        gstr3b_row="Table 4(A)(5) [All other ITC]",
        citation="CGST Act s.16(2); Circular 170/02/2022-GST Para 4.1",
    ),
    "amount_diff": LabelExplanation(
        label="amount_diff",
        title="Tax / Amount Mismatch",
        explanation=(
            "Taxable value or tax amount differs between the purchase register and "
            "GSTR-2B beyond the tolerance threshold."
        ),
        action=(
            "Claim the lower amount. If books < 2B, claim books amount in 4(A)(5) and "
            "temporarily reverse the excess in 4(B)(2). If 2B < books, claim 2B amount "
            "and request supplier to upload an amendment in GSTR-1."
        ),
        gstr3b_row=(
            "Table 4(A)(5) capped at GSTR-2B; excess reversed in Table 4(B)(2) "
            "only when GSTR-2B > books"
        ),
        citation="CGST Act s.16(2)(c); Circular 170/02/2022-GST Para 4.3",
    ),
    "invoice_no_format": LabelExplanation(
        label="invoice_no_format",
        title="Invoice Number Format Difference",
        explanation=(
            "Invoice numbers match once punctuation, separators, casing, and leading zeros "
            "are normalized (e.g. 'INV/0042' vs 'inv-42')."
        ),
        action=(
            "Verify physical invoice matches the supplier entry and update book records if "
            "needed; eligible for credit claim."
        ),
        gstr3b_row="Table 4(A)(5) [All other ITC]",
        citation="CGST Rules r.46(b); CGST Act s.16(2)(a)",
    ),
    "missing_in_2b": LabelExplanation(
        label="missing_in_2b",
        title="Missing in GSTR-2B",
        explanation=(
            "Invoice is recorded in your purchase register but has not been uploaded by the "
            "supplier in GSTR-1, or was filed after the monthly cut-off."
        ),
        action=(
            "Do not claim ITC in the current month's return. Contact the supplier to file or "
            "amend their GSTR-1. Claim credit once the invoice appears in a future GSTR-2B."
        ),
        gstr3b_row="Do not claim (leave out of Table 4 entirely)",
        citation="CGST Act s.16(2)(aa); CGST Rules r.36(4)",
    ),
    "missing_in_books": LabelExplanation(
        label="missing_in_books",
        title="In GSTR-2B, Missing in Books",
        explanation=(
            "The invoice is reported in GSTR-2B by the supplier, but is not recorded in your "
            "purchase register (e.g. goods in transit or unrecorded voucher)."
        ),
        action=(
            "Retain the auto-populated gross amount in 4(A)(5), but make a temporary reversal "
            "in Table 4(B)(2) under s.16(2)(b) (goods/invoice not yet received). "
            "Reclaim in 4(A)(5) and 4(D)(1) once recorded."
        ),
        gstr3b_row="Table 4(A)(5) gross AND Table 4(B)(2) [Others] temporary reversal",
        citation="CGST Act s.16(2)(b); Circular 170/02/2022-GST Para 4.3(C) & Annexure Note 3",
    ),
    "period_diff": LabelExplanation(
        label="period_diff",
        title="Timing / Period Difference",
        explanation=(
            "The invoice exists in both records but was reported by the supplier in a different "
            "tax period from the purchase register booking date."
        ),
        action=(
            "If credit was temporarily reversed in an earlier tax period under 4(B)(2), avail "
            "it in Table 4(A)(5) in the current return and report the reclaimed amount in "
            "tracking row 4(D)(1)."
        ),
        gstr3b_row="Table 4(A)(5) gross AND Table 4(D)(1) [Reclaimed ITC]",
        citation="Circular 170/02/2022-GST Para 4.3(E) & Annexure Note 4; CGST Act s.16(4)",
    ),
    "gstin_typo": LabelExplanation(
        label="gstin_typo",
        title="Supplier GSTIN Typo",
        explanation=(
            "Invoice number and date match, but the supplier GSTIN in your books differs by "
            "one character from the GSTIN reported in GSTR-2B."
        ),
        action=(
            "Verify supplier identity against the physical tax invoice and GST portal master, "
            "and correct the GSTIN in the purchase register."
        ),
        gstr3b_row="Table 4(A)(5) [All other ITC] once master data is verified",
        citation="CGST Rules r.46(c); CGST Act s.16(2)(a)",
    ),
    "tax_type": LabelExplanation(
        label="tax_type",
        title="Tax Type Mismatch (IGST vs CGST/SGST)",
        explanation=(
            "Books and GSTR-2B disagree on tax heads (booked as IGST but reported as "
            "CGST + SGST, or vice versa), pointing to a Place of Supply conflict."
        ),
        action=(
            "Determine the correct place of supply under IGST Act ss. 10/12. Do not claim credit "
            "under the incorrect tax head. Request supplier to issue credit note / amendment "
            "if filed under wrong head."
        ),
        gstr3b_row="Table 4(A)(5) under correct tax head, or Table 4(B)(2) temporary reversal",
        citation="CGST Act s.77; IGST Act s.19; Circular 170/02/2022-GST Para 4.3",
    ),
    "itc_unavailable": LabelExplanation(
        label="itc_unavailable",
        title="Ineligible / Restricted in GSTR-2B",
        explanation=(
            "GSTR-2B marks the invoice with ITC Available = 'N' (e.g. filing beyond the Section "
            "16(4) cut-off, or recipient state differs from supplier state in intra-State supply)."
        ),
        action=(
            "Do not claim credit. These invoices do not auto-populate into 4(A)(5). Report in "
            "Table 4(D)(2) for information and disclosure only."
        ),
        gstr3b_row="Table 4(D)(2) [Ineligible ITC under s.16(4) & PoS] (excluded from 4(A))",
        citation=(
            "CGST Act s.16(4); Circular 170/02/2022-GST Para 4.3(A) & 4.3(F); "
            "GSTN Advisory 02.09.2022"
        ),
    ),
    "duplicate_in_books": LabelExplanation(
        label="duplicate_in_books",
        title="Duplicate Entry in Books",
        explanation=(
            "The exact same supplier invoice is recorded more than once in the purchase register."
        ),
        action=(
            "Remove or cancel the duplicate voucher in your accounting system to avoid illegal "
            "double-claiming of input tax credit."
        ),
        gstr3b_row="Claim only once in Table 4(A)(5)",
        citation="CGST Act s.16(1), s.16(2)",
    ),
}


def explain_label(label: Label) -> LabelExplanation:
    """Return the statutory explanation for a reconciliation label."""
    if label not in EXPLANATIONS:
        raise KeyError(f"Unknown reconciliation label: {label!r}")
    return EXPLANATIONS[label]


def all_explanations() -> dict[Label, LabelExplanation]:
    """Return all reconciliation label explanations keyed by label."""
    return dict(EXPLANATIONS)
