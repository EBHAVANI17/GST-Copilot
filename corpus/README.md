# Corpus

Official GST documents the assistant answers from.

1. Download a document from an official source (CBIC GST portal: cbic-gst.gov.in,
   GST Council: gstcouncil.gov.in). Save it in `corpus/raw/`.
2. Add one row to `manifest.csv`. Copy the title, dates and link from the official page.
   Leave `effective_to` empty while the document is in force.
3. Run `python -m gst_copilot.ingest corpus/manifest.csv`.

`corpus/raw/` is not committed (large files). `manifest.csv` is committed: it is the
record of exactly what the index contains.

Example row (format only; use the real values from the document you download):

```
CGST-ACT-2017,act,Central Goods and Services Tax Act 2017,https://...,2017-04-12,2017-07-01,,raw/cgst-act-2017.pdf
```
