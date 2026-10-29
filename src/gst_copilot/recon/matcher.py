"""Match the books against GSTR-2B and label every invoice (ADR 0019, 0020).

Plain rules in a fixed order; each pass only sees rows no earlier pass used:

1. duplicates in the books: same supplier, invoice number, date and amounts twice
2. same supplier GSTIN and the same invoice number, written the same way
3. same supplier GSTIN, same invoice number written differently ("INV/0042" = "inv-42")
4. same invoice number and date, GSTIN one character different (a typo)
5. whatever is left: missing in GSTR-2B, or missing in the books

A matched pair is then checked in this order: ITC not available, IGST vs CGST + SGST,
amounts, period. The first problem found is the label; a number or GSTIN written
differently (rules 3 and 4) is the label only when none of these is found (ADR 0022).
All differences are kept in `diffs` so nothing is hidden.
"""

import csv
import io
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from gst_copilot.recon.gstin import is_valid
from gst_copilot.recon.models import Invoice, Label

_TOKEN = re.compile(r"[A-Z0-9]+")


def invoice_key(invoice_no: str) -> str:
    """Invoice number without case, separators and leading zeros:
    "J24/26-27/0087", "j24/26-27/0087" and "J24 26-27 000087" -> "J24|26|27|87"."""
    tokens = _TOKEN.findall(invoice_no.upper())
    return "|".join(t.lstrip("0") or "0" if t.isdigit() else t for t in tokens)


def _one_char_apart(a: str, b: str) -> bool:
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) == 1


@dataclass(frozen=True)
class Result:
    books_id: str | None
    gstr2b_id: str | None
    label: Label
    diffs: dict[str, str] = field(default_factory=dict, compare=False)


def _diffs(b: Invoice, g: Invoice) -> dict[str, str]:
    out: dict[str, str] = {}
    if b.taxable_value != g.taxable_value:
        out["taxable_value"] = f"{b.taxable_value - g.taxable_value:+.2f}"  # books minus 2B
    if b.total_tax != g.total_tax:
        out["total_tax"] = f"{b.total_tax - g.total_tax:+.2f}"
    if (b.igst > 0) != (g.igst > 0):
        out["tax_type"] = f"books {_kind(b)}, GSTR-2B {_kind(g)}"
    if b.period != g.period:
        out["period"] = f"books {b.period}, GSTR-2B {g.period}"
    if b.invoice_no != g.invoice_no:
        out["invoice_no"] = f"books {b.invoice_no!r}, GSTR-2B {g.invoice_no!r}"
    if b.supplier_gstin != g.supplier_gstin:
        out["supplier_gstin"] = f"books {b.supplier_gstin}, GSTR-2B {g.supplier_gstin}"
        if not is_valid(b.supplier_gstin):
            out["books_gstin_check"] = "invalid check character"
    if not g.itc_available:
        out["itc_available"] = "N"
    return out


def _kind(inv: Invoice) -> str:
    return "IGST" if inv.igst > 0 else "CGST+SGST"


def classify(b: Invoice, g: Invoice, tolerance: Decimal) -> Label:
    """Label for a pair already known to be the same invoice."""
    if not g.itc_available:
        return "itc_unavailable"
    if (b.igst > 0) != (g.igst > 0) and abs(b.total_tax - g.total_tax) <= tolerance:
        return "tax_type"
    if (
        abs(b.taxable_value - g.taxable_value) > tolerance
        or abs(b.total_tax - g.total_tax) > tolerance
    ):
        return "amount_diff"
    if b.period != g.period:
        return "period_diff"
    return "matched"


def reconcile(
    books: Iterable[Invoice], gstr2b: Iterable[Invoice], tolerance: Decimal = Decimal("1.00")
) -> list[Result]:
    books_left = sorted(books, key=lambda r: r.row_id)
    twob_left = sorted(gstr2b, key=lambda r: r.row_id)
    results: list[Result] = []

    # 1. Duplicates in the books (the first entry stays to be matched).
    seen: dict[tuple[str, str, object, Decimal, Decimal], Invoice] = {}
    unique: list[Invoice] = []
    for b in books_left:
        k = (b.supplier_gstin, invoice_key(b.invoice_no), b.invoice_date, b.taxable_value,
             b.total_tax)  # fmt: skip
        if k in seen:
            results.append(Result(b.row_id, None, "duplicate_in_books",
                                  {"duplicate_of": seen[k].row_id}))  # fmt: skip
        else:
            seen[k] = b
            unique.append(b)
    books_left = unique

    Key = Callable[[Invoice], object]

    def pair_up(key_b: Key, key_g: Key, label_if_matched: Label | None = None) -> None:
        nonlocal books_left, twob_left
        index: dict[object, list[Invoice]] = {}
        for g in twob_left:
            index.setdefault(key_g(g), []).append(g)
        used_g: set[str] = set()
        rest: list[Invoice] = []
        for b in books_left:
            candidates = [g for g in index.get(key_b(b), []) if g.row_id not in used_g]
            if not candidates:
                rest.append(b)
                continue
            g = candidates[0]
            used_g.add(g.row_id)
            label = classify(b, g, tolerance)
            if label == "matched" and label_if_matched:
                label = label_if_matched
            results.append(Result(b.row_id, g.row_id, label, _diffs(b, g)))
        books_left = rest
        twob_left = [g for g in twob_left if g.row_id not in used_g]

    # 2. Exact invoice number and GSTIN.
    pair_up(lambda r: (r.supplier_gstin, r.invoice_no), lambda r: (r.supplier_gstin, r.invoice_no))
    # 3. Same GSTIN, same number written differently.
    pair_up(
        lambda r: (r.supplier_gstin, invoice_key(r.invoice_no)),
        lambda r: (r.supplier_gstin, invoice_key(r.invoice_no)),
        "invoice_no_format",
    )
    # 4. GSTIN typo: same number and date, GSTIN one character off. Amounts may differ
    # (then it is labelled amount_diff); two valid GSTINs are never one character apart.
    rest = []
    for b in books_left:
        match = next(
            (
                g
                for g in twob_left
                if invoice_key(g.invoice_no) == invoice_key(b.invoice_no)
                and g.invoice_date == b.invoice_date
                and _one_char_apart(b.supplier_gstin, g.supplier_gstin)
            ),
            None,
        )
        if match is None:
            rest.append(b)
        else:
            twob_left.remove(match)
            label = classify(b, match, tolerance)
            label = "gstin_typo" if label == "matched" else label
            results.append(Result(b.row_id, match.row_id, label, _diffs(b, match)))
    books_left = rest

    # 5. Left over.
    results += [Result(b.row_id, None, "missing_in_2b") for b in books_left]
    results += [Result(None, g.row_id, "missing_in_books") for g in twob_left]
    return results


def results_csv(results: Iterable[Result]) -> str:
    """The reconciliation as CSV text: one row per invoice, all differences in details."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["books_id", "gstr2b_id", "label", "details"])
    for r in results:
        details = "; ".join(f"{k}: {v}" for k, v in r.diffs.items())
        w.writerow([r.books_id or "", r.gstr2b_id or "", r.label, details])
    return out.getvalue()
