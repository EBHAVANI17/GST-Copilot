"""The corpus manifest: one CSV row per source document.

You fill corpus/manifest.csv by hand as you download official documents.
Columns:
    doc_id          our stable ID used in citations, e.g. CGST-ACT-2017
    doc_type        act | rule | notification | circular
    title           human-readable title
    source_url      the official page or PDF link
    issued_on       YYYY-MM-DD or empty
    effective_from  YYYY-MM-DD or empty
    effective_to    YYYY-MM-DD or empty (still in force)
    file            path to the downloaded file, relative to the manifest
"""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DOC_TYPES = {"act", "rule", "notification", "circular"}
REQUIRED = ["doc_id", "doc_type", "title", "source_url", "file"]


@dataclass(frozen=True)
class ManifestEntry:
    doc_id: str
    doc_type: str
    title: str
    source_url: str
    issued_on: date | None
    effective_from: date | None
    effective_to: date | None
    path: Path


class ManifestError(ValueError):
    pass


def _date(value: str, field: str, line: int) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ManifestError(f"line {line}: {field} must be YYYY-MM-DD, got {value!r}") from exc


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read and validate the manifest. Fails loudly on the first bad row."""
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ManifestError(f"manifest is missing columns: {missing}")
        for line, row in enumerate(reader, start=2):  # line 1 is the header
            doc_id = row["doc_id"].strip()
            if not doc_id:
                raise ManifestError(f"line {line}: doc_id is empty")
            if doc_id in seen:
                raise ManifestError(f"line {line}: duplicate doc_id {doc_id}")
            seen.add(doc_id)
            doc_type = row["doc_type"].strip().lower()
            if doc_type not in DOC_TYPES:
                raise ManifestError(f"line {line}: doc_type must be one of {sorted(DOC_TYPES)}")
            file_path = (path.parent / row["file"].strip()).resolve()
            if not file_path.is_file():
                raise ManifestError(f"line {line}: file not found: {file_path}")
            entries.append(
                ManifestEntry(
                    doc_id=doc_id,
                    doc_type=doc_type,
                    title=row["title"].strip(),
                    source_url=row["source_url"].strip(),
                    issued_on=_date(row.get("issued_on", ""), "issued_on", line),
                    effective_from=_date(row.get("effective_from", ""), "effective_from", line),
                    effective_to=_date(row.get("effective_to", ""), "effective_to", line),
                    path=file_path,
                )
            )
    return entries
