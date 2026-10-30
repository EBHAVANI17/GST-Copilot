# 23. Invoice checker: format and arithmetic rules; tax-type rule unverified

Date: 2026-10-30
Status: Accepted, except the tax-type rule: **unverified — owner to check** before merge

## Context

Feature 3 of the README: check one invoice before it is booked or filed. The checks must
be plain rules whose answers can be tested, like the reconciliation (ADR 0020). The law
corpus has the CGST Act and Rules only; the IGST Act is not in it.

## Decision

`POST /check-invoice` takes one invoice as JSON (amounts as text or numbers, never
negative, at most 2 decimals) and answers with every check that ran, passed or not:

| Rule | What it checks | Source |
|---|---|---|
| `required_fields` | supplier GSTIN, invoice number and place of supply are not blank | format |
| `supplier_gstin`, `recipient_gstin` | shape and check character (`recon/gstin.py`); recipient only if given | format |
| `place_of_supply_format` | a two-digit code | format |
| `total` | invoice total = taxable value + IGST + CGST + SGST, within ₹1 (`RECON_TOLERANCE_RUPEES`, inclusive) | arithmetic |
| `tax_type` | supplier state (GSTIN digits 1-2) ≠ place of supply → IGST only; same state → CGST + SGST only | **unverified** |

- `tax_type` is returned with `verified: false`, and its name is listed in
  `unverified_rules`, so a client can show it as a hint, not a finding. It runs only when
  the supplier GSTIN is valid, the place of supply is two digits and the invoice has tax.
- Not checked: tax rates per item (no verified rate table), whether CGST equals SGST, and
  whether a two-digit code is a real state code (a code table from memory would be a law
  claim). Nothing about the invoice is stored or logged except which rules failed.

### For the owner to verify against the IGST Act (official CBIC text) before merging

1. The basic rule: supply between two states → IGST; within one state → CGST + SGST
   (IGST Act sections on inter-State and intra-State supply; check the section numbers).
2. Possible exceptions to "same state = CGST + SGST", **none implemented**:
   - supplies to or by a unit or developer in a Special Economic Zone (SEZ);
   - exports and imports;
   - any other case the Act treats as inter-State although both parties are in one state.
3. Whether the place-of-supply code should be compared with the supplier's state from
   the GSTIN, or with another field of the invoice.

If an exception applies, the plan is: add an input field for it (for example "supply to
SEZ") and skip or change `tax_type` for that case, with a test; never infer it.

## Consequences

- An invoice that falls under an exception will be flagged by `tax_type` wrongly until
  the exceptions are verified and added. The flag is marked unverified for that reason.
- The format and arithmetic rules are exact and need no legal check.
- Synthetic test data only (`tests/test_invoice_check.py`): one GSTIN from the GST format
  example and one built with a made-up PAN and the right check character.
