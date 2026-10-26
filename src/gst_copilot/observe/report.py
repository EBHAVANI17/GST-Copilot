"""Summaries of real usage from ask_logs, for error analysis.

    python -m gst_copilot.observe --days 7

Shows volume, refusal / partial / invented-citation rates, latency per stage (and
time to first token for streamed answers), feedback, and the questions worth turning
into golden questions: every "not helpful" and every refusal (either a corpus gap or
a false refusal).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.db.models import AskLog
from gst_copilot.evals.metrics import percentile
from gst_copilot.observe.cost import cost_section, prices_from_settings

PART_OF_GENERATE = {"first_token"}


@dataclass
class UsageReport:
    since: datetime
    asks: int = 0
    by_mode: dict[str, int] = field(default_factory=dict)
    rates: dict[str, float | None] = field(default_factory=dict)
    latency_ms: dict[str, dict[str, float]] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    feedback: dict[str, int] = field(default_factory=dict)
    thumbs_down: list[dict[str, Any]] = field(default_factory=list)
    refusals: list[dict[str, Any]] = field(default_factory=list)


async def build_report(session: AsyncSession, days: float = 7.0, limit: int = 20) -> UsageReport:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = list(
        await session.scalars(
            select(AskLog).where(AskLog.created_at >= since).order_by(AskLog.created_at.desc())
        )
    )
    rep = UsageReport(since=since, asks=len(rows))
    for r in rows:
        rep.by_mode[r.mode] = rep.by_mode.get(r.mode, 0) + 1
    generated = [r for r in rows if r.mode == "generated"]

    def rate(n: int, d: int) -> float | None:
        return round(n / d, 3) if d else None

    rep.rates = {
        "refused": rate(sum(r.refused for r in generated), len(generated)),
        "partial": rate(sum(r.partial for r in generated), len(generated)),
        "truncated": rate(sum(r.truncated for r in generated), len(generated)),
        "invented_citations": rate(
            sum(bool(r.invalid_citations) for r in generated), len(generated)
        ),
        "no_citation": rate(
            sum(1 for r in generated if not r.cited and not r.refused), len(generated)
        ),
    }
    stages: dict[str, list[float]] = {}
    for r in rows:
        t = {k: float(v) for k, v in (r.timings_ms or {}).items()}
        for stage, ms in t.items():
            stages.setdefault(stage, []).append(ms)
        # first_token is the part of "generate" before the first word, not a stage.
        total = sum(v for k, v in t.items() if k not in PART_OF_GENERATE)
        stages.setdefault("total", []).append(total)
        if "first_token" in t:  # streamed: what the user waited before text appeared
            ttft = total - t.get("generate", 0.0) + t["first_token"]
            stages.setdefault("time_to_first_token", []).append(ttft)
    rep.latency_ms = {
        s: {"p50": round(percentile(v, 50), 1), "p95": round(percentile(v, 95), 1)}
        for s, v in stages.items()
    }
    rep.cost = cost_section(
        ((r.prompt_tokens, r.completion_tokens) for r in generated), prices_from_settings()
    )
    rep.feedback = {
        "helpful": sum(1 for r in rows if r.feedback == 1),
        "not_helpful": sum(1 for r in rows if r.feedback == -1),
        "none": sum(1 for r in rows if r.feedback is None),
    }
    rep.thumbs_down = [_brief(r) for r in rows if r.feedback == -1][:limit]
    rep.refusals = [_brief(r) for r in generated if r.refused][:limit]
    return rep


def _brief(r: AskLog) -> dict[str, Any]:
    return {
        "ask_id": r.id,
        "at": r.created_at.isoformat(timespec="minutes") if r.created_at else None,
        "question": r.question,
        "note": r.feedback_note,
        "top_refs": [p.get("ref") for p in (r.retrieved or [])][:3],
    }


def render(rep: UsageReport) -> str:
    lines = [f"# GST Copilot usage since {rep.since:%Y-%m-%d %H:%M} UTC", ""]
    lines.append(
        f"Questions: {rep.asks}  " + ", ".join(f"{k}: {v}" for k, v in rep.by_mode.items())
    )
    lines += ["", "| Rate (generated answers) | Value |", "|---|---|"]
    lines += [f"| {k} | {'n/a' if v is None else v} |" for k, v in rep.rates.items()]
    lines += ["", "| Stage | p50 ms | p95 ms |", "|---|---|---|"]
    lines += [f"| {s} | {v['p50']} | {v['p95']} |" for s, v in rep.latency_ms.items()]
    if rep.cost:
        lines += ["", "| Tokens and cost (generated answers) | Value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in rep.cost.items()]
    fb = rep.feedback
    lines += [
        "",
        f"Feedback: helpful {fb.get('helpful', 0)}, not helpful {fb.get('not_helpful', 0)}",
    ]
    for title, items in (("Not helpful", rep.thumbs_down), ("Refused", rep.refusals)):
        lines += ["", f"## {title}"]
        lines += [
            f"- #{i['ask_id']} {i['question']}"
            + (f"  (note: {i['note']})" if i["note"] else "")
            + f"  top: {', '.join(i['top_refs'])}"
            for i in items
        ] or ["- none"]
    return "\n".join(lines)
