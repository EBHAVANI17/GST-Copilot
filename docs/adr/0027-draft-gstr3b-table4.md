# 27. Draft GSTR-3B Table 4: Return Preparation from Reconciliation (Milestone M4b)

Date: 2026-10-31
Status: Accepted

## Context

The repository scope (README) defines return preparation as:
*"A traceable draft GSTR-3B (drafts only; it never files returns). Built on public law documents and synthetic transaction data."*

Following the statutory reconciliation rules in ADR 0020, 0022, and 0026, taxpayers need
to translate invoice reconciliation into the statutory numbers required for **Form GSTR-3B
Table 4 (Eligible ITC)** under CBIC Circular No. 170/02/2022-GST (dated 06.07.2022) and
the GSTN advisory on Table 4 changes (Notification No. 14/2022-CT).

Key requirements:
1. Complete mathematical accuracy across tax heads (IGST, CGST, SGST, Cess).
2. Strict adherence to statutory rules for auto-population, temporary reversals, permanent
   reversals, reclaims, and exclusions.
3. Complete invoice-level audit traceability: every rupee in every row must trace back
   to the exact underlying invoice IDs in books or GSTR-2B.

## Decision

1. **Compilation Engine (`gst_copilot.recon.gstr3b`):**
   - Implemented `compile_table4(books, twob, results) -> DraftTable4`.
   - `TaxBreakdown` handles Decimal precision and head-by-head arithmetic.
   - Each row is a `Table4Row` containing the tax breakdown, invoice count, and
     `invoice_refs` (list of row IDs) for full audit traceability.

2. **Statutory Mapping Rules:**
   - **4(A)(5) All other ITC:** Gross auto-populated inward supplies from GSTR-2B
     where credit is available (including matched, format variations, typos, period diffs,
     and unrecorded invoices). Excludes `itc_unavailable` and `missing_in_2b`.
   - **4(B)(1) Permanent Reversals:** Blocked/ineligible credits under Section 17(5) and
     Rules 38, 42, 43.
   - **4(B)(2) Temporary Reversals:**
     - Invoices in GSTR-2B but unentered in books (`missing_in_books`), temporarily reversed
       under s.16(2)(b) because goods/services are not yet received.
     - Excess tax where GSTR-2B > Books on `amount_diff`.
     - Conflicting Place of Supply entries (`tax_type`).
   - **4(C) Net ITC Available:** Mathematically computed as `4(A) - [4(B)(1) + 4(B)(2)]`.
     This is the net credit that flows into the Electronic Credit Ledger.
   - **4(D)(1) Reclaimed ITC:** Reclaimed credit previously reversed in 4(B)(2) (`period_diff`).
   - **4(D)(2) Ineligible ITC:** Invoices with `itc_available == False` (`itc_unavailable`).
     Excluded from 4(A) and reported strictly for disclosure under s.16(4) / PoS.
   - **Excluded from Return:** Invoices missing in GSTR-2B (`missing_in_2b`) are held out
     completely under s.16(2)(aa) & Rule 36(4).

3. **API Integration (`POST /reconcile`):**
   `ReconcileResponse` includes `draft_3b: DraftGSTR3BResponse` containing the full Table 4
   breakdown with audit traceability and statutory disclaimer.

4. **CLI Integration:**
   `python -m gst_copilot.recon <folder> --gstr3b` renders the compiled Table 4 return
   as a markdown table.

## Consequences

- Full completion of Milestone M4b.
- Transparent and auditable draft return compilation: users and accountants can trace every
  figure back to the source invoices.
- No direct filing capability is built: the application remains strictly a drafting and
  compliance aid.
