# 4. Structure-aware chunking and section-level evaluation

Date: 2026-10-25
Status: Accepted

## Context

The M1 baseline (fixed 1,200-character windows, vector search) scored hit@5 0.875 on
the first golden set, but that number is document-level: with three documents,
finding "the right document" is easy. Error analysis of the one miss (q008, s.16(3)
on depreciation) and of a generated answer showed:

- chunks crossed section boundaries, so a short sub-section was diluted inside a
  chunk that was mostly about other sub-sections;
- running page headers ("CHAPTER V INPUT TAX CREDIT") and amendment footnotes
  ("111 Substituted w.e.f. ...") were embedded together with the law text;
- a chunk did not say which section it came from, so neither the embedding nor
  the LLM knew the context.

## Decisions

1. **Chunk by section.** Headings like "16. Eligibility and conditions ... .—(1)"
   start a new chunk. A section longer than the size limit is split at its
   sub-sections "(1)", "(2)", ...; a single huge sub-section falls back to windows.
2. **Context header on every chunk**, e.g. "Section 16. Eligibility and conditions
   for taking input tax credit", so a small piece still says what it is about.
3. **Strip noise** before chunking: repeated short lines (page headers), amendment
   footnote lines and footnote markers ("]67").
4. **Store the section number** on each chunk and a chunker version on each
   document. A changed chunker version re-chunks the document on the next ingest,
   even when the file itself has not changed.
5. **Section-level evaluation.** Golden items may list `expected_sections`; the
   report adds section_hit@k and section MRR next to document-level metrics.
6. **Keep the baseline switchable** (`CHUNKING_STRATEGY=fixed`) so every later change
   can be compared against it on the same golden set.

## Options rejected

- An LLM to split documents ("semantic chunking"): slow, costs money, and not
  reproducible. Indian statutes already have reliable structure.
- A layout parser (headings from font sizes): more accurate for some PDFs, but adds
  a heavy dependency. Revisit if regex headings fail on new document types.

## Consequences

- Heading detection is a regex tuned to CBIC Act/Rules PDFs. Circulars and
  notifications fall back to fixed windows. `ingest --dry-run` shows how each
  document was split, so failures are visible before indexing.
- Section numbers are not unique across documents (Act s.16 vs Rule 16), so
  evaluation matches the pair (document, section).
