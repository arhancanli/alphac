from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_sharadar_corrected_corporate_action_lake.py"
RESULT = REPO / "artifacts" / "audit" / "sharadar_corrected_corporate_action_validation.json"


def _module():
    spec = importlib.util.spec_from_file_location("corrected_ca_audit_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validation_fails_closed_on_unresolved_split_boundaries() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert payload["decision"] == "CORPORATE_ACTION_VALIDATION_FAILED_SPLIT_BOUNDARIES"
    assert payload["dividend_gate"]["passed"] is True
    assert payload["dividend_gate"]["summary"]["rows_above_full_pre_ex_close"] == 0
    assert payload["split_gate"]["passed"] is False
    assert payload["split_gate"]["summary"] == {
        "split_groups": 4662,
        "consistent": 4189,
        "reciprocal_ratio_would_verify": 3,
        "unexplained_price_boundary": 109,
        "missing_two_sided_price_boundary": 361,
        "failed_or_unverifiable": 473,
        "affected_instruments": 401,
    }
    assert len(payload["split_gate"]["failures"]) == 473
    assert payload["hypotheses_spent"] == 0
    assert payload["return_data_opened"] is False
    assert payload["content_hash"] == _module()._content_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
