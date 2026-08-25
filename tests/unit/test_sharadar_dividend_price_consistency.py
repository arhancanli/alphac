from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_sharadar_dividend_price_consistency.py"
)
SPEC = importlib.util.spec_from_file_location("dividend_price_consistency_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_asof_audit_uses_strictly_pre_ex_raw_close(tmp_path: Path) -> None:
    actions = tmp_path / "actions.parquet"
    bars = tmp_path / "bars.parquet"
    pd.DataFrame(
        {
            "instrument_id": ["XUSE:CASH:AUSD", "XUSE:CASH:AUSD"],
            "action_type": ["dividend", "dividend"],
            "ex_date": pd.to_datetime(["2026-01-03", "2026-01-04"], utc=True),
            "available_at": pd.to_datetime(["2026-01-03", "2026-01-04"], utc=True),
            "cash_amount": [1.0, 200.0],
        }
    ).to_parquet(actions)
    pd.DataFrame(
        {
            "instrument_id": ["XUSE:CASH:AUSD", "XUSE:CASH:AUSD", "XUSE:CASH:AUSD"],
            "ts_open": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-04"], utc=True),
            "close": [90.0, 100.0, 1.0],
        }
    ).to_parquet(bars)
    result = MODULE.audit_frames(str(actions), str(bars))
    assert list(result["pre_close"]) == [100.0, 100.0]
    assert list(result["pre_close_multiple"]) == [2.0, 0.01]
