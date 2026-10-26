"""Health endpoints, the way orchestrators (Kubernetes, ECS, Render...) use them.

/health  = liveness:  "is the process running?"  Never touches dependencies.
                      If it fails, the platform restarts the container.
/ready   = readiness: "can this instance serve traffic right now?"
                      Checks Postgres, Redis and that the models are loaded
                      (warm-up). If it fails, the platform
                      stops sending traffic here but does NOT restart it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis

from gst_copilot import __version__
from gst_copilot.api.warmup import models_ready
from gst_copilot.config import get_settings
from gst_copilot.db.session import ping_database

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


class Liveness(BaseModel):
    status: str
    version: str


class DependencyStatus(BaseModel):
    ok: bool
    latency_ms: float
    error: str | None = None


class Readiness(BaseModel):
    status: str
    checks: dict[str, DependencyStatus]


async def ping_redis() -> None:
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


# A registry of checks, so tests can replace them without real servers.
CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "postgres": ping_database,
    "redis": ping_redis,
    "models": models_ready,  # not ready until warm-up has loaded the models
}


async def _run_check(name: str, check: Callable[[], Awaitable[None]]) -> DependencyStatus:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=get_settings().dependency_timeout_seconds)
        return DependencyStatus(ok=True, latency_ms=round((time.perf_counter() - start) * 1000, 1))
    except Exception as exc:  # report any failure as "down", never crash the endpoint
        log.warning("dependency check failed", extra={"fields": {"dependency": name}})
        return DependencyStatus(
            ok=False,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            error=type(exc).__name__,
        )


@router.get("/health", response_model=Liveness)
async def health() -> Liveness:
    return Liveness(status="ok", version=__version__)


@router.get("/ready", response_model=Readiness)
async def ready(response: Response) -> Readiness:
    # Run all checks at the same time, so the slowest one sets the total time.
    names = list(CHECKS)
    results = await asyncio.gather(*(_run_check(n, CHECKS[n]) for n in names))
    checks = dict(zip(names, results, strict=True))
    all_ok = all(c.ok for c in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ready" if all_ok else "degraded", checks=checks)
