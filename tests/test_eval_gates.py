"""Tests for RAG quality gates and CI summary reporting."""

import subprocess
import sys
from typing import Any

from gst_copilot.evals.gates import (
    QualityGate,
    evaluate_gates,
    format_markdown_summary,
)


def _sample_report() -> dict[str, Any]:
    return {
        "golden_file": "evals/golden.jsonl",
        "questions": 4,
        "config": {
            "k": 3,
            "llm_model": "mock-qwen",
            "prompt_version": "m2-v7",
        },
        "retrieval": {
            "hit@3": 1.0,
            "section_hit@3": 0.85,
            "context_recall": 0.92,
            "mrr": 0.95,
        },
        "answers": {
            "citation_accuracy": 0.88,
            "citation_section_accuracy": 0.82,
            "invalid_citation_rate": 0.0,
            "keyword_recall": 0.80,
            "false_refusal": 0.05,
            "correct_refusal": 1.0,
        },
        "judge": {
            "faithful": 0.95,
            "correct": 0.90,
        },
        "latency_ms": {
            "p50": 850.0,
            "p95": 1400.0,
            "ttft_p50": 320.0,
        },
    }


def test_evaluate_gates_all_pass() -> None:
    report = _sample_report()
    gates = [
        QualityGate("retrieval.hit@3", ">=", 0.90, "Hit@3 threshold"),
        QualityGate("retrieval.section_hit@3", ">=", 0.80, "Section hit threshold"),
        QualityGate("answers.citation_accuracy", ">=", 0.85, "Citation accuracy"),
        QualityGate("answers.invalid_citation_rate", "<=", 0.0, "Zero hallucinations"),
        QualityGate("answers.false_refusal", "<=", 0.10, "Low false refusal"),
        QualityGate("judge.faithful", ">=", 0.90, "Faithfulness threshold"),
    ]

    results = evaluate_gates(report, gates)
    assert len(results) == 6
    assert all(r.passed for r in results)
    for r in results:
        assert "PASS" in r.message


def test_evaluate_gates_detects_regression() -> None:
    report = _sample_report()
    gates = [
        QualityGate("retrieval.hit@3", ">=", 1.0, "Must be perfect"),
        QualityGate("answers.invalid_citation_rate", "<=", -0.01, "Impossible threshold"),
        QualityGate("answers.false_refusal", "<=", 0.02, "Threshold lower than actual 0.05"),
    ]

    results = evaluate_gates(report, gates)
    assert results[0].passed is True
    assert results[1].passed is False
    assert "FAIL" in results[1].message
    assert results[2].passed is False
    assert "FAIL" in results[2].message


def test_evaluate_gates_handles_missing_metric() -> None:
    report = {"retrieval": {"hit@3": 1.0}}
    gates = [
        QualityGate("answers.citation_accuracy", ">=", 0.80, "Citation check"),
    ]

    results = evaluate_gates(report, gates)
    assert len(results) == 1
    assert results[0].passed is False
    assert "missing or not numeric" in results[0].message


def test_format_markdown_summary() -> None:
    report = _sample_report()
    gates = [
        QualityGate("retrieval.hit@3", ">=", 0.90, "Hit@3 threshold"),
        QualityGate("answers.invalid_citation_rate", "<=", 0.0, "Zero hallucinations"),
    ]
    gate_results = evaluate_gates(report, gates)

    md = format_markdown_summary(report, gate_results)
    assert "## GST Copilot: RAG Evaluation Report" in md
    assert "### Quality Gates: **PASSED (All Gates Met)**" in md
    assert "| `retrieval.hit@3`" in md
    assert "| `answers.invalid_citation_rate`" in md
    assert "| **Retrieval (Document)** | Hit@3 | `1.0` |" in md
    assert "| **Generation (Grounding)** | Citation Accuracy | `0.88` |" in md
    assert "| **Judge (NLI Faithfulness)** | Faithful Claims Rate | `0.95` |" in md


def test_cli_help_includes_quality_gates() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gst_copilot.evals", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--min-section-hit" in result.stdout
    assert "--min-context-recall" in result.stdout
    assert "--min-citation-accuracy" in result.stdout
    assert "--max-invalid-citations" in result.stdout
    assert "--max-false-refusal" in result.stdout
    assert "--markdown-summary" in result.stdout
