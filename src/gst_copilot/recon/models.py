"""One invoice line as it appears in the books or in GSTR-2B."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

Source = Literal["books", "gstr2b"]

# What the reconciliation must say about each invoice. M4.2 predicts these;
# synth.py plants them, so every prediction can be checked against the truth.
LABELS = (
    "matched",  # same invoice, amounts equal within the tolerance
    "amount_diff",  # same invoice, taxable value or tax differs by more than the tolerance
    "invoice_no_format",  # same invoice, number written differently ("INV/0042" vs "inv-42")
    "missing_in_2b",  # in the books, not reported by the supplier (yet)
    "missing_in_books",  # reported by a supplier, not in the books
    "period_diff",  # same invoice, in GSTR-2B of a different month
    "gstin_typo",  # same invoice, supplier GSTIN differs by one character
    "tax_type",  # IGST in one, CGST + SGST in the other (place-of-supply error)
    "itc_unavailable",  # GSTR-2B says ITC is not available for this invoice
    "duplicate_in_books",  # the same invoice entered twice in the books
)
Label = Literal[
    "matched",
    "amount_diff",
    "invoice_no_format",
    "missing_in_2b",
    "missing_in_books",
    "period_diff",
    "gstin_typo",
    "tax_type",
    "itc_unavailable",
    "duplicate_in_books",
]

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Invoice:
    row_id: str  # R0001 in the books, B0001 in GSTR-2B
    source: Source
    supplier_gstin: str
    supplier_name: str
    invoice_no: str
    invoice_date: date
    taxable_value: Decimal
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    period: str = ""  # YYYY-MM: month booked (books) or return period (GSTR-2B)
    itc_available: bool = True  # GSTR-2B only; always True in the books
    extra: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def total_tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst


@dataclass(frozen=True)
class Expected:
    """Ground truth for one invoice: which rows belong together and the label."""

    books_id: str | None
    gstr2b_id: str | None
    label: Label
