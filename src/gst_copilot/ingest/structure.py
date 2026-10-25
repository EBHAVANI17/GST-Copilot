"""Structure-aware chunking (M2): one section or rule per chunk.

Why: the M1 baseline cut documents into fixed 1,200-character windows. A window
often mixed the end of one section with the start of the next, and a short
sub-section (for example s.16(3)) was diluted inside a chunk that was mostly about
something else, so its embedding did not match questions about it.

Three steps:
1. strip_noise: drop running page headers ("CHAPTER V INPUT TAX CREDIT" on every
   page), amendment footnotes ("111 Substituted w.e.f. ...") and footnote markers
   ("[furnished]67" -> "[furnished]").
2. split_sections: find headings such as "16. Eligibility and conditions for taking
   input tax credit.—(1)" (Act) or "36. Documentary requirements ... .-(1)" (Rules).
3. chunk_sections: one chunk per section. A long section is split at its
   sub-sections "(1)", "(2)", ... and every piece starts with a context header,
   e.g. "Section 16. Eligibility and conditions for taking input tax credit",
   so even a small piece says what it is about.

Numbers written in words get their digits added ("one hundred and eighty (180)
days"), see numbers.py.

Documents without detectable headings (circulars, notifications) fall back to the
fixed-size chunks from M1.
"""

import re
from collections import Counter
from dataclasses import dataclass

from gst_copilot.ingest.chunking import chunk_text
from gst_copilot.ingest.numbers import annotate_numbers

# Bumped whenever the output of this module changes, so the pipeline re-chunks
# documents that were indexed with an older version.
STRUCTURE_VERSION = "v2"  # v2: numbers in words also written in digits


@dataclass(frozen=True)
class Section:
    number: str | None  # "16", "43A"; None for text before the first heading
    heading: str | None
    body: str


@dataclass(frozen=True)
class Piece:
    text: str
    section: str | None


# --- 1. Noise -----------------------------------------------------------------

# "111 Substituted w.e.f. 01.07.2017 for ..." (amendment notes printed at the page foot)
_FOOTNOTE_START = re.compile(
    r"^\d{1,3}\s+(Substituted|Inserted|Omitted|Added|Renumbered|Re-numbered|"
    r"Brought into force|Vide|The words|Words)\b",
)
# "]67" -> "]": the footnote number printed right after an amended passage
_FOOTNOTE_MARKER = re.compile(r"\]\s?\d{1,3}\b")


def strip_noise(text: str, min_repeats: int = 4) -> str:
    lines = text.split("\n")

    # Running headers: short lines that repeat on many pages.
    counts = Counter(ln.strip() for ln in lines if ln.strip())
    repeated = {
        ln
        for ln, n in counts.items()
        if n >= min_repeats and len(ln) <= 80 and not ln.startswith("(")
    }

    kept: list[str] = []
    wrapped = 0  # how many more wrapped footnote lines may follow
    for line in lines:
        s = line.strip()
        if _FOOTNOTE_START.match(s):
            wrapped = 2
            continue
        if wrapped and s and _looks_like_continuation(s):
            wrapped -= 1
            continue
        wrapped = 0
        if s in repeated:
            continue
        kept.append(line)

    out = "\n".join(kept)
    out = _FOOTNOTE_MARKER.sub("]", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _looks_like_continuation(line: str) -> bool:
    """A wrapped footnote line, e.g. 'Act, 2020 (No. 12 of 2020)-Brought into force ...'."""
    return bool(re.search(r"\b(Act|Rules?|Notification|w\.e\.f|No\.)\b", line)) and not re.match(
        r"^\(?\d+[A-Z]?[.)]", line
    )


# --- 2. Sections ----------------------------------------------------------------

# Line start, optional "[" (inserted by amendment), number, ". ", a heading that starts
# with a capital letter and may wrap over two lines, then ".—" / ". —" / ".-" / ".–".
# PDFs print the dash in several ways: hyphen, en dash, em dash, horizontal bar.
_DASH = "-\u2013\u2014\u2015"
_HEADING = re.compile(
    r"^\[?(?P<num>\d{1,3}[A-Z]{0,3})\.\s+"
    rf"(?P<head>[A-Z](?:[^\n{_DASH[1:]}]|\n(?!\n)){{2,250}}?)"
    rf"\s*\.\s*[{_DASH}]+\s*",
    re.MULTILINE,
)


def split_sections(text: str) -> list[Section]:
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [Section(None, None, text.strip())] if text.strip() else []

    sections: list[Section] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(Section(None, None, preamble))
    for m, nxt in zip(matches, [*matches[1:], None], strict=True):
        end = nxt.start() if nxt else len(text)
        heading = " ".join(m.group("head").split())
        body = text[m.end() : end].strip()
        sections.append(Section(m.group("num"), heading, body))
    return sections


# --- 3. Chunks ------------------------------------------------------------------

_SUBSECTION = re.compile(r"\n(?=\[?\(\d{1,2}[A-Z]?\))")  # a line starting with "(2)" or "[(4)"

_LABEL = {"act": "Section", "rule": "Rule"}


def chunk_sections(
    sections: list[Section], size: int, overlap: int, doc_type: str = "act"
) -> list[Piece]:
    label = _LABEL.get(doc_type, "Para")
    pieces: list[Piece] = []
    for sec in sections:
        if sec.number is None:
            pieces.extend(Piece(t, None) for t in chunk_text(sec.body, size, overlap))
            continue
        header = f"{label} {sec.number}. {sec.heading}"
        budget = max(size - len(header) - 1, size // 2)
        for part in _pack(sec.body, budget, overlap):
            pieces.append(Piece(f"{header}\n{part}", sec.number))
    return pieces


def _pack(body: str, budget: int, overlap: int) -> list[str]:
    """Group whole sub-sections into pieces of at most `budget` characters."""
    if len(body) <= budget:
        return [body] if body else [""]
    out: list[str] = []
    current = ""
    for unit in _SUBSECTION.split(body):
        unit = unit.strip()
        if not unit:
            continue
        if len(unit) > budget:  # one huge sub-section: fall back to windows
            if current:
                out.append(current)
                current = ""
            out.extend(chunk_text(unit, budget, min(overlap, budget // 4)))
        elif current and len(current) + 1 + len(unit) > budget:
            out.append(current)
            current = unit
        else:
            current = f"{current}\n{unit}" if current else unit
    if current:
        out.append(current)
    return out


def structured_chunks(text: str, size: int, overlap: int, doc_type: str) -> list[Piece]:
    """Clean, write numbers in digits, split into sections, then chunk (pipeline entry point)."""
    clean = annotate_numbers(strip_noise(text))
    return chunk_sections(split_sections(clean), size, overlap, doc_type)
