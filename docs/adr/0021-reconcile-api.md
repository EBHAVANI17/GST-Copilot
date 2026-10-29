# 21. POST /reconcile: uploads processed in memory, never stored

Date: 2026-10-29
Status: Accepted

## Context

The matcher (ADR 0020) runs from the command line. Users (an accountant, or a later
web page) need it over HTTP: upload two CSV files, get every invoice labelled.

## Decision

- `POST /reconcile` takes two multipart uploads, `purchase_register` and `gstr2b`, in
  the CSV formats of ADR 0019, plus optional `tolerance` (rupees, 0-100) and
  `format=json|csv`.
- JSON answer: row counts, invoices per label, total tax per label (books side, or
  GSTR-2B when the invoice is only there), and one result per invoice with GSTIN,
  invoice number, tax and all differences. Amounts are strings ("18000.50"), not
  floats. `format=csv` returns the same as the CLI's `reconciliation.csv` as a download.
- **Uploads are never stored**: a business's books are its private data. They are read
  in memory, and only counts per label are logged.
- Limits: 5 MB and 20,000 rows per file (413). A bad file gets 422 with the file name,
  line and column ("mine.csv line 2: invoice_date must be YYYY-MM-DD").
- New dependency: python-multipart (FastAPI needs it for file uploads).

## Consequences

- Stateless: the same upload always gives the same result; there is no history of
  reconciliations (a later feature, with consent and retention rules, if needed).
- Everything is in one request, fine for a month of a small business; a large company's
  year of invoices would need a background job instead.
