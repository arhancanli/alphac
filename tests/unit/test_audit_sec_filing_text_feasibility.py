from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_sec_filing_text_feasibility.py"
SPEC = importlib.util.spec_from_file_location("audit_sec_filing_text_feasibility", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def filler(prefix: str, words: int = 450) -> str:
    return " ".join(f"{prefix}{index}" for index in range(words))


def test_html_parser_removes_hidden_and_preserves_readable_text() -> None:
    raw = (
        b"<html><style>bad</style><p>Visible&nbsp;text</p>"
        b"<div style='display:none'>secret</div></html>"
    )
    text = MODULE.html_to_text(raw)
    assert "Visible text" in text
    assert "bad" not in text
    assert "secret" not in text


def test_extract_10k_chooses_full_sections_not_table_of_contents() -> None:
    html = f"""
      <p>Item 1A. Risk Factors</p><p>Item 1B. Unresolved Staff Comments</p>
      <h2>ITEM 1A. RISK FACTORS</h2><p>{filler("risk")}</p>
      <h2>ITEM 1B. UNRESOLVED STAFF COMMENTS</h2>
      <h2>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS</h2><p>{filler("mda")}</p>
      <h2>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES</h2>
    """.encode()
    sections = MODULE.extract_sections(MODULE.html_to_text(html), "10-K")
    assert len(sections["risk_factors"].split()) >= 450
    assert len(sections["mda"].split()) >= 450


def test_extract_10k_rejects_long_toc_and_earlier_cross_reference() -> None:
    html = f"""
      <p>Item 7. Management's Discussion and Analysis {filler("toc", 120)}</p>
      <p>Item 7A. Quantitative and Qualitative Disclosures</p>
      <p>Item 7. Management's Discussion and Analysis in this report and other warnings
      should be considered. {filler("preface", 500)}</p>
      <h2>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS</h2>
      <p>{filler("actual", 450)}</p>
      <h2>ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES</h2>
    """.encode()
    section = MODULE.extract_sections(MODULE.html_to_text(html), "10-K")["mda"]
    assert "actual449" in section
    assert "preface499" not in section
    assert "toc119" not in section


def test_extract_10q_mda_and_optional_risk_update() -> None:
    html = f"""
      <h2>Item 2. Management's Discussion and Analysis of Financial Condition and Results</h2>
      <p>{filler("quarter")}</p><h2>Item 3. Quantitative and Qualitative Disclosures</h2>
      <h2>Item 1A. Risk Factors</h2><p>{filler("update")}</p><h2>Item 2. Unregistered Sales</h2>
    """.encode()
    sections = MODULE.extract_sections(MODULE.html_to_text(html), "10-Q")
    assert len(sections["mda"].split()) >= 450
    assert len(sections["risk_factors"].split()) >= 450


def test_jaccard_is_bounded_and_detects_identity() -> None:
    text = filler("word", 30)
    assert MODULE.jaccard(text, text) == 1.0
    assert 0.0 <= MODULE.jaccard(text, filler("other", 30)) <= 1.0
