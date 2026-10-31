"""Tests for multi-hop query decomposition and Reciprocal Rank Fusion."""

from gst_copilot.rag.multihop import decompose_query, fuse_multihop_candidates
from gst_copilot.rag.retriever import RetrievedChunk


def test_decompose_single_shot_query() -> None:
    q = "Can I claim input tax credit on motor vehicles?"
    sub_queries = decompose_query(q)
    assert len(sub_queries) == 1
    assert sub_queries[0] == q


def test_decompose_explicit_compound_query() -> None:
    q = "Can I claim ITC on laptops? And also what is the deadline to reverse credit?"
    sub_queries = decompose_query(q)
    assert len(sub_queries) == 2
    assert "Can I claim ITC on laptops" in sub_queries[0]
    assert "what is the deadline to reverse credit" in sub_queries[1]


def test_decompose_dual_domain_concepts() -> None:
    q = "If I claim depreciation under income tax, does blocked credit under section 17(5) apply?"
    sub_queries = decompose_query(q)
    assert len(sub_queries) >= 2
    assert any("depreciation" in sq.lower() for sq in sub_queries)
    assert any("blocked" in sq.lower() or "17(5)" in sq for sq in sub_queries)


def test_fuse_multihop_candidates_rrf() -> None:
    c1 = RetrievedChunk(
        doc_id="CGST-ACT-2017",
        title="CGST Act",
        source_url="https://example.com/act",
        chunk_index=1,
        text="Section 16 text",
        score=0.9,
        section="16",
    )
    c2 = RetrievedChunk(
        doc_id="CGST-ACT-2017",
        title="CGST Act",
        source_url="https://example.com/act",
        chunk_index=2,
        text="Section 17 text",
        score=0.8,
        section="17",
    )
    c3 = RetrievedChunk(
        doc_id="CGST-RULES-2017",
        title="CGST Rules",
        source_url="https://example.com/rules",
        chunk_index=3,
        text="Rule 36 text",
        score=0.7,
        section="36",
    )

    # Sub-query 1 returned [c1, c2], Sub-query 2 returned [c2, c3]
    fused = fuse_multihop_candidates([[c1, c2], [c2, c3]], k=3, rrf_k=60)
    # c2 was present in both lists, so its reciprocal rank score should be highest!
    assert len(fused) == 3
    assert fused[0].ref == "CGST-ACT-2017#2"
