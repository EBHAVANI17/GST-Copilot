"""Section expansion, with cases shaped like the real failures (q001, q004)."""

from gst_copilot.rag.expand import expand_sections
from gst_copilot.rag.retriever import RetrievedChunk


def piece(
    i: int, section: str | None, chars: int = 100, rerank: float | None = None
) -> RetrievedChunk:
    return RetrievedChunk(
        "ACT", "Act", "u", i, "x" * chars, score=0.5, section=section, rerank_score=rerank
    )


S16 = [piece(i, "16") for i in range(77, 83)]  # six pieces, like section 16
S17 = [piece(i, "17") for i in range(83, 92)]  # nine pieces, like section 17


def test_q001_shape_whole_section_in_order() -> None:
    # Retrieval found 77, 80, 81 of s.16 (not 78-79) and a Rules piece.
    ranked = [piece(77, "16", rerank=9.1), piece(80, "16", rerank=8.6), piece(81, "16", rerank=8.5)]
    out = expand_sections(ranked, {("ACT", "16"): S16}, max_chars=10_000)
    assert [c.chunk_index for c in out] == [77, 78, 79, 80, 81, 82]
    assert out[0].rerank_score == 9.1 and out[1].rerank_score is None


def test_best_section_first_then_others_within_budget() -> None:
    ranked = [piece(80, "16"), piece(88, "17")]
    out = expand_sections(ranked, {("ACT", "16"): S16, ("ACT", "17"): S17}, max_chars=700)
    # s.16 fits (600 chars); s.17 (900) does not, so only its hit + neighbours, if room.
    assert [c.chunk_index for c in out][:6] == [77, 78, 79, 80, 81, 82]
    assert sum(len(c.text) for c in out) <= 700


def test_section_too_big_keeps_hits_and_neighbours() -> None:
    ranked = [piece(85, "17"), piece(89, "17")]
    out = expand_sections(ranked, {("ACT", "17"): S17}, max_chars=650)
    assert [c.chunk_index for c in out] == [84, 85, 86, 88, 89, 90]


def test_pieces_without_section_pass_through_and_one_piece_always_fits() -> None:
    circular = piece(3, None, chars=5000)
    out = expand_sections([circular], {}, max_chars=100)
    assert out == [circular]


def test_no_duplicates_when_ranked_pieces_repeat_a_section() -> None:
    ranked = [piece(78, "16"), piece(79, "16"), piece(82, "16")]
    out = expand_sections(ranked, {("ACT", "16"): S16}, max_chars=10_000)
    refs = [c.ref for c in out]
    assert len(refs) == len(set(refs)) == 6
