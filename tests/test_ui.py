"""Tests for the frontend UI endpoints and static assets."""

import re
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import UI_DIR, create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://testserver",
        follow_redirects=False,
    ) as c:
        yield c


async def test_root_redirects_to_ui(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/ui"


async def test_ui_index_served(client: AsyncClient) -> None:
    response = await client.get("/ui/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    text = response.text
    assert "GST Copilot" in text
    assert "Ask Law" in text
    assert "Reconcile ITC" in text
    assert "Check Invoice" in text
    assert "Strict In-Memory Processing" in text


async def test_ui_static_assets_served(client: AsyncClient) -> None:
    for filename, expected_mime in [
        ("favicon.svg", "image/svg+xml"),
        ("app.css", "text/css"),
        ("app.js", "javascript"),
    ]:
        res = await client.get(f"/ui/{filename}")
        assert res.status_code == 200, f"Failed to fetch {filename}"
        assert expected_mime in res.headers["content-type"]


def test_no_emojis_in_frontend_assets() -> None:
    """Strict adherence to the professional UI guideline: SVGs only, zero emojis."""
    # Common Unicode emoji ranges
    emoji_pattern = re.compile(
        r"[\U0001F600-\U0001F64F"  # emoticons
        r"\U0001F300-\U0001F5FF"  # symbols & pictographs
        r"\U0001F680-\U0001F6FF"  # transport & map
        r"\U0001F1E0-\U0001F1FF"  # flags
        r"\U00002702-\U000027B0"  # dingbats
        r"\U0001F900-\U0001F9FF"  # supplemental symbols
        r"\U0001FA70-\U0001FAFF]"  # symbols extended
    )

    for asset in ["index.html", "app.css", "app.js", "favicon.svg"]:
        path = UI_DIR / asset
        assert path.exists(), f"{asset} does not exist"
        content = path.read_text(encoding="utf-8")
        matches = emoji_pattern.findall(content)
        assert not matches, f"Found emoji(s) {matches} in {asset}!"
