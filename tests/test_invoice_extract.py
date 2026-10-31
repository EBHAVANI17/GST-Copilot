"""Tests for PDF invoice extraction and POST /check-invoice/upload."""

import io
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from gst_copilot.api.main import create_app
from gst_copilot.invoice.extract import extract_invoice_from_pdf


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_extract_invoice_from_mocked_pdf() -> None:
    sample_text = """
    TAX INVOICE
    Supplier GSTIN: 27AAPFU0939F1ZV
    Recipient GSTIN: 29ABCCE1234F1Z9
    Invoice Number: INV/2026/042
    Invoice Date: 2026-04-10
    Place of Supply: 29
    Taxable Value: 100,000.00
    IGST: 18,000.00
    Total Invoice Value: 118,000.00
    """
    mock_page = MagicMock()
    mock_page.extract_text.return_value = sample_text

    with patch("gst_copilot.invoice.extract.PdfReader") as mock_reader_cls:
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        inv = extract_invoice_from_pdf(b"%PDF-1.4-dummy")

        assert inv.supplier_gstin == "27AAPFU0939F1ZV"
        assert inv.recipient_gstin == "29ABCCE1234F1Z9"
        assert inv.invoice_no == "INV/2026/042"
        assert inv.place_of_supply == "29"
        assert str(inv.taxable_value) == "100000.00"
        assert str(inv.igst) == "18000.00"
        assert str(inv.invoice_total) == "118000.00"


def test_extract_invoice_fallback_on_blank_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)

    inv = extract_invoice_from_pdf(buf.getvalue())
    assert inv.supplier_gstin == "27AAPFU0939F1ZV"
    assert inv.invoice_no == "INV-PDF-001"
    assert inv.place_of_supply == "27"
    assert str(inv.invoice_total) == "118000.00"


async def test_api_check_invoice_upload(client: AsyncClient) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    files = {"invoice_file": ("invoice.pdf", pdf_bytes, "application/pdf")}
    res = await client.post("/check-invoice/upload", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "extracted_invoice" in data
    assert data["extracted_invoice"]["supplier_gstin"] == "27AAPFU0939F1ZV"
    assert data["extracted_invoice"]["invoice_no"] == "INV-PDF-001"
