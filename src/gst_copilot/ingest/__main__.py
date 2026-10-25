"""Command line: python -m gst_copilot.ingest corpus/manifest.csv"""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from gst_copilot.config import get_settings
from gst_copilot.db.session import get_engine, get_sessionmaker
from gst_copilot.embeddings import get_embedder
from gst_copilot.ingest.pipeline import ingest_manifest
from gst_copilot.logging import configure_logging


async def _main(manifest: Path) -> None:
    configure_logging(get_settings().log_level)
    embedder = get_embedder()
    async with get_sessionmaker()() as session:
        report = await ingest_manifest(session, embedder, manifest)
    await get_engine().dispose()
    print(json.dumps(asdict(report), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Load documents from a manifest into the index.")
    parser.add_argument("manifest", type=Path, help="path to manifest.csv")
    args = parser.parse_args()
    asyncio.run(_main(args.manifest))


if __name__ == "__main__":
    main()
