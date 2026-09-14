import runpy
from pathlib import Path

import databento_dbn as dbn
import pandas as pd
import pytest

STATE = runpy.run_path(str(Path(__file__).parents[2] / "scripts/audit_share_class_quotes.py"))[
    "latest_state"
]
AT = pd.Timestamp("2025-08-12T14:01:00Z")


def frame(changes=None, offsets=(0,)):
    rows = []
    for offset in offsets:
        rows.append(
            {
                "ts_event": AT + pd.Timedelta(milliseconds=offset),
                "flags": dbn.F_LAST,
                "action": "M",
                "bid_px_00": 10.0,
                "ask_px_00": 11.0,
                "bid_sz_00": 100,
                "ask_sz_00": 100,
            }
            | (changes or {})
        )
    return pd.DataFrame(rows, index=[AT + pd.Timedelta(milliseconds=x) for x in offsets])


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"flags": dbn.F_LAST | dbn.F_MAYBE_BAD_BOOK}, "flagged_or_incomplete"),
        ({"flags": 0}, "flagged_or_incomplete"),
        ({"action": "T"}, "non_book_update"),
        ({"bid_px_00": 11}, "invalid_prices"),
        ({"ask_px_00": float("nan")}, "invalid_prices"),
        ({"ask_sz_00": 0}, "empty_side"),
        ({"ts_event": AT + pd.Timedelta(milliseconds=1)}, "timestamp_order"),
        ({"ts_event": AT - pd.Timedelta(seconds=2)}, "stale"),
    ],
)
def test_reject_unsafe(changes, reason):
    assert STATE(frame(changes), AT)[0] == reason


def test_no_fallback_and_no_lookahead():
    old = frame(offsets=(-100,))
    bad = frame({"flags": 0})
    future = frame(offsets=(100,))
    assert STATE(pd.concat([old, bad, future]), AT)[0] == "flagged_or_incomplete"
    assert STATE(future, AT)[0] == "missing"


def test_ordering_and_valid():
    assert STATE(frame(), AT)[0] == "valid"
    with pytest.raises(ValueError, match="unordered"):
        STATE(frame(offsets=(0, -100)), AT)
