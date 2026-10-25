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
    mean_reciprocal_rank,
    percentile,
    ratio,
)
from gst_copilot.rag.llm import get_llm
from gst_copilot.rag.prompt import PROMPT_VERSION
from gst_copilot.rag.service import ask


async def run(golden_path: Path, k: int) -> dict[str, Any]:
    settings = get_settings()
    items = load_golden(golden_path)
    embedder, llm = get_embedder(), get_llm()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []

    async with get_sessionmaker()() as session:
        for item in items:
            t0 = time.perf_counter()
            result = await ask(item.question, session, embedder, llm, k)
            latencies.append((time.perf_counter() - t0) * 1000)
            retrieved_ids = [c.doc_id for c in result.retrieved]
            rank = first_relevant_rank(retrieved_ids, set(item.expected_doc_ids))
            section_rank = (
                first_relevant_rank(
                    [f"{c.doc_id}:{c.section}" for c in result.retrieved],
                    {f"{d}:{s}" for d in item.expected_doc_ids for s in item.expected_sections},
                )
                if item.expected_sections
                else None
            )
            cited_docs = {ref.split("#")[0] for ref in result.cited}
            rows.append(
                {
                    "id": item.id,
                    "type": item.type,
                    "rank": rank,
                    "section_rank": section_rank,
                    "has_expected_sections": bool(item.expected_sections),
                    "retrieved": [f"{c.ref} (s.{c.section})" for c in result.retrieved],
                    "answer": result.answer,
                    "refused": result.refused,
                    "keywords_ok": (
                        contains_all(result.answer, item.expected_keywords)
                        if result.answer is not None
                        else None
                    ),
                    "cited_expected_doc": bool(cited_docs & set(item.expected_doc_ids)),
                    "has_citation": bool(result.cited),
                    "invalid_citations": result.invalid_citations,
                }
            )
    await get_engine().dispose()

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
            "llm_model": settings.llm_model or None,
            "prompt_version": PROMPT_VERSION,
        },
        "retrieval": {
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
        answered = [r for r in answerable if not r["refused"]]
        with_citation = [r for r in answered if r["has_citation"]]
        report["answers"] = {
            "keyword_correctness": ratio(
                sum(bool(r["keywords_ok"]) for r in answered), len(answerable)
            ),
            "citation_accuracy": ratio(
                sum(r["cited_expected_doc"] for r in with_citation), len(with_citation)
            ),
            "answers_without_citation": ratio(len(answered) - len(with_citation), len(answered)),
            "invalid_citation_rate": ratio(
                sum(bool(r["invalid_citations"]) for r in rows), len(rows)
            ),
            "correct_refusal": ratio(sum(r["refused"] for r in unanswerable), len(unanswerable)),
            "false_refusal": ratio(sum(r["refused"] for r in answerable), len(answerable)),
        }
    return report


def print_summary(report: dict[str, Any]) -> None:
    print(f"\nGolden set: {report['golden_file']} ({report['questions']} questions)")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and answers on a golden set.")
    parser.add_argument("golden", type=Path)
    parser.add_argument("--k", type=int, default=get_settings().retrieval_top_k)
    parser.add_argument("--out", type=Path, default=Path("reports"))
    parser.add_argument(
        "--min-hit-at-k",
        type=float,
        default=None,
        help="exit with an error if hit@k is below this (for CI)",
    )
    args = parser.parse_args()

    report = asyncio.run(run(args.golden, args.k))
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = args.out / f"eval-{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"\nFull report: {out_file}")

    hit = report["retrieval"][f"hit@{args.k}"]
    if args.min_hit_at_k is not None and hit < args.min_hit_at_k:
        print(f"FAIL: hit@{args.k} {hit} is below {args.min_hit_at_k}")
        sys.exit(1)


if __name__ == "__main__":
    main()
