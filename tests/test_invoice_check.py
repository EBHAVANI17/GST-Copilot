"""M4.6: invoice checker rules and POST /check-invoice."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.invoice.check import Check, InvoiceIn, check
from gst_copilot.recon.gstin import check_char

SUPPLIER = "27AAPFU0939F1ZV"  # format example from GST documentation, state 27
BUYER = "29ABCCE1234F1Z" + check_char("29ABCCE1234F1Z")  # made up, state 29
ZERO = Decimal("0")

# Inter-state (supplier in 27, place of supply 29): IGST.
INTER = InvoiceIn(SUPPLIER, "INV/26-27/0042", date(2026, 4, 10), "29", Decimal("1000.00"),
                  Decimal("1180.00"), igst=Decimal("180.00"), recipient_gstin=BUYER)  # fmt: skip
# Intra-state (both 27): CGST + SGST.
INTRA = replace(INTER, place_of_supply="27", igst=ZERO, cgst=Decimal("90.00"),
                sgst=Decimal("90.00"))  # fmt: skip


def by_rule(checks: list[Check]) -> dict[str, Check]:
    return {c.rule: c for c in checks}


def test_a_good_invoice_passes_every_check() -> None:
    for inv in (INTER, INTRA):
        checks = by_rule(check(inv))
        assert set(checks) == {"required_fields", "supplier_gstin", "recipient_gstin",
                               "place_of_supply_format", "total", "tax_type"}  # fmt: skip
        assert all(c.ok for c in checks.values()), checks


def test_blank_fields_are_named() -> None:
    c = by_rule(check(replace(INTER, invoice_no=" ", place_of_supply="")))["required_fields"]
    assert not c.ok and c.message == "missing: invoice_no, place_of_supply"


def test_gstins_need_the_right_check_character() -> None:
    checks = by_rule(check(replace(INTER, recipient_gstin=BUYER[:-1] + "0")))
    assert checks["supplier_gstin"].ok and not checks["recipient_gstin"].ok
    wrong_check_char = replace(INTER, supplier_gstin="27AAPFU0939F1ZA")
    assert not by_rule(check(wrong_check_char))["supplier_gstin"].ok


def test_recipient_gstin_is_optional() -> None:
    checks = by_rule(check(replace(INTER, recipient_gstin=None)))
    assert "recipient_gstin" not in checks and all(c.ok for c in checks.values())


def test_place_of_supply_must_be_two_digits() -> None:
    checks = by_rule(check(replace(INTER, place_of_supply="KA")))
    assert not checks["place_of_supply_format"].ok
    assert "tax_type" not in checks  # cannot compare states without a state code


def test_total_tolerance_boundary_is_inclusive() -> None:
    at = by_rule(check(replace(INTER, invoice_total=Decimal("1181.00"))))["total"]
    over = by_rule(check(replace(INTER, invoice_total=Decimal("1181.01"))))["total"]
    assert at.ok and not over.ok
    assert over.message == "total 1181.01, taxable value + tax 1180.00 (difference +1.01)"
    off_by_a_paisa = replace(INTER, invoice_total=Decimal("1180.01"))
    assert by_rule(check(INTER, tolerance=ZERO))["total"].ok
    assert not by_rule(check(off_by_a_paisa, tolerance=ZERO))["total"].ok


def test_tax_type_inter_and_intra_state_and_marked_unverified() -> None:
    # Inter-state invoice charged CGST + SGST, and intra-state charged IGST: both flagged.
    wrong_inter = replace(INTRA, place_of_supply="29")
    wrong_intra = replace(INTER, place_of_supply="27")
    for inv, found in ((wrong_inter, "CGST + SGST"), (wrong_intra, "IGST")):
        c = by_rule(check(inv))["tax_type"]
        assert not c.ok and c.message.endswith(f"invoice has {found}"), c.message
        assert c.verified is False
    mixed = replace(INTER, cgst=Decimal("1.00"), invoice_total=Decimal("1181.00"))
    assert not by_rule(check(mixed))["tax_type"].ok


def test_no_tax_means_no_tax_type_check() -> None:
    exempt = replace(INTER, igst=ZERO, invoice_total=Decimal("1000.00"))
    checks = by_rule(check(exempt))
    assert "tax_type" not in checks and all(c.ok for c in checks.values())


# API


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


BODY = {
    "supplier_gstin": SUPPLIER,
    "recipient_gstin": BUYER,
    "invoice_no": "INV/26-27/0042",
    "invoice_date": "2026-04-10",
    "place_of_supply": "29",
    "taxable_value": "1000.00",
    "igst": "180.00",
    "invoice_total": "1180.00",
}


async def test_api_good_invoice(client: AsyncClient) -> None:
    r = await client.post("/check-invoice", json=BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["unverified_rules"] == ["tax_type"]
    assert {c["rule"] for c in body["checks"]} >= {"supplier_gstin", "total", "tax_type"}
    assert "not tax advice" in body["disclaimer"]


async def test_api_reports_each_failure(client: AsyncClient) -> None:
    bad = {**BODY, "place_of_supply": "27", "invoice_total": "1200.00"}
    body = (await client.post("/check-invoice", json=bad)).json()
    failed = {c["rule"] for c in body["checks"] if not c["ok"]}
    assert body["ok"] is False and failed == {"total", "tax_type"}


@pytest.mark.parametrize(
    "change",
    [
        {"invoice_date": "10/04/2026"},
        {"taxable_value": "-5"},
        {"igst": "1.005"},
        {"invoice_total": None},
        {"supplier_gstin": "X" * 21},
    ],
)
async def test_api_bad_body_is_422(client: AsyncClient, change: dict[str, object]) -> None:
    r = await client.post("/check-invoice", json={**BODY, **change})
    assert r.status_code == 422
