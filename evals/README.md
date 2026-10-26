# Golden set

`golden.jsonl` holds questions with known answers. Write each one while reading the
official document, never from memory. Aim for 60 questions in M1:

| Type | Count | Example shape |
|---|---|---|
| lookup | 30 | What does section X require? |
| date | 10 | The same rate question for a date before and after a change |
| multihop | 10 | Needs an Act section and a notification or circular together |
| application | 10 | The user's own facts: "My turnover is 15 lakh, do I need to register?" |
| unanswerable | 10 | Out of scope (income tax, other countries) or not in the corpus |

Format: see `src/gst_copilot/evals/golden.py`.

Add `"expected_sections": ["16"]` to answerable questions (section or rule number
only, no sub-section like "16(2)"). The report then also shows `section_hit@k`:
did retrieval find the right **section**, not just the right document. With only a
few documents, document-level hit@k is easy; section-level is the honest number.

When a question needs two documents, name the document in each entry:
`"expected_sections": ["CGST-ACT-2017:18", "CGST-RULES-2017:40"]`.

Before running an eval, check every keyword against the real documents:

```
python -m gst_copilot.evals.check evals/golden.jsonl corpus/manifest.csv
```

Run:

```
python -m gst_copilot.evals evals/golden.jsonl
```
