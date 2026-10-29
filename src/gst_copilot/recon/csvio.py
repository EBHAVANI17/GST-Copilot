"""Read and write the two input files and the ground truth as CSV.

Amounts are Decimal (never float: 0.1 + 0.2 != 0.3), dates are YYYY-MM-DD.
A bad row raises ValueError naming the file, line and column.
"""

import csv
import io
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from gst_copilot.recon.models import LABELS, Expected, Invoice, Source

BOOKS_COLUMNS = [
    "row_id", "supplier_gstin", "supplier_name", "invoice_no", "invoice_date",
    "taxable_value", "igst", "cgst", "sgst", "books_period",
]  # fmt: skip
GSTR2B_COLUMNS = [
    "row_id", "supplier_gstin", "trade_name", "invoice_no", "invoice_date",
    "taxable_value", "igst", "cgst", "sgst", "return_period", "itc_available",
]  # fmt: skip
EXPECTED_COLUMNS = ["books_id", "gstr2b_id", "label"]


def write_invoices(path: Path, rows: Iterable[Invoice], source: Source) -> None:
    columns = BOOKS_COLUMNS if source == "books" else GSTR2B_COLUMNS
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            common = [r.row_id, r.supplier_gstin, r.supplier_name, r.invoice_no,
                      r.invoice_date.isoformat(), f"{r.taxable_value:.2f}",
                      f"{r.igst:.2f}", f"{r.cgst:.2f}", f"{r.sgst:.2f}", r.period]  # fmt: skip
            w.writerow(common if source == "books" else [*common, "Y" if r.itc_available else "N"])


def read_invoices(path: Path, source: Source) -> list[Invoice]:
    return parse_invoices(path.read_text(encoding="utf-8-sig"), source, path.name)


def parse_invoices(text: str, source: Source, name: str = "file") -> list[Invoice]:
    """Rows from CSV text (a file or an upload). name is used in error messages."""
    columns = BOOKS_COLUMNS if source == "books" else GSTR2B_COLUMNS
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = set(columns) - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{name}: missing columns {sorted(missing)}")
    return [_parse(row, source, name, line) for line, row in enumerate(reader, start=2)]


def _parse(row: dict[str, str], source: Source, name: str, line: int) -> Invoice:
    def money(col: str) -> Decimal:
        raw = (row.get(col) or "0").strip().replace(",", "")
        try:
            return Decimal(raw or "0").quantize(Decimal("0.01"))
        except InvalidOperation:
            raise ValueError(f"{name} line {line}: {col} is not a number: {raw!r}") from None

    try:
        invoice_date = date.fromisoformat(row["invoice_date"].strip())
    except ValueError:
        raise ValueError(
            f"{name} line {line}: invoice_date must be YYYY-MM-DD: {row['invoice_date']!r}"
        ) from None
    books = source == "books"
    itc = (row.get("itc_available") or "Y").strip().upper()
    if itc not in {"Y", "N"}:
        raise ValueError(f"{name} line {line}: itc_available must be Y or N: {itc!r}")
    return Invoice(
        row_id=(row.get("row_id") or "").strip() or f"{'R' if books else 'B'}{line - 1:04d}",
        source=source,
        supplier_gstin=row["supplier_gstin"].strip().upper(),
        supplier_name=(row["supplier_name"] if books else row["trade_name"]).strip(),
        invoice_no=row["invoice_no"].strip(),
        invoice_date=invoice_date,
        taxable_value=money("taxable_value"),
        igst=money("igst"),
        cgst=money("cgst"),
        sgst=money("sgst"),
        period=(row["books_period"] if books else row["return_period"]).strip(),
        itc_available=itc == "Y",
    )


def write_expected(path: Path, rows: Iterable[Expected]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EXPECTED_COLUMNS)
        for e in rows:
            w.writerow([e.books_id or "", e.gstr2b_id or "", e.label])


def read_expected(path: Path) -> list[Expected]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        out = []
        for line, row in enumerate(csv.DictReader(f), start=2):
            if row["label"] not in LABELS:
                raise ValueError(f"{path.name} line {line}: unknown label {row['label']!r}")
            out.append(Expected(row["books_id"] or None, row["gstr2b_id"] or None, row["label"]))  # type: ignore[arg-type]
        return out
