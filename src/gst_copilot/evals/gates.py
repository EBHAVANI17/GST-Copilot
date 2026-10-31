"""Quality gates and CI reporting for the evaluation pipeline.

Allows CI/CD workflows and engineers to enforce strict RAG Triad thresholds:
- Context Recall & Hit@k (Retrieval)
- Section-Level Accuracy (Precise statutory grounding)
- Citation Accuracy & Invalid Citation Rate (Hallucination prevention)
- Faithfulness & Correctness (LLM-as-judge)
- False Refusal Rate (Usability & coverage)
"""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class QualityGate:
    # e.g. "retrieval.hit@5", "answers.citation_accuracy", "answers.invalid_citation_rate"
    metric_path: str
    operator: Literal[">=", "<="]
    threshold: float
    description: str


@dataclass(frozen=True)
class GateResult:
    gate: QualityGate
    actual_value: float | None
    passed: bool
    message: str


def evaluate_gates(report: dict[str, Any], gates: list[QualityGate]) -> list[GateResult]:
    """Check every quality gate against the evaluation report metrics."""
    results: list[GateResult] = []

    for gate in gates:
        parts = gate.metric_path.split(".")
        val: Any = report
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                val = None
                break

        if val is None or not isinstance(val, int | float):
            # Metric missing from report (e.g. LLM metrics when retrieval-only run)
            results.append(
                GateResult(
                    gate=gate,
                    actual_value=None,
                    passed=False,
                    message=f"Metric '{gate.metric_path}' is missing or not numeric in report.",
                )
            )
            continue

        actual = float(val)
        if gate.operator == ">=":
            passed = actual >= gate.threshold
            symbol = ">="
        else:
            passed = actual <= gate.threshold
            symbol = "<="

        status_text = "PASS" if passed else "FAIL"
        msg = (
            f"[{status_text}] {gate.metric_path}: actual {actual:.3f} "
            f"{symbol} threshold {gate.threshold:.3f} ({gate.description})"
        )
        results.append(GateResult(gate=gate, actual_value=actual, passed=passed, message=msg))

    return results


def format_markdown_summary(
    report: dict[str, Any],
    gate_results: list[GateResult] | None = None,
) -> str:
    """Generate a GitHub Actions Step Summary markdown report (GFM)."""
    lines: list[str] = []
    lines.append("## GST Copilot: RAG Evaluation Report")
    lines.append("")

    # Metadata & Config
    golden_file = report.get("golden_file", "unknown")
    questions = report.get("questions", 0)
    config = report.get("config", {})
    k = config.get("k", 5)
    model = config.get("llm_model") or "None (Retrieval Only)"
    prompt = config.get("prompt_version") or "n/a"

    lines.append(f"- **Golden Dataset:** `{golden_file}` ({questions} questions)")
    lines.append(f"- **LLM / Prompt:** `{model}` (prompt `{prompt}`)")
    lines.append(f"- **Top-K Chunks:** `{k}`")
    lines.append("")

    # Quality Gates Table (if any gates were evaluated)
    if gate_results:
        all_passed = all(g.passed for g in gate_results)
        verdict = "PASSED (All Gates Met)" if all_passed else "FAILED (Regression Detected)"
        lines.append(f"### Quality Gates: **{verdict}**")
        lines.append("")
        lines.append("| Quality Gate | Operator | Threshold | Actual | Status |")
        lines.append("| :--- | :---: | :---: | :---: | :---: |")

        for gr in gate_results:
            status_badge = "**PASS**" if gr.passed else "**FAIL**"
            actual_str = f"{gr.actual_value:.3f}" if gr.actual_value is not None else "n/a"
            lines.append(
                f"| `{gr.gate.metric_path}`<br>*{gr.gate.description}* "
                f"| `{gr.gate.operator}` "
                f"| `{gr.gate.threshold:.3f}` "
                f"| `{actual_str}` "
                f"| {status_badge} |"
            )
        lines.append("")

    # RAG Triad & Performance Metrics
    lines.append("### RAG Triad & Performance Metrics")
    lines.append("")
    lines.append("| Metric Category | Metric | Score / Value | Target Benchmark |")
    lines.append("| :--- | :--- | :---: | :---: |")

    # 1. Retrieval (Context Precision & Recall)
    retrieval = report.get("retrieval", {})
    if retrieval:
        hit_k = retrieval.get(f"hit@{k}", "n/a")
        sec_hit_k = retrieval.get(f"section_hit@{k}", "n/a")
        mrr = retrieval.get("mrr", "n/a")
        sec_mrr = retrieval.get("section_mrr", "n/a")
        ctx_recall = retrieval.get("context_recall", "n/a")

        lines.append(f"| **Retrieval (Document)** | Hit@{k} | `{hit_k}` | >= 0.900 |")
        lines.append(f"| **Retrieval (Document)** | MRR | `{mrr}` | >= 0.850 |")
        lines.append(f"| **Retrieval (Section)** | Section Hit@{k} | `{sec_hit_k}` | >= 0.800 |")
        lines.append(f"| **Retrieval (Section)** | Section MRR | `{sec_mrr}` | >= 0.750 |")
        lines.append(f"| **Retrieval (Context)** | Context Recall | `{ctx_recall}` | >= 0.850 |")

    # 2. Answers & Grounding
    answers = report.get("answers", {})
    if answers:
        cit_acc = answers.get("citation_accuracy", "n/a")
        cit_sec_acc = answers.get("citation_section_accuracy", "n/a")
        inv_cit = answers.get("invalid_citation_rate", "n/a")
        kw_recall = answers.get("keyword_recall", "n/a")
        false_ref = answers.get("false_refusal", "n/a")
        corr_ref = answers.get("correct_refusal", "n/a")

        lines.append(f"| **Generation (Grounding)** | Citation Accuracy | `{cit_acc}` | >= 0.850 |")
        lines.append(
            f"| **Generation (Grounding)** | Section Citation Acc | `{cit_sec_acc}` | >= 0.800 |"
        )
        lines.append(
            f"| **Generation (Hallucination)** | Invalid Citation Rate | `{inv_cit}` | **0.000** |"
        )
        lines.append(f"| **Generation (Keywords)** | Keyword Recall | `{kw_recall}` | >= 0.750 |")
        lines.append(f"| **Generation (Safety)** | Correct Refusals | `{corr_ref}` | 1.000 |")
        lines.append(f"| **Generation (Safety)** | False Refusal Rate | `{false_ref}` | <= 0.100 |")

    # 3. LLM-as-Judge
    judge = report.get("judge", {})
    if judge:
        faithful = judge.get("faithful", "n/a")
        correct = judge.get("correct", "n/a")
        lines.append(
            f"| **Judge (NLI Faithfulness)** | Faithful Claims Rate | `{faithful}` | >= 0.900 |"
        )
        lines.append(
            f"| **Judge (Verdict Correctness)** | Overall Correct Rate | `{correct}` | >= 0.850 |"
        )

    # 4. Latency
    latency = report.get("latency_ms", {})
    if latency:
        p50 = latency.get("p50", "n/a")
        p95 = latency.get("p95", "n/a")
        ttft_p50 = latency.get("ttft_p50", "n/a")
        lines.append(f"| **Latency** | Total Latency (p50) | `{p50} ms` | <= 2000 ms |")
        lines.append(f"| **Latency** | Total Latency (p95) | `{p95} ms` | <= 4000 ms |")
        if ttft_p50 != "n/a":
            lines.append(f"| **Latency** | TTFT (p50) | `{ttft_p50} ms` | <= 1000 ms |")

    lines.append("")
    return "\n".join(lines)
