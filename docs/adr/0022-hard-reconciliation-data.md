# 22. Hard reconciliation data; a pairing problem is the label only when nothing else is wrong

Date: 2026-10-30
Status: Accepted

## Context

The matcher scored 1.0 on every label (ADR 0020), but the generator planted one problem
per invoice, of exactly the kinds the rules look for. ADR 0020 listed the known limits:
two problems on one invoice were never generated. M4.4 adds data that tests them.

## Decision

### Hard data

`python -m gst_copilot.recon.synth --hard` adds these cases to the easy mix (share of
invoices in brackets). The easy data of a seed does not change: seeds 1-10 at 150 and
200 invoices give byte-identical output with and without this change.

| Case | What is planted | The one right label |
|---|---|---|
| format+amount (5%) | number written differently and taxable value 10% lower in GSTR-2B | `amount_diff` |
| typo+amount (5%) | one GSTIN character wrong in the books and 10% lower in GSTR-2B | `amount_diff` |
| typo+period (5%) | one GSTIN character wrong in the books and a later GSTR-2B period | `period_diff` |
| twin_suppliers (5%) | another supplier (GSTIN 2+ characters apart), same number, date and amounts | `missing_in_2b` + `missing_in_books` |
| boundary_1.00 (3%) | taxable value exactly ₹1.00 higher in GSTR-2B | `matched` (tolerance is inclusive) |
| boundary_1.01 (3%) | taxable value ₹1.01 higher | `amount_diff` |

**Ground truth for two problems:** one label per invoice, as before. The pair gets the
label of its most serious problem, in the matcher's existing check order: ITC not
available, IGST vs CGST + SGST, amounts, period. A number or GSTIN written differently is
a data-entry problem, not a tax difference, so it is the label only when nothing else is
wrong. Every difference stays in `details` either way.

### Rule changes, one at a time

- **(a)** Rules 3 (number written differently) and 4 (GSTIN typo) check the pair like
  rule 2 does and keep their own label only when the pair would otherwise be `matched`.
- **(b)** Rule 4 no longer needs equal amounts: same normalised number, same date,
  GSTIN exactly one character apart. A typo and a wrong amount on one invoice are now
  paired and labelled `amount_diff`.

Why (b) is safe: the check character catches every single changed character at every
position (tested exhaustively for two GSTINs), so two valid GSTINs are never one
character apart. A one-character difference always means at least one side is mistyped.
Suppliers 2 or more characters apart are never paired (tested with equal and with
different amounts).

## Results

Seeds 1-10, 150 invoices each, counts added up:
`python -m gst_copilot.recon.score --seeds 1-10 --invoices 150 [--hard]`.

### Before any rule change

Easy data:

| Label | Expected | Predicted | Correct | Precision | Recall |
|---|---|---|---|---|---|
| matched | 910 | 910 | 910 | 1.0 | 1.0 |
| amount_diff | 90 | 90 | 90 | 1.0 | 1.0 |
| invoice_no_format | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_2b | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_books | 80 | 80 | 80 | 1.0 | 1.0 |
| period_diff | 80 | 80 | 80 | 1.0 | 1.0 |
| gstin_typo | 60 | 60 | 60 | 1.0 | 1.0 |
| tax_type | 60 | 60 | 60 | 1.0 | 1.0 |
| itc_unavailable | 40 | 40 | 40 | 1.0 | 1.0 |
| duplicate_in_books | 40 | 40 | 40 | 1.0 | 1.0 |
| all | 1540 | 1540 | 1540 | 1.0 | 1.0 |

Hard data:

| Label | Expected | Predicted | Correct | Precision | Recall |
|---|---|---|---|---|---|
| matched | 550 | 550 | 550 | 1.0 | 1.0 |
| amount_diff | 290 | 130 | 130 | 1.0 | 0.448 |
| invoice_no_format | 90 | 170 | 90 | 0.529 | 1.0 |
| missing_in_2b | 170 | 250 | 170 | 0.68 | 1.0 |
| missing_in_books | 160 | 240 | 160 | 0.667 | 1.0 |
| period_diff | 160 | 80 | 80 | 1.0 | 0.5 |
| gstin_typo | 60 | 140 | 60 | 0.429 | 1.0 |
| tax_type | 60 | 60 | 60 | 1.0 | 1.0 |
| itc_unavailable | 40 | 40 | 40 | 1.0 | 1.0 |
| duplicate_in_books | 40 | 40 | 40 | 1.0 | 1.0 |
| all | 1620 | 1700 | 1380 | 0.812 | 0.852 |

Where it failed (80 invoices each): format+amount labelled `invoice_no_format`;
typo+period labelled `gstin_typo`; typo+amount not paired at all (80 `missing_in_2b` +
80 `missing_in_books` too many). Twin suppliers and both ₹1.00 / ₹1.01 boundaries were
already right.

### After change (a)

Easy data: unchanged.

| Label | Expected | Predicted | Correct | Precision | Recall |
|---|---|---|---|---|---|
| matched | 910 | 910 | 910 | 1.0 | 1.0 |
| amount_diff | 90 | 90 | 90 | 1.0 | 1.0 |
| invoice_no_format | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_2b | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_books | 80 | 80 | 80 | 1.0 | 1.0 |
| period_diff | 80 | 80 | 80 | 1.0 | 1.0 |
| gstin_typo | 60 | 60 | 60 | 1.0 | 1.0 |
| tax_type | 60 | 60 | 60 | 1.0 | 1.0 |
| itc_unavailable | 40 | 40 | 40 | 1.0 | 1.0 |
| duplicate_in_books | 40 | 40 | 40 | 1.0 | 1.0 |
| all | 1540 | 1540 | 1540 | 1.0 | 1.0 |

Hard data:

| Label | Expected | Predicted | Correct | Precision | Recall |
|---|---|---|---|---|---|
| matched | 550 | 550 | 550 | 1.0 | 1.0 |
| amount_diff | 290 | 210 | 210 | 1.0 | 0.724 |
| invoice_no_format | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_2b | 170 | 250 | 170 | 0.68 | 1.0 |
| missing_in_books | 160 | 240 | 160 | 0.667 | 1.0 |
| period_diff | 160 | 160 | 160 | 1.0 | 1.0 |
| gstin_typo | 60 | 60 | 60 | 1.0 | 1.0 |
| tax_type | 60 | 60 | 60 | 1.0 | 1.0 |
| itc_unavailable | 40 | 40 | 40 | 1.0 | 1.0 |
| duplicate_in_books | 40 | 40 | 40 | 1.0 | 1.0 |
| all | 1620 | 1700 | 1540 | 0.906 | 0.951 |

Fixed format+amount and typo+period. Typo+amount is still unpaired.

### After change (b)

Easy data: unchanged.

| Label | Expected | Predicted | Correct | Precision | Recall |
|---|---|---|---|---|---|
| matched | 910 | 910 | 910 | 1.0 | 1.0 |
| amount_diff | 90 | 90 | 90 | 1.0 | 1.0 |
| invoice_no_format | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_2b | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_books | 80 | 80 | 80 | 1.0 | 1.0 |
| period_diff | 80 | 80 | 80 | 1.0 | 1.0 |
| gstin_typo | 60 | 60 | 60 | 1.0 | 1.0 |
| tax_type | 60 | 60 | 60 | 1.0 | 1.0 |
| itc_unavailable | 40 | 40 | 40 | 1.0 | 1.0 |
| duplicate_in_books | 40 | 40 | 40 | 1.0 | 1.0 |
| all | 1540 | 1540 | 1540 | 1.0 | 1.0 |

Hard data:

| Label | Expected | Predicted | Correct | Precision | Recall |
|---|---|---|---|---|---|
| matched | 550 | 550 | 550 | 1.0 | 1.0 |
| amount_diff | 290 | 290 | 290 | 1.0 | 1.0 |
| invoice_no_format | 90 | 90 | 90 | 1.0 | 1.0 |
| missing_in_2b | 170 | 170 | 170 | 1.0 | 1.0 |
| missing_in_books | 160 | 160 | 160 | 1.0 | 1.0 |
| period_diff | 160 | 160 | 160 | 1.0 | 1.0 |
| gstin_typo | 60 | 60 | 60 | 1.0 | 1.0 |
| tax_type | 60 | 60 | 60 | 1.0 | 1.0 |
| itc_unavailable | 40 | 40 | 40 | 1.0 | 1.0 |
| duplicate_in_books | 40 | 40 | 40 | 1.0 | 1.0 |
| all | 1620 | 1620 | 1620 | 1.0 | 1.0 |

## Consequences

- The 1.0 on hard data has the same weakness as ADR 0020's: the hard cases were written
  by the same person who wrote the rules, after reading them. It shows the three known
  limits of ADR 0020 are fixed and that twins and the tolerance boundary behave; it is
  not a claim about real books.
- Behaviour change in the API and CLI: a pair with a number written differently *and*
  another problem now shows the other problem as its label (before:
  `invoice_no_format`). Nothing is lost; the number difference is still in `details`.
- Still not handled (not generated):
  - a typo in the GSTIN *and* in the invoice number, or a typo plus a different date:
    shown as `missing_in_2b` + `missing_in_books`;
  - two different suppliers whose GSTINs are both mistyped into one-apart values:
    possible in theory, would be paired wrongly; needs real data to know if it happens;
  - credit and debit notes, amendments, partial invoices (as in ADR 0020).
