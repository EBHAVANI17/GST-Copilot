"""Query decomposition and multi-hop planning for complex GST questions.

Single-shot RAG fails on compound inquiries that span multiple statutory domains
(e.g., composition levy + blocked credits, or depreciation + time limits).
The query planner decomposes compound questions into targeted sub-queries,
retrieves evidence across multiple sections, and fuses them via Reciprocal Rank Fusion.
"""

import re
from collections.abc import Sequence

from gst_copilot.rag.retriever import RetrievedChunk

# Connectors and contrastive patterns indicating compound queries
_SPLIT_PATTERNS = re.compile(
    r"\b(?:and\s+also|as\s+well\s+as|additionally|furthermore|along\s+with|;\s*|\?\s+)\b",
    re.IGNORECASE,
)

# Dual-concept trigger pairs (e.g. asking about two distinct legal mechanisms together)
_COMPOUND_TRIGGERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(depreciation|income[- ]tax)\b", re.I), "depreciation under income tax act"),
    (
        re.compile(r"\b(composition|composition\s+scheme)\b", re.I),
        "composition levy eligibility section 10",
    ),
    (re.compile(r"\b(reverse\s+charge|rcm)\b", re.I), "reverse charge liability section 9"),
    (
        re.compile(r"\b(blocked\s+credit|section\s+17\s*\(5\)|ineligible)\b", re.I),
        "blocked input tax credit section 17(5)",
    ),
    (
        re.compile(r"\b(180\s*days|payment\s+to\s+supplier|add[- ]back)\b", re.I),
        "payment within 180 days and output tax liability reversal",
    ),
    (
        re.compile(r"\b(rule\s*36|documents|invoice\s+possession)\b", re.I),
        "documentary requirements under rule 36",
    ),
    (
        re.compile(r"\b(time\s*limit|cut[- ]off|november|september)\b", re.I),
        "time limit for claiming input tax credit",
    ),
]


def decompose_query(question: str) -> list[str]:
    """Decompose compound or multi-topic questions into atomic statutory sub-queries.

    Returns a list of 1 to 3 targeted sub-queries.
    """
    clean_q = question.strip()
    if not clean_q:
        return []

    # 1. Explicit multi-clause questions (e.g. "Can I claim ITC? And also what is the deadline?")
    clauses = [c.strip() for c in _SPLIT_PATTERNS.split(clean_q) if len(c.strip()) > 8]
    if len(clauses) >= 2:
        return clauses[:3]

    # 2. Check for compound legal topics in a single sentence
    matched_topics: list[str] = []
    for pattern, topic_desc in _COMPOUND_TRIGGERS:
        if pattern.search(clean_q):
            matched_topics.append(topic_desc)

    if len(matched_topics) >= 2:
        sub_queries = [clean_q]
        for topic in matched_topics[:2]:
            sub_queries.append(f"{clean_q} focusing on {topic}")
        return sub_queries

    # Single-hop query
    return [clean_q]


def fuse_multihop_candidates(
    candidate_lists: Sequence[list[RetrievedChunk]],
    k: int,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Merge retrieved chunks from multiple sub-queries using Reciprocal Rank Fusion."""
    if not candidate_lists:
        return []
    if len(candidate_lists) == 1:
        return candidate_lists[0][:k]

    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for candidates in candidate_lists:
        for rank, chunk in enumerate(candidates, start=1):
            ref = chunk.ref
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (rrf_k + rank)
            if ref not in chunk_map:
                chunk_map[ref] = chunk

    # Sort descending by fused RRF score
    ordered_refs = sorted(scores.keys(), key=lambda r: scores[r], reverse=True)
    return [chunk_map[ref] for ref in ordered_refs[:k]]
