"""Run the golden set against the live index and print a report.

    python -m gst_copilot.evals evals/golden.jsonl
    python -m gst_copilot.evals evals/golden.jsonl --k 5 --min-hit-at-k 0.85   # fail if below

Retrieval metrics always run. Answer metrics run only when an LLM is configured.
Every run writes a JSON report to reports/ so you can compare runs over time.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gst_copilot.config import get_settings
from gst_copilot.db.session import get_engine, get_sessionmaker
from gst_copilot.embeddings import get_embedder
from gst_copilot.evals.golden import load_golden
from gst_copilot.evals.metrics import (
    contains_all,
    first_relevant_rank,
    hit_at_k,
    keyword_recall,
    mean_reciprocal_rank,
    missing_keywords,
    percentile,
    ratio,
)
from gst_copilot.rag.llm import LLMError, get_llm
from gst_copilot.rag.rerank import get_reranker
from gst_copilot.rag.service import ask


async def run(golden_path: Path, k: int, retrieval_only: bool = False) -> dict[str, Any]:
    settings = get_settings()
    items = load_golden(golden_path)
    embedder, reranker = get_embedder(), get_reranker()
    llm = None if retrieval_only else get_llm()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []

    async with get_sessionmaker()() as session:
        for item in items:
            t0 = time.perf_counter()
            llm_error = None
            try:
                result = await ask(item.question, session, embedder, llm, k, reranker)
            except LLMError as exc:
                # One failed LLM call must not lose the whole run: keep the retrieval
                # result for this question and record the error.
                llm_error = str(exc)
                result = await ask(item.question, session, embedder, None, k, reranker)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)
            retrieved_ids = [c.doc_id for c in result.retrieved]
            rank = first_relevant_rank(retrieved_ids, set(item.expected_doc_ids))
            section_rank = (
                first_relevant_rank(
                    [f"{c.doc_id}:{c.section}" for c in result.retrieved],
                    item.section_pairs,
                )
                if item.expected_sections
                else None
            )
            cited_docs = {ref.split("#")[0] for ref in result.cited}
            shown = result.context or result.retrieved  # what the LLM saw
            section_of = {c.ref: f"{c.doc_id}:{c.section}" for c in shown}
            expected_pairs = item.section_pairs
            context = "\n".join(c.text for c in shown)
            rows.append(
                {
                    "id": item.id,
                    "type": item.type,
                    "rank": rank,
                    "section_rank": section_rank,
                    "has_expected_sections": bool(item.expected_sections),
                    "retrieved": [
                        f"{c.ref} (s.{c.section}, vec #{c.vector_rank}, kw #{c.keyword_rank}"
                        f", rerank {c.rerank_score})"
                        for c in result.retrieved
                    ],
                    "context_refs": [c.ref for c in shown],
                    "context_chars": len(context),
                    "llm_error": llm_error,
                    "latency_ms": round(elapsed_ms, 1),
                    "answer": result.answer,
                    "answer_chars": len(result.answer or ""),
                    "refused": result.refused,
                    "partial": result.partial,
                    "truncated": result.truncated,
                    "keyword_recall": (
                        keyword_recall(result.answer, item.expected_keywords)
                        if result.answer is not None and not result.refused
                        else 0.0
                    ),
                    "keywords_ok": (
                        contains_all(result.answer, item.expected_keywords)
                        if result.answer is not None
                        else None
                    ),
                    "cited_expected_doc": bool(cited_docs & set(item.expected_doc_ids)),
                    # Stricter: a cited passage is from an expected (document, section).
                    "cited_expected_section": (
                        bool({section_of.get(r) for r in result.cited} & expected_pairs)
                        if expected_pairs
                        else None
                    ),
                    # Are the key phrases in the passages at all? Low = retrieval's fault;
                    # high context_recall but low keyword_recall = generation's fault.
                    "context_recall": keyword_recall(context, item.expected_keywords),
                    "missing_in_context": missing_keywords(context, item.expected_keywords),
                    "missing_in_answer": (
                        missing_keywords(result.answer, item.expected_keywords)
                        if result.answer is not None
                        else None
                    ),
                    "has_citation": bool(result.cited),
                    "invalid_citations": result.invalid_citations,
                }
            )

    answerable = [r for r in rows if r["type"] != "unanswerable"]
    unanswerable = [r for r in rows if r["type"] == "unanswerable"]
    ranks = [r["rank"] for r in answerable]
    section_ranks = [r["section_rank"] for r in answerable if r["has_expected_sections"]]
    report: dict[str, Any] = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "golden_file": str(golden_path),
        "questions": len(rows),
        "config": {
            "k": k,
            "embedding_model": settings.embedding_model,
            "embedding_provider": settings.embedding_provider,
            "chunking_strategy": settings.chunking_strategy,
            "chunker_version": settings.chunker_version,
            "chunk_size_chars": settings.chunk_size_chars,
            "chunk_overlap_chars": settings.chunk_overlap_chars,
            "retrieval_mode": settings.retrieval_mode,
            "reranker": reranker.name if reranker else None,
            "query_expansion": settings.query_expansion,
            "rerank_candidates": settings.rerank_candidates,
            "context_expansion": settings.context_expansion,
            "context_max_chars": settings.context_max_chars,
            "llm_model": settings.llm_model or None,
            "prompt_version": settings.prompt_version,
            "llm_max_tokens": settings.llm_max_tokens,
        },
        "retrieval": {
            "context_recall": ratio(sum(r["context_recall"] for r in answerable), len(answerable)),
            f"hit@{k}": round(hit_at_k(ranks, k), 3),
            "hit@1": round(hit_at_k(ranks, 1), 3),
            "mrr": round(mean_reciprocal_rank(ranks), 3),
        },
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 1),
            "p95": round(percentile(latencies, 95), 1),
        },
        "rows": rows,
    }
    if section_ranks:
        # Stricter than hit@k: the right section, not just the right document.
        report["retrieval"].update(
            {
                f"section_hit@{k}": round(hit_at_k(section_ranks, k), 3),
                "section_hit@1": round(hit_at_k(section_ranks, 1), 3),
                "section_mrr": round(mean_reciprocal_rank(section_ranks), 3),
                "section_questions": len(section_ranks),
            }
        )
    if llm is not None:
        answered = [r for r in answerable if not r["refused"] and not r["llm_error"]]
        with_citation = [r for r in answered if r["has_citation"]]
        report["answers"] = {
            "keyword_correctness": ratio(
                sum(bool(r["keywords_ok"]) for r in answered), len(answerable)
            ),
            "keyword_recall": ratio(sum(r["keyword_recall"] for r in answerable), len(answerable)),
            "citation_accuracy": ratio(
                sum(r["cited_expected_doc"] for r in with_citation), len(with_citation)
            ),
            "citation_section_accuracy": ratio(
                sum(bool(r["cited_expected_section"]) for r in with_citation),
                sum(1 for r in with_citation if r["cited_expected_section"] is not None),
            ),
            "answers_without_citation": ratio(len(answered) - len(with_citation), len(answered)),
            "invalid_citation_rate": ratio(
                sum(bool(r["invalid_citations"]) for r in rows), len(rows)
            ),
            "correct_refusal": ratio(sum(r["refused"] for r in unanswerable), len(unanswerable)),
            "false_refusal": ratio(sum(r["refused"] for r in answerable), len(answerable)),
            "partial_answers": ratio(sum(r["partial"] for r in answerable), len(answerable)),
            "truncated_answers": sum(1 for r in rows if r["truncated"]),
            "llm_errors": sum(1 for r in rows if r["llm_error"]),
        }
    return report


def print_summary(report: dict[str, Any]) -> None:
    print(f"\nGolden set: {report['golden_file']} ({report['questions']} questions)")
    runs = report.get("runs_count")
    if runs:
        print(f"Mean of {runs} runs (min-max shown where runs differ)")
    print("| Metric | Value |\n|---|---|")
    for section in ("retrieval", "answers", "latency_ms"):
        for name, value in report.get(section, {}).items():
            print(f"| {section}.{name} | {value if value is not None else 'n/a'} |")
    k = report["config"]["k"]
    answerable = [r for r in report["rows"] if r["type"] != "unanswerable"]
    misses = [r["id"] for r in answerable if r["rank"] is None]
    if misses:
        print(f"\nDocument not in top {k}: {', '.join(misses)}")
    section_misses = [
        r["id"] for r in answerable if r["has_expected_sections"] and r["section_rank"] is None
    ]
    if section_misses:
        print(f"Section not in top {k}: {', '.join(section_misses)}")
    gaps = [r for r in answerable if r.get("missing_in_context")]
    if gaps:
        print("\nKey phrases missing from the retrieved passages (retrieval or golden set):")
        for r in gaps:
            print(f"  {r['id']}: {', '.join(repr(p) for p in r['missing_in_context'])}")
    answer_gaps = [
        r
        for r in answerable
        if r.get("missing_in_answer")
        and set(r["missing_in_answer"]) - set(r.get("missing_in_context") or [])
    ]
    if answer_gaps:
        print("In the passages but missing from the answer (generation):")
        for r in answer_gaps:
            only = [p for p in r["missing_in_answer"] if p not in r["missing_in_context"]]
            print(f"  {r['id']}: {', '.join(repr(p) for p in only)}")
    errors = report.get("llm_errors_total", report.get("answers", {}).get("llm_errors", 0))
    if errors:
        print(
            f"\nWARNING: {errors} LLM call(s) failed, so the answer metrics are not valid."
            " Is the LLM running? Retrieval metrics are still correct."
        )


async def run_many(golden: Path, k: int, retrieval_only: bool, runs: int) -> list[dict[str, Any]]:
    """All runs in ONE event loop. The database pool and the LLM's HTTP connections
    belong to the loop that created them; a new asyncio.run() per run would reuse
    connections from a closed loop ("Event loop is closed")."""
    try:
        return [await run(golden, k, retrieval_only) for _ in range(max(1, runs))]
    finally:
        await get_engine().dispose()


def aggregate(reports: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    """Mean, min and max of every numeric metric across repeated runs."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for section in ("retrieval", "answers", "latency_ms"):
        names = reports[0].get(section, {})
        for name in names:
            values = [r[section][name] for r in reports if r.get(section, {}).get(name) is not None]
            if values and all(isinstance(v, int | float) for v in values):
                out.setdefault(section, {})[name] = {
                    "mean": round(sum(values) / len(values), 3),
                    "min": min(values),
                    "max": max(values),
                }
    return out


def _as_ranges(summary: dict[str, dict[str, dict[str, float]]]) -> dict[str, dict[str, str]]:
    """For printing: '0.25' when all runs agree, else '0.312 (0.25-0.375)'."""
    return {
        section: {
            name: f"{v['mean']}" if v["min"] == v["max"] else f"{v['mean']} ({v['min']}-{v['max']})"
            for name, v in metrics.items()
        }
        for section, metrics in summary.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and answers on a golden set.")
    parser.add_argument("golden", type=Path)
    parser.add_argument("--k", type=int, default=get_settings().retrieval_top_k)
    parser.add_argument("--out", type=Path, default=Path("reports"))
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="skip the LLM: retrieval metrics only, much faster (for retrieval experiments)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="repeat the whole run N times and report mean and range (LLM answers vary)",
    )
    parser.add_argument(
        "--min-hit-at-k",
        type=float,
        default=None,
        help="exit with an error if hit@k is below this (for CI)",
    )
    args = parser.parse_args()

    reports = asyncio.run(run_many(args.golden, args.k, args.retrieval_only, args.runs))
    report = reports[0]
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = args.out / f"eval-{stamp}.json"
    payload: dict[str, Any] = report if len(reports) == 1 else {"runs": reports}
    if len(reports) > 1:
        payload["summary"] = aggregate(reports)
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print_summary(
        report
        if len(reports) == 1
        else {
            **report,
            **_as_ranges(aggregate(reports)),
            "runs_count": len(reports),
            "llm_errors_total": sum(r.get("answers", {}).get("llm_errors", 0) for r in reports),
        }
    )
    print(f"\nFull report: {out_file}")

    hit = report["retrieval"][f"hit@{args.k}"]
    if args.min_hit_at_k is not None and hit < args.min_hit_at_k:
        print(f"FAIL: hit@{args.k} {hit} is below {args.min_hit_at_k}")
        sys.exit(1)


if __name__ == "__main__":
    main()
