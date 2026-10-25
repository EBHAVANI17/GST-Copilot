"""Number annotation and rank fusion: pure functions, no database."""

import pytest

from gst_copilot.ingest.numbers import annotate_numbers, words_to_int
from gst_copilot.ingest.structure import structured_chunks
from gst_copilot.rag.retriever import RetrievedChunk, rrf_fuse


@pytest.mark.parametrize(
    "phrase,value",
    [
        ("thirty", 30),
        ("one hundred and eighty", 180),
        ("twenty-five", 25),
        ("two thousand", 2000),
        ("twenty lakh", 2_000_000),
        ("ninety", 90),
    ],
)
def test_words_to_int(phrase: str, value: int) -> None:
    assert words_to_int(phrase) == value


def test_annotate_numbers_before_units_only() -> None:
    text = "within one hundred and eighty days; fifty per cent. of it; one of the persons"
    assert annotate_numbers(text) == (
        "within one hundred and eighty (180) days; fifty (50) per cent. of it; one of the persons"
    )


def test_annotate_numbers_across_a_line_break() -> None:
    assert annotate_numbers("a period of one hundred\nand eighty days") == (
        "a period of one hundred\nand eighty (180) days"
    )


def test_structured_chunks_include_digits() -> None:
    text = "5. Payment.—(1) Pay within one hundred and eighty days of the invoice."
    [piece] = structured_chunks(text, 500, 50, "act")
    assert "one hundred and eighty (180) days" in piece.text


def _chunk(i: int) -> RetrievedChunk:
    return RetrievedChunk("D", "t", "u", i, f"text {i}", score=0.5)


def test_rrf_rewards_chunks_found_by_both_searches() -> None:
    vector = {1: _chunk(1), 2: _chunk(2), 3: _chunk(3)}
    keyword = {3: _chunk(3), 4: _chunk(4)}
    fused = rrf_fuse(vector, keyword, k=4, rrf_k=60)
    # 3 is in both lists, so it wins; 2 and 4 tie (both rank 2 in one list), and
    # ties go to the vector ranking.
    assert [c.chunk_index for c in fused] == [3, 1, 2, 4]
    top = fused[0]
    assert (top.vector_rank, top.keyword_rank) == (3, 1)
    assert fused[3].vector_rank is None and fused[3].keyword_rank == 2


def test_rrf_ties_prefer_the_vector_ranking() -> None:
    fused = rrf_fuse({1: _chunk(1)}, {2: _chunk(2)}, k=2, rrf_k=60)
    assert [c.chunk_index for c in fused] == [1, 2]
