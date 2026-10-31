"""Unit tests for corpus freshness reporting and health endpoints (ADR 0024 Follow-up 1)."""

from datetime import date
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.ingest.freshness import FreshnessReport, get_corpus_freshness, main


def test_real_corpus_freshness() -> None:
    report = get_corpus_freshness(as_of=date(2026, 10, 31))
    assert isinstance(report, FreshnessReport)
    assert report.total_documents >= 4
    assert report.newest_doc_id == "CIRC-193-2023"
    assert report.newest_issued_on == date(2023, 7, 17)
    assert report.corpus_date_iso == "2023-07-17"
    assert report.days_since_newest == (date(2026, 10, 31) - date(2023, 7, 17)).days
    assert "circular" in report.by_type
    assert "act" in report.by_type


def test_missing_manifest_returns_empty_report(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.csv"
    report = get_corpus_freshness(non_existent)
    assert report.total_documents == 0
    assert report.newest_doc_id is None
    assert report.newest_issued_on is None
    assert report.days_since_newest is None


def test_manifest_without_issued_dates(tmp_path: Path) -> None:
    csv_file = tmp_path / "manifest.csv"
    csv_file.write_text(
        "doc_id,doc_type,title,source_url,issued_on,effective_from,effective_to,file\n"
        "DOC-1,act,Title 1,https://x/1,,,,raw/1.pdf\n",
        encoding="utf-8",
    )
    report = get_corpus_freshness(csv_file)
    assert report.total_documents == 1
    assert report.newest_doc_id is None
    assert report.days_since_newest is None


def test_freshness_works_when_raw_files_missing(tmp_path: Path) -> None:
    csv_file = tmp_path / "manifest.csv"
    csv_file.write_text(
        "doc_id,doc_type,title,source_url,issued_on,effective_from,effective_to,file\n"
        "ACT-1,act,Title 1,https://x/1,2023-01-01,2023-01-01,,raw/nonexistent.pdf\n",
        encoding="utf-8",
    )
    report = get_corpus_freshness(csv_file, as_of=date(2023, 1, 11))
    assert report.total_documents == 1
    assert report.newest_doc_id == "ACT-1"
    assert report.corpus_date_iso == "2023-01-01"
    assert report.days_since_newest == 10


def test_cli_freshness_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["corpus/manifest.csv", "--as-of", "2026-10-31"]) == 0
    out = capsys.readouterr().out
    assert "Corpus Freshness Report" in out
    assert "Total documents: 4" in out
    assert "CIRC-193-2023" in out
    assert "2023-07-17" in out


async def test_ready_endpoint_reports_corpus_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gst_copilot.api import health

    async def fake_ok() -> None:
        pass

    monkeypatch.setattr(health, "CHECKS", {"postgres": fake_ok, "redis": fake_ok})

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://t"
    ) as client:
        r_ready = await client.get("/ready")
        assert r_ready.status_code == 200
        body = r_ready.json()
        assert body["status"] == "ready"
        assert body["corpus_date"] == "2023-07-17"
        assert body["corpus_freshness_days"] is not None
