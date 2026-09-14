import importlib.util
from pathlib import Path
from types import SimpleNamespace

import databento_dbn as dbn
import pandas as pd


def test_depth_diagnostics_exclude_bad_timestamps_and_locked_books(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/audit_wasde_depth_sample.py"
    spec = importlib.util.spec_from_file_location("depth_quality", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    event = pd.Timestamp("2025-08-12T16:05:01Z")
    frames = pd.DataFrame(
        {
            "ts_event": [event] * 3,
            "instrument_id": [1, 1, 1],
            "symbol": ["ZCZ5"] * 3,
            "bid_px_00": [400.0, 400.0, 400.0],
            "ask_px_00": [400.25, 400.25, 400.0],
            "bid_sz_00": [10, 10, 10],
            "ask_sz_00": [10, 10, 10],
            "flags": [dbn.F_LAST, dbn.F_LAST | dbn.F_BAD_TS_RECV, dbn.F_LAST],
        },
        index=[event + pd.Timedelta(milliseconds=1), event - pd.Timedelta(milliseconds=1), event],
    )
    store = SimpleNamespace(to_df=lambda **_: iter([frames.iloc[:1], frames.iloc[1:]]))
    monkeypatch.setattr(module.db, "DBNStore", SimpleNamespace(from_file=lambda _: store))
    result = module.audit(Path("2025-08-12-mbp-10.dbn.zst"))
    assert result["counts"]["records"] == 3
    assert result["counts"]["two_sided_positive_uncrossed"] == 2
    assert result["counts"]["receive_precedes_event"] == 1
    assert result["counts"]["locked_or_crossed_top"] == 1
    assert result["scheduled_window_counts"]["ZC"]["valid_end_of_event_unflagged_rows"] == 1
    assert result["execution_quality_passed"] is False
    assert result["scheduled_window_start"] == "2025-08-12T12:05:00-04:00"
