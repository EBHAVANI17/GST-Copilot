"""Reconcile two CSV files, optionally scoring against the ground truth.

    python -m gst_copilot.recon data/synthetic/recon-01
    python -m gst_copilot.recon --books my_register.csv --gstr2b my_2b.csv

A folder is read as purchase_register.csv + gstr2b.csv (+ expected.csv if present).
Writes reconciliation.csv next to the inputs (or to --out) and prints a summary.
"""

import argparse
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from gst_copilot.config import get_settings
from gst_copilot.recon.csvio import read_expected, read_invoices
from gst_copilot.recon.matcher import Result, reconcile, results_csv
from gst_copilot.recon.score import render, score


def write_results(path: Path, results: list[Result]) -> None:
    path.write_text(results_csv(results), encoding="utf-8", newline="")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reconcile the purchase register with GSTR-2B.")
    p.add_argument("folder", nargs="?", type=Path)
    p.add_argument("--books", type=Path)
    p.add_argument("--gstr2b", type=Path)
    p.add_argument("--expected", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--tolerance", type=str, help="rupees (default from settings: 1.0)")
    args = p.parse_args(argv)

    if args.folder:
        books_path = args.books or args.folder / "purchase_register.csv"
        twob_path = args.gstr2b or args.folder / "gstr2b.csv"
        expected_path = args.expected or args.folder / "expected.csv"
    elif args.books and args.gstr2b:
        books_path, twob_path, expected_path = args.books, args.gstr2b, args.expected
    else:
        p.error("give a folder, or --books and --gstr2b")
    tolerance = Decimal(args.tolerance or str(get_settings().recon_tolerance_rupees))

    books = read_invoices(books_path, "books")
    gstr2b = read_invoices(twob_path, "gstr2b")
    results = reconcile(books, gstr2b, tolerance)
    out = args.out or books_path.parent / "reconciliation.csv"
    try:
        write_results(out, results)
    except PermissionError:
        # Windows: Excel locks a file while it is open.
        print(f"Cannot write {out}: is it open in Excel? Close it and run again.", file=sys.stderr)
        return 1

    counts = Counter(r.label for r in results)
    print(f"Books: {len(books)} rows, GSTR-2B: {len(gstr2b)} rows, tolerance Rs {tolerance}")
    print("| Label | Invoices |\n|---|---|")
    for label, n in counts.most_common():
        print(f"| {label} | {n} |")
    print(f"\nWritten: {out}")
    if expected_path and expected_path.exists():
        print("\nScore against expected.csv:")
        print(render(score(results, read_expected(expected_path))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
