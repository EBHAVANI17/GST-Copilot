from pathlib import Path

import pytest

from gst_copilot.embeddings import FakeEmbedder
from gst_copilot.ingest.chunking import chunk_text
from gst_copilot.ingest.extract import clean_text
from gst_copilot.ingest.manifest import ManifestError, load_manifest

FIXTURES = Path(__file__).parent / "fixtures" / "sample_corpus"


def test_chunks_respect_size_and_cover_all_words() -> None:
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, size=200, overlap=40)
    assert all(len(c) <= 200 for c in chunks)
    covered = set(" ".join(chunks).split())
    assert covered == set(text.split()), "no word may be lost"


def test_chunks_overlap_and_never_split_words() -> None:
    text = " ".join(f"token{i}" for i in range(300))
    chunks = chunk_text(text, size=150, overlap=50)
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert a.split()[-1] in b.split(), "neighbouring chunks should share words"
    for c in chunks:
        assert all(w.startswith("token") for w in c.split())


def test_chunking_terminates_with_extreme_settings() -> None:
    assert len(chunk_text("a " * 1000, size=10, overlap=9)) > 0


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, 100), (100, -1)])
def test_chunking_rejects_bad_settings(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("some text", size=size, overlap=overlap)


def test_clean_text_fixes_hyphenation_and_page_numbers() -> None:
    raw = "The regis-\ntration rules\n\n12\n\n\n\nPage 3 of 40\nnext   line"
    assert clean_text(raw) == "The registration rules\n\nnext line"


def test_manifest_loads_and_resolves_files() -> None:
    entries = load_manifest(FIXTURES / "manifest.csv")
    assert [e.doc_id for e in entries] == ["SAMPLE-ACT", "SAMPLE-RULES", "SAMPLE-SCHEDULE"]
    assert all(e.path.is_file() for e in entries)
    assert entries[0].effective_to is None


def test_manifest_rejects_bad_dates(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    m = tmp_path / "manifest.csv"
    m.write_text(
        "doc_id,doc_type,title,source_url,issued_on,effective_from,effective_to,file\n"
        "D1,act,T,https://x,15-08-2025,,,a.txt\n"
    )
    with pytest.raises(ManifestError, match="YYYY-MM-DD"):
        load_manifest(m)


def test_fake_embedder_puts_shared_words_close() -> None:
    e = FakeEmbedder(dim=384)
    q = e.embed_query("input credit statement")
    near = e.embed_documents(["input credit appears in the monthly credit statement"])[0]
    far = e.embed_documents(["registration number at the principal place of business"])[0]

    def dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert dot(q, near) > dot(q, far)
    assert len(q) == 384
