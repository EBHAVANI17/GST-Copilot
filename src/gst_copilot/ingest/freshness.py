"""Corpus freshness reporting (Milestone M5, ADR 0024 Follow-up 1).

Measures and prints the newest document date and days elapsed since publication,
based on corpus/manifest.csv.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gst_copilot.ingest.manifest import load_manifest

DEFAULT_MANIFEST_PATH = Path("corpus/manifest.csv")


@dataclass(frozen=True)
class FreshnessReport:
    manifest_path: Path
    total_documents: int
    by_type: dict[str, int]
    newest_doc_id: str | None
    newest_doc_title: str | None
    newest_issued_on: date | None
    days_since_newest: int | None

    @property
    def corpus_date_iso(self) -> str | None:
        return self.newest_issued_on.isoformat() if self.newest_issued_on else None


def get_corpus_freshness(
    manifest_path: Path | None = None,
    as_of: date | None = None,
) -> FreshnessReport:
    """Read the manifest and calculate corpus freshness metrics."""
    path = manifest_path or DEFAULT_MANIFEST_PATH
    if not path.exists():
        return FreshnessReport(
            manifest_path=path,
            total_documents=0,
            by_type={},
            newest_doc_id=None,
            newest_doc_title=None,
            newest_issued_on=None,
            days_since_newest=None,
        )

    try:
        entries = load_manifest(path, check_files=False)
    except Exception:
        return FreshnessReport(
            manifest_path=path,
            total_documents=0,
            by_type={},
            newest_doc_id=None,
            newest_doc_title=None,
            newest_issued_on=None,
            days_since_newest=None,
        )
    today = as_of or date.today()

    by_type = dict(Counter(e.doc_type for e in entries))
    with_dates = [e for e in entries if e.issued_on is not None]

    if not with_dates:
        return FreshnessReport(
            manifest_path=path,
            total_documents=len(entries),
            by_type=by_type,
            newest_doc_id=None,
            newest_doc_title=None,
            newest_issued_on=None,
            days_since_newest=None,
        )

    newest = max(with_dates, key=lambda e: e.issued_on or date.min)
    days = (today - newest.issued_on).days if newest.issued_on else None

    return FreshnessReport(
        manifest_path=path,
        total_documents=len(entries),
        by_type=by_type,
        newest_doc_id=newest.doc_id,
        newest_doc_title=newest.title,
        newest_issued_on=newest.issued_on,
        days_since_newest=days,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check the freshness of the indexed corpus.")
    parser.add_argument("manifest", nargs="?", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--as-of", type=date.fromisoformat, help="YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)

    report = get_corpus_freshness(args.manifest, as_of=args.as_of)
    print("Corpus Freshness Report")
    print("=======================")
    print(f"Manifest: {report.manifest_path}")
    type_str = ", ".join(f"{t}: {c}" for t, c in sorted(report.by_type.items()))
    print(f"Total documents: {report.total_documents} ({type_str})")
    if report.newest_doc_id:
        print(f"Newest document: {report.newest_doc_id} ({report.newest_doc_title})")
        print(f"Issued on: {report.corpus_date_iso} ({report.days_since_newest} days ago)")
    else:
        print("No documents with issued_on date found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
