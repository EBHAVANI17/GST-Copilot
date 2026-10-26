"""Evaluation metrics. Pure functions, so they are easy to test and trust."""

import math
from collections.abc import Sequence

from gst_copilot.ingest.numbers import to_digits


def first_relevant_rank(retrieved_doc_ids: Sequence[str], expected: set[str]) -> int | None:
    """1-based rank of the first retrieved chunk from an expected document, or None."""
    for rank, doc_id in enumerate(retrieved_doc_ids, start=1):
        if doc_id in expected:
            return rank
    return None


def hit_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Share of questions whose answer document appears in the top k."""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    """Average of 1/rank (0 when not found). 1.0 means always ranked first."""
    if not ranks:
        return 0.0
    return sum(1.0 / r for r in ranks if r is not None) / len(ranks)


# Numbers are compared in digits on both sides: the law says "thirty days", the
# index says "thirty (30) days", and an answer may say "30 days". All three match.
def _normalise(text: str) -> str:
    return " ".join(to_digits(text.lower()).split())


def contains_all(text: str, keywords: Sequence[str]) -> bool:
    lowered = _normalise(text)
    return all(_normalise(k) in lowered for k in keywords)


def missing_keywords(text: str, keywords: Sequence[str]) -> list[str]:
    """The expected keywords that do not appear in text (same matching rules)."""
    lowered = _normalise(text)
    return [k for k in keywords if _normalise(k) not in lowered]


def keyword_recall(text: str, keywords: Sequence[str]) -> float:
    """Share of expected keywords present (1.0 = all). Gentler than contains_all:
    an answer with 4 of 5 key phrases scores 0.8 instead of failing outright."""
    if not keywords:
        return 1.0
    lowered = _normalise(text)
    return sum(1 for k in keywords if _normalise(k) in lowered) / len(keywords)


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile, e.g. p=95 for p95 latency."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[index]


def ratio(numerator: float, denominator: int) -> float | None:
    """None (not 0) when there is nothing to measure, so reports don't mislead."""
    return round(numerator / denominator, 3) if denominator else None
