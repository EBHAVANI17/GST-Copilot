"""Score a reconciliation against the ground truth from synth.py.

A prediction counts only if it pairs exactly the same rows AND gives the same
label. Per label: precision = right / predicted with that label, recall = right /
expected with that label.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from gst_copilot.recon.matcher import Result
from gst_copilot.recon.models import LABELS, Expected


@dataclass(frozen=True)
class LabelScore:
    expected: int
    predicted: int
    correct: int

    @property
    def precision(self) -> float | None:
        return round(self.correct / self.predicted, 3) if self.predicted else None

    @property
    def recall(self) -> float | None:
        return round(self.correct / self.expected, 3) if self.expected else None


def score(results: Iterable[Result], expected: Iterable[Expected]) -> dict[str, LabelScore]:
    pred = {(r.books_id, r.gstr2b_id, r.label) for r in results}
    truth = {(e.books_id, e.gstr2b_id, e.label) for e in expected}
    right: Counter[str] = Counter(label for _, _, label in pred & truth)
    n_pred: Counter[str] = Counter(label for _, _, label in pred)
    n_true: Counter[str] = Counter(label for _, _, label in truth)
    out = {
        label: LabelScore(n_true[label], n_pred[label], right[label])
        for label in LABELS
        if n_true[label] or n_pred[label]
    }
    out["all"] = LabelScore(sum(n_true.values()), sum(n_pred.values()), sum(right.values()))
    return out


def render(scores: dict[str, LabelScore]) -> str:
    lines = [
        "| Label | Expected | Predicted | Correct | Precision | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for label, s in scores.items():
        lines.append(
            f"| {label} | {s.expected} | {s.predicted} | {s.correct} | "
            f"{'n/a' if s.precision is None else s.precision} | "
            f"{'n/a' if s.recall is None else s.recall} |"
        )
    return "\n".join(lines)
