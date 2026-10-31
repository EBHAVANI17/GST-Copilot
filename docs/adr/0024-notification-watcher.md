# 24. Keeping the corpus fresh: a daily manual check and one ingest command (design)

Date: 2026-10-30
Status: Accepted (follow-up 1 implemented)

## Context

M5 target: a new CBIC notification or circular is answerable within 24 hours of its
publication. Today the corpus changes only when the owner edits `corpus/manifest.csv`
and runs ingest by hand, with no schedule and no record of how fresh the index is.

What already exists (checked in the code):

- `python -m gst_copilot.ingest corpus/manifest.csv` and the worker job `ingest`
  (`worker.py`, arq on Redis) load every manifest row.
- Ingest is idempotent: each document's file hash and chunker version are stored;
  unchanged documents are skipped, changed ones are re-chunked, rows removed from the
  manifest are deleted from the index (`ingest/pipeline.py`).
- The manifest accepts `doc_type` notification and circular, and stores `issued_on`,
  `effective_from` and `effective_to` (`ingest/manifest.py`).
- **Gap:** the effective dates are stored on each document but no retrieval code uses
  them yet (`rag/` never reads them). A superseded document is still retrieved.

## Decision

### The process (owner, every working day)

1. Check the official notification and circular pages (CBIC GST site; GST Council site
   for its documents). Only official sources, as the corpus README says.
2. For each new document: save the PDF in `corpus/raw/`; add one manifest row with
   `doc_type`, `title`, `source_url`, `issued_on` and `effective_from` copied from the
   document itself.
3. If the new document says it replaces or rescinds an earlier one, set `effective_to`
   on that earlier row. Do not delete the row: the history stays answerable by date
   once retrieval uses the dates (follow-up 2).
4. Run `python -m gst_copilot.ingest corpus/manifest.csv` (or enqueue the `ingest` job).
   Only the new or changed files are processed.
5. Run `python -m gst_copilot.evals.check evals\golden.jsonl` and the golden eval
   `--retrieval-only` to see nothing broke. Never the holdout set.
6. Commit the manifest change through a PR (`corpus: add <doc_id>`): the manifest is the
   record of what the index contains and since when.

The 24-hour target is measured as: date of the merged manifest commit minus `issued_on`.

### Why not an automatic downloader

- The structure and terms of use of the official sites are not verified here, and a
  scraper that breaks silently is worse than a daily manual check, because it makes the
  corpus look fresh when it is not.
- Every document must be read by a person anyway, to set `effective_from` and
  `effective_to` correctly. A wrong date is a wrong legal answer.
- Revisit once the manual process has run for some weeks and its cost is known.

### Follow-ups (each its own task, PR and tests)

1. `python -m gst_copilot.ingest.freshness`: prints the newest `issued_on` in the
   manifest and the days since; `/ready` reports `corpus_date` and `corpus_freshness_days`.
   *(Implemented in `gst_copilot.ingest.freshness` and `gst_copilot.api.health`)*
2. Date-aware retrieval: filter chunks by `effective_from` / `effective_to` against the
   date the question is about (today by default). Needs its own ADR and an eval run
   before and after.
3. Optional: a small checklist file the owner ticks daily (date, checked, new documents),
   to show the target was met.

## Consequences

- Freshness depends on the owner checking daily. Missed days show up in follow-up 1.
- Until follow-up 2, adding a newer document does not hide the older one. An answer may
  cite both; the citation check still shows which documents were used.
- No law content is in this ADR: which documents to add is decided by reading the
  official publications.
