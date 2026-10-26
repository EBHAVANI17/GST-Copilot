"""Lint the golden set against the real documents, before any eval run.

    python -m gst_copilot.evals.check evals/golden.jsonl corpus/manifest.csv

For every answerable question it checks, using the same text the index uses
(repair, cleaning, sections, numbers in digits):

- each expected section exists in the expected document;
- each expected keyword appears, word for word, in an expected section.

A keyword found only in another section is reported with where it was found.
A keyword found nowhere is usually paraphrased or remembered instead of copied.
No database, no LLM: it only reads the source files. Exit code 1 if anything fails.
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from gst_copilot.evals.golden import GoldenItem, load_golden
from gst_copilot.evals.metrics import missing_keywords
from gst_copilot.ingest.extract import extract_text
from gst_copilot.ingest.manifest import load_manifest
from gst_copilot.ingest.pipeline import chunk_document


@dataclass
class Corpus:
    # "DOC:SECTION" -> text of all pieces of that section
    sections: dict[str, str] = field(default_factory=dict)
    # DOC -> full text
    documents: dict[str, str] = field(default_factory=dict)


def load_corpus(manifest: Path) -> Corpus:
    corpus = Corpus()
    for entry in load_manifest(manifest):
        pieces = chunk_document(extract_text(entry.path), entry.doc_type)
        by_section: dict[str, list[str]] = defaultdict(list)
        for p in pieces:
            if p.section is not None:
                by_section[p.section].append(p.text)
        for section, texts in by_section.items():
            corpus.sections[f"{entry.doc_id}:{section}"] = "\n".join(texts)
        corpus.documents[entry.doc_id] = "\n".join(p.text for p in pieces)
    return corpus


def check_item(item: GoldenItem, corpus: Corpus) -> list[str]:
    """Problems for one question (empty = fine)."""
    if not item.answerable:
        return []
    problems: list[str] = []
    for doc in item.expected_doc_ids:
        if doc not in corpus.documents:
            problems.append(f"document {doc} is not in the manifest")
    pairs = sorted(item.section_pairs)
    missing_sections = [p for p in pairs if p not in corpus.sections]
    problems += [f"section {p} not found (check the number)" for p in missing_sections]

    expected_text = "\n".join(corpus.sections[p] for p in pairs if p in corpus.sections)
    if not pairs:  # no sections given: search the whole expected documents
        expected_text = "\n".join(corpus.documents.get(d, "") for d in item.expected_doc_ids)
    for keyword in missing_keywords(expected_text, item.expected_keywords):
        elsewhere = [
            key
            for key, text in corpus.sections.items()
            if key.split(":")[0] in item.expected_doc_ids and not missing_keywords(text, [keyword])
        ]
        if elsewhere:
            shown = ", ".join(elsewhere[:5]) + (" ..." if len(elsewhere) > 5 else "")
            problems.append(f"keyword {keyword!r} not in expected section(s); found in {shown}")
        else:
            problems.append(f"keyword {keyword!r} not found anywhere: copy it from the text")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Check golden keywords against the documents.")
    parser.add_argument("golden", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    items = load_golden(args.golden)  # format errors stop here, with the line number
    corpus = load_corpus(args.manifest)
    failures = 0
    for item in items:
        problems = check_item(item, corpus)
        if problems:
            failures += 1
            print(f"{item.id}: {item.question}")
            for p in problems:
                print(f"    - {p}")
    answerable = sum(1 for i in items if i.answerable)
    print(f"\n{len(items)} questions ({answerable} answerable): {failures} with problems")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
