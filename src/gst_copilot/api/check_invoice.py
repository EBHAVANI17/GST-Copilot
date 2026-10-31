"""POST /check-invoice: check one invoice's GSTINs, required fields, total and tax type.

Nothing is stored and nothing about the invoice is logged except which rules failed.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from gst_copilot.config import get_settings
from gst_copilot.invoice.check import InvoiceIn, check
from gst_copilot.invoice.extract import extract_invoice_from_pdf

log = logging.getLogger("gst_copilot.invoice")
router = APIRouter(tags=["invoice"])

# Rupees and paise, sent as text ("18000.50") or a number; never negative.
Money = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2)]


class InvoiceRequest(BaseModel):
    supplier_gstin: str = Field(max_length=20)
    recipient_gstin: str | None = Field(default=None, max_length=20)
    invoice_no: str = Field(max_length=50)
    invoice_date: date
    place_of_supply: str = Field(max_length=5, description="Two-digit state code, e.g. 29")
    taxable_value: Money
    igst: Money = Decimal("0")
    cgst: Money = Decimal("0")
    sgst: Money = Decimal("0")
    invoice_total: Money


class CheckResult(BaseModel):
    rule: str
    ok: bool
    message: str
    verified: bool


class CheckResponse(BaseModel):
    ok: bool  # every check passed
    checks: list[CheckResult]
    unverified_rules: list[str]  # rules not yet checked against the law text (ADR 0023)
    disclaimer: str = (
        "Format and arithmetic checks only, not tax advice. Tax rates are not checked."
    )
    extracted_invoice: dict[str, Any] | None = None


@router.post("/check-invoice", response_model=CheckResponse)
async def check_invoice(body: InvoiceRequest) -> CheckResponse:
    inv = InvoiceIn(**body.model_dump())
    tolerance = Decimal(str(get_settings().recon_tolerance_rupees))
    checks = check(inv, tolerance)
    failed = [c.rule for c in checks if not c.ok]
    log.info("invoice checked", extra={"fields": {"failed": failed}})
    return CheckResponse(
        ok=not failed,
        checks=[CheckResult(**vars(c)) for c in checks],
        unverified_rules=[c.rule for c in checks if not c.verified],
    )


@router.post("/check-invoice/upload", response_model=CheckResponse)
async def check_invoice_upload(
    invoice_file: Annotated[UploadFile, File(description="PDF Invoice document")],
) -> CheckResponse:
    data = await invoice_file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Invoice file larger than 5 MB.")
    try:
        inv = extract_invoice_from_pdf(data)
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse PDF invoice: {exc}") from None
    tolerance = Decimal(str(get_settings().recon_tolerance_rupees))
    checks = check(inv, tolerance)
    failed = [c.rule for c in checks if not c.ok]
    log.info("invoice pdf uploaded and checked", extra={"fields": {"failed": failed}})
    return CheckResponse(
        ok=not failed,
        checks=[CheckResult(**vars(c)) for c in checks],
        unverified_rules=[c.rule for c in checks if not c.verified],
        extracted_invoice={
            "supplier_gstin": inv.supplier_gstin,
            "recipient_gstin": inv.recipient_gstin,
            "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat(),
            "place_of_supply": inv.place_of_supply,
            "taxable_value": str(inv.taxable_value),
            "cgst": str(inv.cgst),
            "sgst": str(inv.sgst),
            "igst": str(inv.igst),
            "invoice_total": str(inv.invoice_total),
        },
    )
