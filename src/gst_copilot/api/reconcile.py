"""POST /reconcile: upload the purchase register and GSTR-2B, get every invoice labelled.

The files are processed in memory and never stored: the books of a business are its
private data. Only counts are logged.
"""

import logging
from collections import Counter
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from gst_copilot.config import get_settings
from gst_copilot.recon.csvio import parse_invoices
from gst_copilot.recon.explain import EXPLANATIONS
from gst_copilot.recon.matcher import reconcile, results_csv
from gst_copilot.recon.models import LABELS, Invoice, Source

log = logging.getLogger("gst_copilot.recon")
router = APIRouter(tags=["reconcile"])

MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file: about 30,000 invoice rows
MAX_ROWS = 20_000


class InvoiceResult(BaseModel):
    books_id: str | None
    gstr2b_id: str | None
    label: str
    supplier_gstin: str
    invoice_no: str
    total_tax: str  # rupees as text, so no float rounding: "18000.50"
    details: dict[str, str]


class ExplanationResponse(BaseModel):
    title: str
    explanation: str
    action: str
    gstr3b_row: str
    citation: str


class ReconcileResponse(BaseModel):
    tolerance_rupees: str
    books_rows: int
    gstr2b_rows: int
    summary: dict[str, int]  # invoices per label
    tax_by_label: dict[str, str]  # total tax per label (books side; GSTR-2B if only there)
    explanations: dict[str, ExplanationResponse] = Field(default_factory=dict)
    results: list[InvoiceResult]
    disclaimer: str = "Reconciliation aid, not tax advice. Check results before filing."


async def _read(upload: UploadFile, source: Source) -> list[Invoice]:
    name = upload.filename or source
    data = await upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"{name}: larger than 5 MB.")
    try:
        rows = parse_invoices(data.decode("utf-8-sig"), source, name)
    except UnicodeDecodeError:
        raise HTTPException(422, f"{name}: not a UTF-8 CSV file.") from None
    except (ValueError, KeyError) as exc:  # bad column, number or date, with the line number
        raise HTTPException(422, str(exc)) from None
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"{name}: over {MAX_ROWS} rows.")
    return rows


@router.post(
    "/reconcile",
    response_model=ReconcileResponse,
    responses={200: {"content": {"text/csv": {}}, "description": "JSON, or CSV with format=csv"}},
)
async def reconcile_endpoint(
    purchase_register: Annotated[UploadFile, File(description="Your purchase register CSV")],
    gstr2b: Annotated[UploadFile, File(description="GSTR-2B (B2B invoices) CSV")],
    tolerance: Annotated[float | None, Query(ge=0, le=100, description="Rupees")] = None,
    format: Annotated[Literal["json", "csv"], Query()] = "json",
) -> ReconcileResponse | Response:
    books = await _read(purchase_register, "books")
    twob = await _read(gstr2b, "gstr2b")
    tol = Decimal(
        str(tolerance if tolerance is not None else get_settings().recon_tolerance_rupees)
    )
    results = reconcile(books, twob, tol)
    summary: Counter[str] = Counter(r.label for r in results)
    log.info(
        "reconciled",
        extra={"fields": {"books_rows": len(books), "gstr2b_rows": len(twob),
                          **summary}},
    )  # fmt: skip

    if format == "csv":
        return Response(
            results_csv(results),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="reconciliation.csv"'},
        )

    # Separate lookups: the two files may use the same row ids.
    by_books = {r.row_id: r for r in books}
    by_twob = {r.row_id: r for r in twob}
    tax: dict[str, Decimal] = {}
    items = []
    for r in results:
        inv = by_books[r.books_id] if r.books_id else by_twob[r.gstr2b_id or ""]
        tax[r.label] = tax.get(r.label, Decimal("0")) + inv.total_tax
        items.append(
            InvoiceResult(
                books_id=r.books_id,
                gstr2b_id=r.gstr2b_id,
                label=r.label,
                supplier_gstin=inv.supplier_gstin,
                invoice_no=inv.invoice_no,
                total_tax=f"{inv.total_tax:.2f}",
                details=r.diffs,
            )
        )
    active_summary = {label: summary[label] for label in LABELS if summary[label]}
    explanations = {
        label: ExplanationResponse(
            title=EXPLANATIONS[label].title,
            explanation=EXPLANATIONS[label].explanation,
            action=EXPLANATIONS[label].action,
            gstr3b_row=EXPLANATIONS[label].gstr3b_row,
            citation=EXPLANATIONS[label].citation,
        )
        for label in active_summary
        if label in EXPLANATIONS
    }
    return ReconcileResponse(
        tolerance_rupees=f"{tol:.2f}",
        books_rows=len(books),
        gstr2b_rows=len(twob),
        summary=active_summary,
        tax_by_label={label: f"{tax[label]:.2f}" for label in LABELS if label in tax},
        explanations=explanations,
        results=items,
    )
