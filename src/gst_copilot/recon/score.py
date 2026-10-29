"""Score a reconciliation against the ground truth from synth.py.

A prediction counts only if it pairs exactly the same rows AND gives the same
label. Per label: precision = right / predicted with that label, recall = right /
expected with that label.

    python -m gst_copilot.recon.score --seeds 1-10 --invoices 150 [--hard]

scores the matcher on many generated seeds and prints one table (counts added up).
"""

import argparse
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from gst_copilot.recon import synth
from gst_copilot.recon.matcher import Result, reconcile
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


def add_up(tables: Iterable[dict[str, LabelScore]]) -> dict[str, LabelScore]:
    """One table from many: counts summed per label, in LABELS order, "all" last."""
    total: dict[str, tuple[int, int, int]] = {}
    for table in tables:
        for label, s in table.items():
            e, p, c = total.get(label, (0, 0, 0))
            total[label] = (e + s.expected, p + s.predicted, c + s.correct)
    order = [label for label in (*LABELS, "all") if label in total]
    return {label: LabelScore(*total[label]) for label in order}


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score the matcher on generated seeds.")
    p.add_argument("--seeds", default="1-10", help="first-last, e.g. 1-10")
    p.add_argument("--invoices", type=int, default=150)
    p.add_argument("--hard", action="store_true")
    args = p.parse_args(argv)
    first, last = (int(x) for x in args.seeds.split("-"))
    tables = []
    for seed in range(first, last + 1):
        books, twob, expected = synth.generate(seed, args.invoices, hard=args.hard)
        tables.append(score(reconcile(books, twob), expected))
    mode = "hard" if args.hard else "easy"
    print(f"{mode} data, seeds {args.seeds}, {args.invoices} invoices each")
    print(render(add_up(tables)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
