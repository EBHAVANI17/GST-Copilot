# Daily Notification Check Log (M5, ADR 0024)

Target: All relevant CBIC GST notifications and circulars indexed within 24 hours of official publication.

---

## Daily Routine (Every Working Day)

1. **Check official sources:**
   - **CBIC Central Tax Notifications:** https://cbic-gst.gov.in/central-tax-notifications.html
   - **CBIC Circulars:** https://cbic-gst.gov.in/circulars.html
   - **GST Council Notifications & Circulars:** https://www.gstcouncil.gov.in/
2. **For any new relevant notification or circular:**
   - Download the official PDF into `corpus/raw/<filename>.pdf`.
   - Add a row to `corpus/manifest.csv` with `doc_id`, `doc_type`, `title`, `source_url`, `issued_on`, `effective_from`, and `file`.
   - If the new document supersedes an existing one, update `effective_to` on that prior document in `manifest.csv`.
3. **Run local ingestion & evaluation checks:**
   ```bash
   python -m gst_copilot.ingest corpus/manifest.csv
   python -m gst_copilot.evals.check evals/golden.jsonl corpus/manifest.csv
   python -m gst_copilot.ingest.freshness
   ```
4. **Log below and open a PR** (`corpus: add <doc_id>`).

---

## Inspection Log

| Date Checked | Checked By | Portal(s) Inspected | New Documents Found | Manifest PR | Notes |
|---|---|---|---|---|---|
| 2026-10-30 | Bhavani | CBIC Notifications & Circulars | `CIRC-170-2022` | #29 | Circular No. 170/02/2022-GST on GSTR-3B return mapping |
| 2026-10-31 | Bhavani | CBIC & GST Council Portals | None | – | Freshness verified: 4 docs in corpus (`CIRC-193-2023` latest) |
