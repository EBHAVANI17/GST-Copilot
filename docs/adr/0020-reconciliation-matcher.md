# 20. Reconciliation matcher: ordered rules, one label per invoice, all differences kept

Date: 2026-10-29
Status: Accepted; rules 3 and 4 amended by ADR 0022 (combined problems)

## Context

M4.1 (ADR 0019) defined ten labels and a synthetic generator that writes the right
label for every invoice. M4.2 needs the code that finds them in two unordered files.

## Decision

Plain rules in a fixed order; each pass only sees rows no earlier pass used:

1. **Duplicates in the books:** same supplier GSTIN, invoice number (normalised),
   date, taxable value and tax. The first entry stays; the others are
   `duplicate_in_books`.
2. **Exact pair:** same GSTIN and the same invoice number as written.
3. **Format difference:** same GSTIN, same invoice number after normalising (upper
   case, separators removed, leading zeros dropped: "INV/0042" = "inv-42").
4. **GSTIN typo:** same normalised number, date and amounts; GSTIN differs in exactly
   one character. Two or more characters = a different supplier, not a typo.
5. **Left over:** `missing_in_2b` (books only) or `missing_in_books` (GSTR-2B only).

A pair from step 2 is labelled by the first problem found, in this order: ITC not
available, IGST vs CGST + SGST (same total), amounts beyond the tolerance (₹1,
inclusive, `RECON_TOLERANCE_RUPEES`), different period; otherwise `matched`. Every
difference (amounts books minus GSTR-2B, period, number, GSTIN, check character) is
kept in `details`, so a second problem is visible even though only one label is set.

`python -m gst_copilot.recon <folder>` writes `reconciliation.csv` and, when the
folder has `expected.csv`, prints precision and recall per label.

## Results

Synthetic data, seeds 1-10 (150 invoices each) and seed 1 with 200 invoices:
precision and recall 1.0 for every label.

## Consequences

- 1.0 is not a claim about real books. The generator plants one problem per invoice,
  of exactly the kinds the rules look for; the rules and the generator were written
  together. It proves the rules do what they say, nothing more.
- Known limits (combined problems, not generated yet):
  - format + amount difference: labelled `invoice_no_format`; the amount difference is
    only in `details`.
  - GSTIN typo + amount difference: the typo rule needs equal amounts, so the invoice
    shows up as `missing_in_2b` + `missing_in_books`.
  - credit and debit notes, amendments, partial invoices: out of scope for M4.
- A harder generator (two problems per invoice, near-identical invoices of different
  suppliers) is the next way to find where the rules break.
