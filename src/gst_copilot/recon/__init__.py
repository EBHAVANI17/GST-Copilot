"""ITC reconciliation: the purchase register (the books) against GSTR-2B.

Deterministic Python rules decide every match and mismatch, so the numbers are
exact and testable; explain.py maps each label to statutory rules and GSTR-3B placements (M4.4).
All data here is synthetic (see synth.py).
"""

from gst_copilot.recon.explain import (
    EXPLANATIONS,
    LabelExplanation,
    all_explanations,
    explain_label,
)
from gst_copilot.recon.gstr3b import (
    DraftTable4,
    Table4Row,
    TaxBreakdown,
    compile_table4,
)

__all__ = [
    "EXPLANATIONS",
    "LabelExplanation",
    "all_explanations",
    "explain_label",
    "DraftTable4",
    "Table4Row",
    "TaxBreakdown",
    "compile_table4",
]
