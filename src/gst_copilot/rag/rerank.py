"""Reranking: re-score retrieval candidates with a cross-encoder.

Retrieval (vector or keyword search) is fast because the question and each chunk
are turned into numbers separately, and only those are compared. That is also its
weakness: the model never sees the question and the chunk together.

A cross-encoder reads "question + chunk" as one input and outputs one relevance
score. Far more accurate, far too slow to run on every chunk. So the standard
two-stage design is:

    retrieval: ~40 candidates in milliseconds   (recall: don't miss the right one)
    reranker:  re-score those 40, keep top k    (precision: put it first)
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from functools import lru_cache
from typing import Protocol

from gst_copilot.config import get_settings
from gst_copilot.rag.retriever import RetrievedChunk


class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """One relevance score per text; higher = more relevant."""
        ...


class CrossEncoderReranker:
    """A cross-encoder from fastembed (ONNX, CPU). The model downloads on first use."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # not needed in tests

        self.name = model_name
        self._model = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, list(texts))]


_WORD = re.compile(r"[a-z0-9]{3,}")


class FakeReranker:
    """Deterministic stand-in for tests and CI: share of question words in the text."""

    name = "fake"

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        words = set(_WORD.findall(query.lower()))
        if not words:
            return [0.0] * len(texts)
        return [len(words & set(_WORD.findall(t.lower()))) / len(words) for t in texts]


def rerank(
    reranker: Reranker, query: str, candidates: list[RetrievedChunk], k: int
) -> list[RetrievedChunk]:
    """Order candidates by reranker score and keep the top k. Ties keep retrieval order."""
    if not candidates:
        return []
    scores = reranker.score(query, [c.text for c in candidates])
    order = sorted(range(len(candidates)), key=lambda i: -scores[i])  # stable sort
    return [replace(candidates[i], rerank_score=round(scores[i], 4)) for i in order[:k]]


@lru_cache
def get_reranker() -> Reranker | None:
    """None when reranking is switched off (RERANKER=none)."""
    s = get_settings()
    if s.reranker == "none":
        return None
    if s.reranker == "fake":
        return FakeReranker()
    return CrossEncoderReranker(s.reranker_model, s.embedding_cache_dir)
