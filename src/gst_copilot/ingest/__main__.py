"""Command line.

python -m gst_copilot.ingest corpus/manifest.csv              # load into the index
python -m gst_copilot.ingest corpus/manifest.csv --dry-run    # preview chunks, no database
python -m gst_copilot.ingest corpus/manifest.csv --dry-run --show CGST-ACT-2017:16
"""

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from gst_copilot.config import get_settings
from gst_copilot.db.session import get_engine, get_sessionmaker
from gst_copilot.embeddings import get_embedder
from gst_copilot.ingest.extract import extract_text
from gst_copilot.ingest.manifest import load_manifest
from gst_copilot.ingest.pipeline import chunk_document, ingest_manifest
from gst_copilot.logging import configure_logging


async def _main(manifest: Path) -> None:
    configure_logging(get_settings().log_level)
    embedder = get_embedder()
    async with get_sessionmaker()() as session:
        report = await ingest_manifest(session, embedder, manifest)
    await get_engine().dispose()
    print(json.dumps(asdict(report), indent=2))


def dry_run(manifest: Path, show: str | None) -> None:
    """Extract and chunk every document and print a summary. Nothing is embedded or stored."""
    settings = get_settings()
    print(f"Chunker: {settings.chunker_version}\n")
    for entry in load_manifest(manifest):
        pieces = chunk_document(extract_text(entry.path), entry.doc_type)
        counts = Counter(p.section for p in pieces)
        numbered = [s for s in counts if s is not None]
        sizes = sorted(len(p.text) for p in pieces)
        print(f"{entry.doc_id}: {len(pieces)} chunks, {len(numbered)} sections found")
        if pieces:
            print(f"  chunk size: median {sizes[len(sizes) // 2]}, max {sizes[-1]} chars")
            print(f"  chunks without a section: {counts.get(None, 0)}")
            print(f"  first sections: {', '.join(numbered[:15])}")
        if show and show.split(":")[0] == entry.doc_id:
            wanted = show.split(":", 1)[1] if ":" in show else None
            for i, p in enumerate(pieces):
                if p.section == wanted:
                    print(f"\n--- {entry.doc_id}#{i} (section {p.section}) ---\n{p.text}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load documents from a manifest into the index.")
    parser.add_argument("manifest", type=Path, help="path to manifest.csv")
    parser.add_argument("--dry-run", action="store_true", help="preview chunks; no database")
    parser.add_argument("--show", help="with --dry-run: print one section, e.g. CGST-ACT-2017:16")
    args = parser.parse_args()
    if args.dry_run:
        dry_run(args.manifest, args.show)
    else:
        asyncio.run(_main(args.manifest))


if __name__ == "__main__":
    main()
