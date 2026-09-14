import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location(
    "native_audit", Path(__file__).resolve().parents[2] / "scripts/audit_refining_native_spreads.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "accepted"),
        ({"flags": 136}, "feed_state"),
        ({"flags": 0}, "feed_state"),
        ({"bid_sz_00": 1}, "insufficient_size"),
        ({"ask_px_00": -20000000}, "invalid_book"),
        ({"ask_px_00": 10000001}, "invalid_tick"),
        ({"ts_recv": pd.Timestamp(2000000001, tz="UTC")}, "clock_order"),
        ({"ts_event": pd.Timestamp(1, tz="UTC")}, "stale"),
    ],
)
def test_native_quote_filters(changes, expected):
    fields = {
        "ts_recv": pd.Timestamp(2000000000, tz="UTC"),
        "ts_event": pd.Timestamp(1999999999, tz="UTC"),
        "flags": 128,
        "bid_px_00": -10000000,
        "ask_px_00": 10000000,
        "bid_sz_00": 2,
        "ask_sz_00": 2,
    }
    fields.update(changes)
    assert module.quality(SimpleNamespace(**fields), 2000000000, 2, 10000000) == expected
