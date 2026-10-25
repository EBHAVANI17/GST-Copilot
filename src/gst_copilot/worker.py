"""Background worker (arq on Redis).

Anything slow (downloading documents, embedding, reconciling a 5,000-row
file) runs here, never inside an API request. The API puts a job on the
Redis queue and returns immediately; the worker picks it up.

Run locally:  arq gst_copilot.worker.WorkerSettings
"""

import logging
from typing import Any

from arq.connections import RedisSettings

from gst_copilot.config import get_settings
from gst_copilot.logging import configure_logging

log = logging.getLogger("gst_copilot.worker")


async def ping(ctx: dict[str, Any], message: str = "pong") -> str:
    """A trivial job used to prove the queue works end to end."""
    log.info("ping job ran", extra={"fields": {"job_message": message}})
    return message


async def ingest(ctx: dict[str, Any], manifest_path: str) -> dict[str, Any]:
    """Load documents listed in a manifest into the index (see gst_copilot.ingest)."""
    from dataclasses import asdict
    from pathlib import Path

    from gst_copilot.db.session import get_sessionmaker
    from gst_copilot.embeddings import get_embedder
    from gst_copilot.ingest.pipeline import ingest_manifest

    async with get_sessionmaker()() as session:
        report = await ingest_manifest(session, get_embedder(), Path(manifest_path))
    log.info("ingest job finished", extra={"fields": asdict(report)})
    return asdict(report)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    log.info("worker started")


class WorkerSettings:
    functions = [ping, ingest]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    job_timeout = 600  # seconds
