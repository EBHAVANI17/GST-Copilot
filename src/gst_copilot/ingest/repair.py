"""Repair text that PDF extraction broke.

pypdf sometimes inserts spaces inside words when a PDF positions letters
individually, and keeps a space before a line-break hyphen. From the CBIC Act:

    "date of issue o f invoice"      should be "date of issue of invoice"
    "it sh all be deemed"            should be "it shall be deemed"
    "the Income -\\ntax Act"         should be "the Income-tax Act"

These broke keyword matching (q003, q008) and make embeddings worse.

Split words are joined using the document's own vocabulary, not a dictionary:
join "a b" when "ab" is a common word in the same document and at least one
fragment is rare on its own. So "o f" -> "of" ("o" alone is rare, "of" is very
common), but "in to" stays: both "in" and "to" are common words by themselves.
"""

import re
from collections import Counter

# "Income -\ntax", "sub -section", "2017 -18": a space before a hyphen inside a word.
_SPACED_HYPHEN = re.compile(r"(\w) -\n?(?=\w)")
# A letter-only word, one space, and (looked ahead, not consumed) the next word, so
# every neighbouring pair is checked: "issue und er" checks "issue und" AND "und er".
_PAIR = re.compile(r"\b([A-Za-z]+) (?=([A-Za-z]+)\b)")
_WORD = re.compile(r"[A-Za-z]+")

MIN_JOINED = 3  # the joined word must appear at least this often, intact
RARE_RATIO = 0.1  # a fragment is "rare" if seen < 10% as often as the joined word


def repair_text(text: str) -> str:
    text = _SPACED_HYPHEN.sub(r"\1-", text)
    counts = Counter(w.lower() for w in _WORD.findall(text))

    def join(m: re.Match[str]) -> str:
        """Drop the space between the two words, or keep the match unchanged."""
        a, b = m.group(1), m.group(2)
        joined = (a + b).lower()
        n = counts.get(joined, 0)
        if n < MIN_JOINED:
            return m.group(0)
        rarest = min(counts[a.lower()], counts[b.lower()])
        return a if rarest < RARE_RATIO * n else m.group(0)

    return _PAIR.sub(join, text)
