# 10. Repair words broken by PDF extraction

Date: 2026-10-26
Status: Proposed (confirm on the golden set)

## Context

After section expansion (ADR 0008), the only expected phrases still missing from
the context were caused by pypdf, not retrieval:

- q003: the text reads "date of issue o f invoice" (a space inside "of").
- q008: the text reads "Income -\ntax Act" (a space before a line-break hyphen).

The dry run showed more of the same: "it sh all", "t he", "und er", "det ails".

## Decision

A repair step before chunking (section chunker v3, so documents re-chunk):

1. "word -\nword" and "word -word" become "word-word" ("Income-tax", "sub-section").
2. Two neighbouring letter-only fragments are joined when the joined word appears
   at least 3 times intact in the same document and at least one fragment, on its
   own, appears less than 10% as often as the joined word. The vocabulary comes
   from the document itself, so no dictionary is needed and legal terms work.

"o f" becomes "of" ("o" is rare, "of" very common). "in to" stays, because both
"in" and "to" are common words by themselves.

## Options rejected

- An English dictionary: misses legal terms (GSTIN, ITC, Schedule names) and adds a
  dependency.
- Another PDF library (pdfplumber, PyMuPDF): may fix some cases and break others;
  worth an ablation later, but repair works whatever the extractor.

## Consequences

- Rare split words (joined form seen fewer than 3 times) stay broken.
- A real two-word phrase whose concatenation is a common word, with one rare part,
  would be joined wrongly. No such case was found in the tests.
