"""Reranking logic with a fake reranker: no model download."""

from collections.abc import Sequence

from gst_copilot.rag.rerank import FakeReranker, rerank
from gst_copilot.rag.retriever import RetrievedChunk


def _chunk(i: int, text: str) -> RetrievedChunk:
    return RetrievedChunk("D", "t", "u", i, text, score=0.5, vector_rank=i + 1)


class ByLength:
    name = "by-length"

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        return [float(len(t)) for t in texts]


def test_rerank_orders_by_score_and_keeps_top_k() -> None:
    pool = [_chunk(0, "aa"), _chunk(1, "aaaa"), _chunk(2, "a"), _chunk(3, "aaa")]
    out = rerank(ByLength(), "q", pool, k=2)
    assert [c.chunk_index for c in out] == [1, 3]
    assert [c.rerank_score for c in out] == [4.0, 3.0]
    assert out[0].vector_rank == 2, "retrieval ranks are kept for debugging"


def test_rerank_ties_keep_retrieval_order_and_handles_empty() -> None:
    pool = [_chunk(0, "x"), _chunk(1, "y"), _chunk(2, "z")]
    assert [c.chunk_index for c in rerank(ByLength(), "q", pool, k=3)] == [0, 1, 2]
    assert rerank(ByLength(), "q", [], k=3) == []


def test_fake_reranker_scores_word_overlap() -> None:
    scores = FakeReranker().score(
        "time limit for input tax credit",
        ["the time limit for input tax credit", "registration of a person", ""],
    )
    assert scores[0] == 1.0
    assert scores[1] == 0.0 and scores[2] == 0.0
    assert FakeReranker().score("a ?", ["anything"]) == [0.0]


def test_rerank_promotes_the_relevant_chunk() -> None:
    pool = [
        _chunk(0, "Rule 89. Application for refund within two years."),
        _chunk(1, "Rule 23. Revocation of cancellation within thirty days."),
        _chunk(2, "Section 16. Where a recipient fails to pay the supplier within 180 days."),
    ]
    question = "What if the recipient fails to pay the supplier within 180 days?"
    assert rerank(FakeReranker(), question, pool, k=1)[0].chunk_index == 2
