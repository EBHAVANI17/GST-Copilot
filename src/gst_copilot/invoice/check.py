"""Check one invoice: required fields, GSTINs, total and tax type (ADR 0023).

Every rule gives a Check, passed or not, so the answer shows what was checked as well
as what failed. A rule that is not yet verified against the official law text says so
(verified=False); its result is a hint, not a finding.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from gst_copilot.recon.gstin import is_valid, state_code
from gst_copilot.recon.models import ZERO

_STATE = re.compile(r"^[0-9]{2}$")


@dataclass(frozen=True)
class InvoiceIn:
    supplier_gstin: str
    invoice_no: str
    invoice_date: date
    place_of_supply: str  # 2-digit state code, as in the GSTIN
    taxable_value: Decimal
    invoice_total: Decimal
    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    recipient_gstin: str | None = None  # absent for a sale to an unregistered buyer


@dataclass(frozen=True)
class Check:
    rule: str
    ok: bool
    message: str
    verified: bool = True  # False: the rule itself still needs the owner's check


def check(inv: InvoiceIn, tolerance: Decimal = Decimal("1.00")) -> list[Check]:
    checks = [_required(inv), _gstin("supplier_gstin", inv.supplier_gstin)]
    if inv.recipient_gstin:
        checks.append(_gstin("recipient_gstin", inv.recipient_gstin))
    pos_ok = bool(_STATE.match(inv.place_of_supply.strip()))
    checks.append(
        Check("place_of_supply_format", pos_ok,
              "two-digit state code" if pos_ok else
              f"place of supply {inv.place_of_supply!r} is not a two-digit state code")
    )  # fmt: skip
    checks.append(_total(inv, tolerance))
    # No tax on the invoice (e.g. exempt goods): nothing to say about its type.
    if pos_ok and is_valid(inv.supplier_gstin) and inv.igst + inv.cgst + inv.sgst > 0:
        checks.append(_tax_type(inv))
    return checks


def _required(inv: InvoiceIn) -> Check:
    blank = [
        name
        for name in ("supplier_gstin", "invoice_no", "place_of_supply")
        if not getattr(inv, name).strip()
    ]
    if blank:
        return Check("required_fields", False, f"missing: {', '.join(blank)}")
    return Check("required_fields", True, "all present")


def _gstin(rule: str, gstin: str) -> Check:
    if is_valid(gstin):
        return Check(rule, True, "valid format and check character")
    return Check(rule, False, f"{gstin!r}: wrong format or check character")


def _total(inv: InvoiceIn, tolerance: Decimal) -> Check:
    expected = inv.taxable_value + inv.igst + inv.cgst + inv.sgst
    diff = inv.invoice_total - expected
    if abs(diff) <= tolerance:
        return Check("total", True, f"total {inv.invoice_total:.2f} = taxable value + tax")
    return Check(
        "total",
        False,
        f"total {inv.invoice_total:.2f}, taxable value + tax {expected:.2f} "
        f"(difference {diff:+.2f})",
    )


def _tax_type(inv: InvoiceIn) -> Check:
    # UNVERIFIED - owner to check against the IGST Act (ADR 0023): supplier state other
    # than the place of supply -> IGST only; the same state -> CGST + SGST only. There
    # may be exceptions (for example supplies to SEZ units); none is implemented here.
    inter = state_code(inv.supplier_gstin.strip().upper()) != inv.place_of_supply.strip()
    has_igst = inv.igst > 0
    has_split = inv.cgst > 0 or inv.sgst > 0
    if inter:
        ok = has_igst and not has_split
        want = "IGST only (supplier state differs from place of supply)"
    else:
        ok = has_split and not has_igst
        want = "CGST + SGST only (supplier state is the place of supply)"
    found = " + ".join(
        n for n, v in (("IGST", inv.igst), ("CGST", inv.cgst), ("SGST", inv.sgst)) if v > 0
    )
    message = want if ok else f"expected {want}; invoice has {found or 'no tax'}"
    return Check("tax_type", ok, message, verified=False)
