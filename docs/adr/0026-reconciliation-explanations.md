# 26. Reconciliation mismatch explanations: statutory citations and GSTR-3B Table 4 placement

Date: 2026-10-30
Status: Accepted

## Context

M4 adds ITC reconciliation (ADR 0019, 0020, 0021, 0022). ADR 0019 established the core
architecture: "Deterministic rules decide; a model only explains." The matcher assigns
one of 10 labels to every invoice in the purchase register and GSTR-2B.

Accountants and business users need to know:
1. What each mismatch label actually means.
2. What specific action should be taken.
3. Where the invoice belongs in the statutory Form GSTR-3B (Table 4).
4. The legal statutory authority (CGST Act, CGST Rules, or CBIC Circular).

ADR 0019 noted that explanations citing Section 16(2)(aa) (mandatory appearance in GSTR-2B)
and Circular 170/02/2022-GST require these sources to be present in the corpus first.
Circular 170 has now been indexed in the corpus (`CIRC-170-2022`).

## Decision

1. **Deterministic explanation mapping (`gst_copilot.recon.explain`):**
   Every one of the 10 reconciliation labels is mapped to a `LabelExplanation` dataclass:
   - `title`: Short descriptive name.
   - `explanation`: Plain-language explanation of the match or discrepancy.
   - `action`: Concrete compliance action for the business / taxpayer.
   - `gstr3b_row`: Exact statutory row in Table 4 of Form GSTR-3B, grounded in Circular 170/02/2022-GST and the GSTN 02.09.2022 advisory (Notification 14/2022-CT).
   - `citation`: Statutory provisions (e.g. s.16(2)(aa), r.36(4), s.16(2)(b), Circular 170).

2. **Integration with `POST /reconcile`:**
   `ReconcileResponse` includes an `explanations: dict[str, ExplanationResponse]` field
   containing the explanation for every label that appears in the reconciliation `summary`.
   This allows client applications and web UIs to show immediate, authoritative statutory
   reasons and filing instructions without requiring an LLM call.

3. **Integration with CLI:**
   `python -m gst_copilot.recon` accepts `--explain` to print a detailed statutory
   guidance table alongside the summary counts.

4. **Rule for `amount_diff` Invoices:**
   In accordance with statutory conservatism:
   - If Books < GSTR-2B: Claim only up to the internal books figure in Table 4(A)(5),
     reversing any excess in Table 4(B)(2) (others).
   - If GSTR-2B < Books: Claim is capped by GSTR-2B in Table 4(A)(5); remaining credit
     is held until the supplier files an amendment via GSTR-1.

## Consequences

- Every reconciliation output now carries actionable tax guidance grounded directly in
  official CBIC instructions.
- Zero latency overhead: explanations are static lookups, maintaining the high performance
  of the reconciliation engine.
- Sets the statutory foundation for Milestone M4b (Draft GSTR-3B compilation).
