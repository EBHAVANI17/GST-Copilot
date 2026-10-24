"""API tests. These run without Postgres or Redis: the dependency checks
are replaced with fakes, so the tests are fast and run anywhere, including CI."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot import __version__
from gst_copilot.api import health
from gst_copilot.api.main import create_app


async def ok() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("down")


async def hangs() -> None:
    await asyncio.sleep(10)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_is_ok_and_reports_version(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


async def test_every_response_has_a_request_id(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert len(r.headers["x-request-id"]) == 32


async def test_incoming_request_id_is_reused(client: AsyncClient) -> None:
    r = await client.get("/health", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


async def test_ready_when_all_dependencies_up(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "CHECKS", {"postgres": ok, "redis": ok})
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


async def test_not_ready_when_a_dependency_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "CHECKS", {"postgres": ok, "redis": broken})
    r = await client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == {
        "ok": False,
        "latency_ms": body["checks"]["redis"]["latency_ms"],
        "error": "ConnectionError",
    }
    assert body["checks"]["postgres"]["ok"] is True


async def test_slow_dependency_times_out_instead_of_hanging(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "CHECKS", {"postgres": hangs})
    monkeypatch.setattr(health.get_settings(), "dependency_timeout_seconds", 0.1)
    r = await client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["postgres"]["error"] == "TimeoutError"
