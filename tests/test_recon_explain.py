"""Unit tests for reconciliation label explanations, citations, and GSTR-3B mappings (ADR 0026)."""

from pathlib import Path

import pytest

from gst_copilot.recon import synth
from gst_copilot.recon.__main__ import main
from gst_copilot.recon.explain import (
    EXPLANATIONS,
    LabelExplanation,
    all_explanations,
    explain_label,
)
from gst_copilot.recon.models import LABELS, Label


def test_every_label_has_an_explanation() -> None:
    assert set(EXPLANATIONS.keys()) == set(LABELS)
    assert len(EXPLANATIONS) == 10


@pytest.mark.parametrize("label", LABELS)
def test_explanation_fields_are_non_empty(label: Label) -> None:
    info = explain_label(label)
    assert isinstance(info, LabelExplanation)
    assert info.label == label
    assert info.title.strip() != ""
    assert info.explanation.strip() != ""
    assert info.action.strip() != ""
    assert info.gstr3b_row.strip() != ""
    assert info.citation.strip() != ""


def test_specific_statutory_citations() -> None:
    # Key legal citations grounded in CGST Act and Circular 170
    assert "16(2)(aa)" in explain_label("missing_in_2b").citation
    assert "36(4)" in explain_label("missing_in_2b").citation

    assert "16(2)(b)" in explain_label("missing_in_books").citation
    assert "Circular 170" in explain_label("missing_in_books").citation

    assert "16(4)" in explain_label("itc_unavailable").citation
    assert "4(D)(2)" in explain_label("itc_unavailable").gstr3b_row

    assert "4(B)(2)" in explain_label("missing_in_books").gstr3b_row
    assert "4(A)(5)" in explain_label("matched").gstr3b_row


def test_explain_unknown_label_raises_key_error() -> None:
    with pytest.raises(KeyError, match="Unknown reconciliation label"):
        explain_label("invalid_label")  # type: ignore[arg-type]


def test_all_explanations_returns_copy() -> None:
    all_exp = all_explanations()
    assert len(all_exp) == len(LABELS)
    all_exp.clear()
    assert len(EXPLANATIONS) == len(LABELS)


def test_cli_explain_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    synth.main(["--out", str(tmp_path), "--invoices", "30", "--seed", "1"])
    capsys.readouterr()
    assert main([str(tmp_path), "--explain"]) == 0
    out = capsys.readouterr().out
    assert "### Statutory Explanations and GSTR-3B Placement" in out
    assert "Table 4" in out
    assert "Citation:" in out
