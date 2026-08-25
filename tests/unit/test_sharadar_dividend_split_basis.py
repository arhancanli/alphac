from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit_sharadar_dividend_split_basis.py"


def _module():
    spec = importlib.util.spec_from_file_location("dividend_split_basis_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_future_reverse_split_rebases_adjusted_dividend_to_raw_basis() -> None:
    offenders = pd.DataFrame(
        [
            {
                "instrument_id": "XUSE:CASH:TESTUSD",
                "ex_date": "2020-01-02T00:00:00+00:00",
                "cash_amount": 100.0,
                "pre_close": 2.0,
                "pre_close_multiple": 50.0,
            },
            {
                "instrument_id": "XUSE:CASH:OPENUSD",
                "ex_date": "2020-01-02T00:00:00+00:00",
                "cash_amount": 3.0,
                "pre_close": 2.0,
                "pre_close_multiple": 1.5,
            },
        ]
    )
    actions = pd.DataFrame(
        [
            {"date": "2021-01-01", "action": "split", "ticker": "TEST", "value": 0.01},
            {
                "date": "2021-01-01",
                "action": "adrratiosplit",
                "ticker": "TEST",
                "value": 100.0,
            },
            {"date": "2019-01-01", "action": "split", "ticker": "TEST", "value": 0.1},
        ]
    )
    result = _module().classify_rows(offenders, actions)
    assert result.iloc[0]["candidate_raw_cash_amount"] == 1.0
    assert result.iloc[0]["classification"] == (
        "ARITHMETICALLY_RECONCILED_BY_FUTURE_SPLITS"
    )
    assert result.iloc[1]["classification"] == (
        "REMAINS_UNRESOLVED_AFTER_FUTURE_SPLITS"
    )


def test_workspace_audit_preserves_residual_quarantine() -> None:
    payload = _module().build_audit()
    assert payload["decision"] == (
        "SPLIT_BASIS_HYPOTHESIS_SUPPORTED_CORRECTION_NOT_AUTHORIZED"
    )
    assert payload["summary"]["source_offending_rows"] == 422
    assert payload["summary"]["arithmetically_reconciled_rows"] == 421
    assert payload["summary"]["residual_unresolved_rows"] == 1
    assert payload["summary"]["residual_unresolved_instruments"] == 1
