# Golden set

`golden.jsonl` holds questions with known answers. Write each one while reading the
official document, never from memory. Aim for 60 questions in M1:

| Type | Count | Example shape |
|---|---|---|
| lookup | 30 | What does section X require? |
| date | 10 | The same rate question for a date before and after a change |
| multihop | 10 | Needs an Act section and a notification or circular together |
| unanswerable | 10 | Out of scope (income tax, other countries) or not in the corpus |

Format: see `src/gst_copilot/evals/golden.py`. Run:

```
python -m gst_copilot.evals evals/golden.jsonl
```
