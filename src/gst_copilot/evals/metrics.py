"""Evaluation metrics. Pure functions, so they are easy to test and trust."""

import math
from collections.abc import Sequence


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


def contains_all(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return all(k.lower() in lowered for k in keywords)


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile, e.g. p=95 for p95 latency."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[index]


def ratio(numerator: int, denominator: int) -> float | None:
    """None (not 0) when there is nothing to measure, so reports don't mislead."""
    return round(numerator / denominator, 3) if denominator else None
