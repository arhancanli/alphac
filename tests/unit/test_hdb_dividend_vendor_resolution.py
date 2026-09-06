from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_hdb_dividend_vendor_resolution.py"
RESULT = REPO / "artifacts" / "audit" / "hdb_dividend_vendor_resolution.json"


def _module():
    spec = importlib.util.spec_from_file_location("hdb_dividend_vendor_resolution_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendor_resolution_authorizes_only_versioned_zero_marker_quarantine() -> None:
    module = _module()
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["content_hash"] == module._content_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    assert payload["decision"] == "VERSIONED_ZERO_MARKER_QUARANTINE_AUTHORIZED"
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["bound_due_bill_record"]["due_bill_on_date"] == "2025-06-26"
    assert payload["bound_due_bill_record"]["ex_date"] == "2025-08-11"
    assert payload["bound_due_bill_record"]["rate"] == 0.641432
    assert payload["gates"]["historical_vendor_creation_time_established"] is False
    assert payload["gates"]["automatic_cash_amount_imputation_permitted"] is False
    assert payload["gates"]["original_lake_mutation_permitted"] is False
    assert payload["gates"]["versioned_exact_row_quarantine_permitted"] is True
    assert len(payload["vendor_rows"]) == 3
