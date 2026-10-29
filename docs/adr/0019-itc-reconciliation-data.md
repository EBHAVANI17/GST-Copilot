# 19. ITC reconciliation (M4): data formats, mismatch labels, synthetic ground truth

Date: 2026-10-29
Status: Accepted

## Context

M4 adds ITC reconciliation: compare the business's purchase register (the books) with
GSTR-2B (the statement of invoices its suppliers reported) and explain every
difference. The project uses synthetic transaction data only, never client or
employer data.

## Decision

- **Two input CSVs**, our own documented formats (a simplified B2B view, not a copy
  of the portal's download): `purchase_register.csv` (supplier GSTIN and name,
  invoice number and date, taxable value, IGST, CGST, SGST, books period) and
  `gstr2b.csv` (the same fields plus return period and ITC available Y/N). Amounts
  are Decimal, never float; dates YYYY-MM-DD; a bad row fails with file, line, column.
- **Ten labels** the reconciliation must assign: matched, amount_diff,
  invoice_no_format, missing_in_2b, missing_in_books, period_diff, gstin_typo,
  tax_type (IGST vs CGST + SGST), itc_unavailable, duplicate_in_books.
- **Deterministic rules decide; a model only explains.** Matching (M4.2) is plain
  Python, so every number is exact and testable. An LLM may later turn a result into
  plain language with a law citation (M4.4).
- **Synthetic generator with ground truth** (`python -m gst_copilot.recon.synth`):
  seeded, so the same seed gives the same files. It plants each problem in a known
  share of invoices and writes `expected.csv` with the right label for every row, so
  the matcher is scored with precision and recall per label, exactly.
- Synthetic GSTINs have the right shape and check character but random letters;
  supplier names say "(synthetic N)". Tax rates are a set of slab percentages used
  only to make realistic amounts, not a statement of which rate applies to what.
- **Rounding tolerance: ₹1 per invoice** (default, configurable in M4.2). 20% of
  matched invoices carry a ₹0.40 difference to test it.

## Consequences

- Scores on synthetic data show the rules work on the planted problem types; real
  books have messier problems (credit notes, partial invoices, amendments), which
  are out of scope for M4 and listed as gaps.
- The corpus CGST Act is the CBIC version "as on 31.08.2021": section 16(2) has no
  clause (aa), so explanations that cite it need the current Act first (before M4.4).
