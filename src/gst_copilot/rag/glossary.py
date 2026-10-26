"""Query expansion with a GST glossary: everyday words -> the law's words.

Users write "ITC", "bills", "sales", "file my return". The Act writes "input tax
credit", "invoice", "supply", "furnish ... return". A small embedding model does
not reliably connect them (golden v2: "What documents do I need before I can
claim ITC" missed Rule 36, while the same question with "input tax credit" found
it first).

So before searching, each glossary term found in the question gets the legal term
added next to it: "claim ITC" -> "claim ITC (input tax credit)". Only additions,
never replacements. The LLM still sees the user's original question.

Rule for editing this list: standard GST vocabulary only. Never add a term just
because one golden question fails; that tunes the system to the test (overfitting).
"""

import re

# term (matched as whole words, case-insensitive) -> legal wording to add
GLOSSARY: dict[str, str] = {
    # abbreviations
    "ITC": "input tax credit",
    "GSTIN": "Goods and Services Tax Identification Number",
    "HSN": "Harmonised System of Nomenclature",
    "ISD": "Input Service Distributor",
    "RCM": "reverse charge",
    "IGST": "integrated tax",
    "CGST": "central tax",
    "SGST": "State tax",
    # everyday words
    "bill": "invoice",
    "bills": "invoice",
    "sale": "supply",
    "sales": "supplies",
    "sell": "supply",
    "selling": "supply",
    "purchase": "inward supply",
    "purchases": "inward supplies",
    "buyer": "recipient",
    "seller": "supplier",
    "turnover": "aggregate turnover",
    "file": "furnish",
    "filing": "furnishing",
    "interstate": "inter-State",
    "intrastate": "intra-State",
}

_TERMS = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, GLOSSARY), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_LOOKUP = {k.lower(): v for k, v in GLOSSARY.items()}


def expand_query(question: str) -> str:
    """Add legal wording after glossary terms; skip terms already followed by it."""

    def repl(m: re.Match[str]) -> str:
        legal = _LOOKUP[m.group(1).lower()]
        rest = question[m.end() : m.end() + len(legal) + 3].lower()
        if legal.lower() in rest or legal.lower() == m.group(1).lower():
            return m.group(0)
        return f"{m.group(1)} ({legal})"

    return _TERMS.sub(repl, question)
