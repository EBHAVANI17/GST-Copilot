"""Synthetic books + GSTR-2B with planted mismatches and the ground truth.

    python -m gst_copilot.recon.synth --out data/synthetic/recon-01 --seed 1 --invoices 200

Writes purchase_register.csv, gstr2b.csv and expected.csv. Everything is made up:
fictional supplier names, GSTINs built from random letters (right shape and check
character, not taken from any real business), random amounts. The tax rates are
just a set of slab percentages to make realistic-looking numbers; they are not a
statement of which rate applies to which goods.

The same seed always gives the same files, so a matcher can be scored against
expected.csv exactly (precision and recall per label, M4.2).
"""

import argparse
import calendar
import random
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from gst_copilot.recon.csvio import write_expected, write_invoices
from gst_copilot.recon.gstin import ALPHABET, check_char
from gst_copilot.recon.models import ZERO, Expected, Invoice, Label

BUYER_STATE = "29"  # the fictional business is registered in Karnataka
OTHER_STATES = ["27", "33", "36", "07", "24"]
SLABS = [Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28")]
WORDS = ["Sunrise", "Lotus", "Indus", "Nilgiri", "Kaveri", "Deccan", "Coral", "Banyan",
         "Saffron", "Monsoon", "Granite", "Peacock", "Tulsi", "Harbor", "Meadow"]  # fmt: skip
KINDS = ["Traders", "Supplies", "Enterprises", "Industries", "Agencies", "Distributors"]

# Share of invoices that get each planted problem; the rest match.
MIX: dict[Label, float] = {
    "amount_diff": 0.06,
    "invoice_no_format": 0.06,
    "missing_in_2b": 0.06,
    "missing_in_books": 0.05,
    "period_diff": 0.05,
    "gstin_typo": 0.04,
    "tax_type": 0.04,
    "itc_unavailable": 0.03,
    "duplicate_in_books": 0.03,
}


def _money(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fake_gstin(rng: random.Random, state: str) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    pan = (
        "".join(rng.choice(letters) for _ in range(3))
        + "C"  # 4th PAN letter: company
        + rng.choice(letters)
        + f"{rng.randint(0, 9999):04d}"
        + rng.choice(letters)
    )
    first14 = f"{state}{pan}{rng.choice('123456789')}Z"
    return first14 + check_char(first14)


def gstin_typo(rng: random.Random, gstin: str) -> str:
    """Change one character of the PAN part (a typical typing mistake)."""
    i = rng.randint(2, 11)
    pool = "0123456789" if gstin[i].isdigit() else "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    new = rng.choice([c for c in pool if c != gstin[i]])
    return gstin[:i] + new + gstin[i + 1 :]


def reformat_invoice_no(rng: random.Random, no: str) -> str:
    """The same number written differently: separator, case, leading zeros."""
    prefix, year, seq = no.split("/")
    style = rng.randint(0, 2)
    if style == 0:
        return f"{prefix}-{year}-{int(seq)}"
    if style == 1:
        return f"{prefix.lower()}/{year}/{seq}"
    return f"{prefix} {year} {int(seq):06d}"


def _taxes(
    rng: random.Random, taxable: Decimal, inter_state: bool
) -> tuple[Decimal, Decimal, Decimal]:
    """(igst, cgst, sgst): IGST between states, CGST + SGST halves within one state."""
    tax = _money(taxable * rng.choice(SLABS) / 100)
    if inter_state:
        return tax, ZERO, ZERO
    half = _money(tax / 2)
    return ZERO, half, tax - half


def generate(
    seed: int = 1, invoices: int = 200, period: str = "2026-04", suppliers: int = 25
) -> tuple[list[Invoice], list[Invoice], list[Expected]]:
    rng = random.Random(seed)  # noqa: S311 - repeatable test data, not security
    year, month = (int(p) for p in period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    next_period = f"{year + month // 12}-{month % 12 + 1:02d}"

    vendors = []
    for i in range(suppliers):
        state = BUYER_STATE if rng.random() < 0.6 else rng.choice(OTHER_STATES)
        name = f"{rng.choice(WORDS)} {rng.choice(KINDS)} (synthetic {i + 1})"
        vendors.append((fake_gstin(rng, state), name, f"{rng.choice(ALPHABET[10:])}{i:02d}"))

    labels: list[Label] = []
    for label, share in MIX.items():
        labels += [label] * round(share * invoices)
    labels += ["matched"] * (invoices - len(labels))
    rng.shuffle(labels)

    books: list[Invoice] = []
    gstr2b: list[Invoice] = []
    expected: list[Expected] = []

    def add(rows: list[Invoice], inv: Invoice, prefix: str) -> str:
        row_id = f"{prefix}{len(rows) + 1:04d}"
        rows.append(replace(inv, row_id=row_id, source="books" if prefix == "R" else "gstr2b"))
        return row_id

    for n, label in enumerate(labels, start=1):
        gstin, name, code = rng.choice(vendors)
        inter = gstin[:2] != BUYER_STATE
        taxable = _money(Decimal(rng.randint(1_000_00, 5_00_000_00)) / 100)
        igst, cgst, sgst = _taxes(rng, taxable, inter)
        base = Invoice(
            row_id="",
            source="books",
            supplier_gstin=gstin,
            supplier_name=name,
            invoice_no=f"{code}/{year % 100}-{(year + 1) % 100}/{n:04d}",
            invoice_date=date(year, month, rng.randint(1, last_day)),
            taxable_value=taxable,
            igst=igst,
            cgst=cgst,
            sgst=sgst,
            period=period,
        )
        twob = replace(base, source="gstr2b")

        if label == "matched" and rng.random() < 0.2:
            # Rounding noise within the tolerance still counts as matched.
            twob = replace(twob, taxable_value=twob.taxable_value + Decimal("0.40"))
        elif label == "amount_diff":
            cut = _money(base.taxable_value * Decimal("0.9"))
            ig, cg, sg = _taxes(rng, cut, inter)
            twob = replace(twob, taxable_value=cut, igst=ig, cgst=cg, sgst=sg)
        elif label == "invoice_no_format":
            twob = replace(twob, invoice_no=reformat_invoice_no(rng, base.invoice_no))
        elif label == "period_diff":
            twob = replace(twob, period=next_period)
        elif label == "gstin_typo":
            base = replace(base, supplier_gstin=gstin_typo(rng, gstin))
        elif label == "tax_type":
            tax = base.total_tax
            if inter:  # books wrongly split it as CGST + SGST
                half = _money(tax / 2)
                base = replace(base, igst=ZERO, cgst=half, sgst=tax - half)
            else:  # books wrongly booked it as IGST
                base = replace(base, igst=tax, cgst=ZERO, sgst=ZERO)
        elif label == "itc_unavailable":
            twob = replace(twob, itc_available=False)

        if label == "missing_in_books":
            expected.append(Expected(None, add(gstr2b, twob, "B"), label))
        elif label == "missing_in_2b":
            expected.append(Expected(add(books, base, "R"), None, label))
        elif label == "duplicate_in_books":
            first, b_id = add(books, base, "R"), add(gstr2b, twob, "B")
            expected.append(Expected(first, b_id, "matched"))
            expected.append(Expected(add(books, base, "R"), None, label))
        else:
            expected.append(Expected(add(books, base, "R"), add(gstr2b, twob, "B"), label))

    # Real files are not in matching order.
    rng.shuffle(books)
    rng.shuffle(gstr2b)
    return books, gstr2b, expected


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write synthetic reconciliation data.")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--invoices", type=int, default=200)
    p.add_argument("--period", default="2026-04", help="YYYY-MM")
    args = p.parse_args(argv)
    books, gstr2b, expected = generate(args.seed, args.invoices, args.period)
    args.out.mkdir(parents=True, exist_ok=True)
    write_invoices(args.out / "purchase_register.csv", books, "books")
    write_invoices(args.out / "gstr2b.csv", gstr2b, "gstr2b")
    write_expected(args.out / "expected.csv", expected)
    counts: dict[str, int] = {}
    for e in expected:
        counts[e.label] = counts.get(e.label, 0) + 1
    print(f"Wrote {len(books)} book rows, {len(gstr2b)} GSTR-2B rows to {args.out}")
    print("| Label | Invoices |\n|---|---|")
    for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"| {label} | {n} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
