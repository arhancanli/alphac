from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_operating_margin_replay_root_cause.py"


@pytest.mark.workspace_evidence
def test_root_cause_binds_first_dividend_and_cmct_contamination() -> None:
    spec = importlib.util.spec_from_file_location("operating_margin_root_cause_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = module.build_finding()
    assert payload["status"] == "ROOT_CAUSE_ESTABLISHED_REPLAY_REMAINS_INVALID"
    assert payload["hypotheses_spent"] == 0
    first = payload["causal_chain"][1]
    assert first["orders_byte_equal"] is True
    assert first["fills_byte_equal"] is True
    assert first["equity_delta"] == pytest.approx(1.15)
    dominant = payload["causal_chain"][2]["dominant_row"]
    assert dominant["instrument_id"] == "XUSE:CASH:CMCTUSD"
    assert dominant["cash_amount"] == 112_500.0
    assert dominant["cashflow_quote"] == 7_312_500.0
    assert payload["causal_chain"][3]["rows_above_full_pre_ex_close"] == 422
