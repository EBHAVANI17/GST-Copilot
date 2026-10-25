"""Write numbers in digits next to numbers in words.

Indian statutes write "one hundred and eighty days" where a user types "180 days".
A small embedding model does not reliably treat those as the same, and keyword
search cannot match them at all. So at index time we turn

    "within a period of one hundred and eighty days"
into
    "within a period of one hundred and eighty (180) days"

Only number phrases followed by a unit (days, months, years, per cent, lakh, ...)
are annotated, so ordinary words like "one of the" are left alone.
"""

import re

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "crore": 10_000_000}

_WORD = "|".join([*_UNITS, *_TENS, *_SCALES])
_NUM = rf"(?:{_WORD})(?:[\s-]+(?:and[\s-]+)?(?:{_WORD}))*"
_FOLLOWING = (
    r"days?|months?|years?|weeks?|hours?|per\s*cent\.?|percent|rupees|"
    r"lakhs?|crores?|instalments?|times"
)
_PATTERN = re.compile(rf"\b(?P<num>{_NUM})\b(?P<gap>\s+)(?=(?:{_FOLLOWING})\b)", re.IGNORECASE)


def words_to_int(phrase: str) -> int | None:
    """'one hundred and eighty' -> 180, 'twenty-five' -> 25. None if not a number."""
    total = current = 0
    seen = False
    for word in re.split(r"[\s-]+", phrase.lower()):
        if word == "and" or not word:
            continue
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word in _SCALES:
            total += (current or 1) * _SCALES[word]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def annotate_numbers(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        value = words_to_int(m.group("num"))
        if value is None:
            return m.group(0)
        return f"{m.group('num')} ({value}){m.group('gap')}"

    return _PATTERN.sub(repl, text)
