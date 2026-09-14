import runpy
from pathlib import Path
from types import SimpleNamespace

import databento_dbn as dbn
import pandas as pd
import pytest


@pytest.mark.parametrize("unordered", [False, True])
def test_latest_bad_row_blocks_across_chunks_and_future_row_is_excluded(monkeypatch, unordered):
    script = runpy.run_path(
        str(Path(__file__).parents[2] / "scripts/probe_wasde_execution_depth.py")
    )
    at = pd.Timestamp("2025-08-12T16:05:00Z")
    definition = pd.DataFrame(
        {"instrument_id": [42], "symbol": ["ZCZ5"], "ts_event": [at - pd.Timedelta(hours=1)]},
        index=[at - pd.Timedelta(minutes=1)],
    )
    status = pd.DataFrame(
        {"instrument_id": [42], "ts_event": [at], "is_trading": ["Y"], "is_quoting": ["Y"]},
        index=[at],
    )
    base = {"instrument_id": 42, "ts_event": at, "action": "M", "sequence": 10, "flags": dbn.F_LAST}
    for i in range(10):
        base.update(
            {
                f"bid_px_{i:02}": 99 - i,
                f"ask_px_{i:02}": 101 + i,
                f"bid_sz_{i:02}": 10,
                f"ask_sz_{i:02}": 10,
            }
        )
    first = pd.DataFrame([base], index=[at])
    second = pd.DataFrame(
        [base | {"flags": dbn.F_LAST | dbn.F_MAYBE_BAD_BOOK}, base],
        index=[at + pd.Timedelta(milliseconds=100), at + pd.Timedelta(seconds=1)],
    )
    if unordered:
        second = second.iloc[::-1]

    def load(path):
        if "definition" in path.name:
            return SimpleNamespace(to_df=lambda: definition)
        if "status" in path.name:
            return SimpleNamespace(to_df=lambda: status)
        return SimpleNamespace(to_df=lambda **kwargs: iter([first, second]))

    monkeypatch.setattr(script["db"].DBNStore, "from_file", load)
    if unordered:
        with pytest.raises(ValueError, match="unordered"):
            script["probe"]("2025-08-12", "2025-08-13", ["ZCZ5"])
    else:
        results = script["probe"]("2025-08-12", "2025-08-13", ["ZCZ5"])
        entry = [r for r in results if r["label"] == "entry_clock"]
        assert len(entry) == 6
        assert all(r["reason"] == "flagged_or_incomplete_event" for r in entry)
        assert all(r["book_received_ns"] == second.index[0].value for r in entry)
