from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_vate_2020_dividend_vendor_resolution.py"


def _module():
    spec = importlib.util.spec_from_file_location("vate_dividend_resolution_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolution_authorizes_only_exact_row_quarantine() -> None:
    filing = b"""
    <html><body>does not anticipate paying cash dividends in the foreseeable future.
    Preferred Share Dividends</body></html>
    """
    payload = _module().build(
        {"corporate_actions": {"cash_dividends": []}},
        filing,
        retrieved_at="2026-08-23T00:00:00+00:00",
    )
    assert payload["decision"] == (
        "VERSIONED_UNSUPPORTED_DIVIDEND_ROW_QUARANTINE_AUTHORIZED"
    )
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["repair_contract"] == {
        "original_lake_mutation_permitted": False,
        "versioned_exact_row_quarantine_permitted": True,
        "cash_amount_imputation_permitted": False,
        "rows_permitted_to_remove": [payload["source_row"]],
    }
