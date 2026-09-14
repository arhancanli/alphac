import copy

import pytest

from alphaforge.validation.trend_history_capture import normalize_history
from alphaforge.validation.trend_observation import ObservationError

SESSIONS = [1788998400000, 1789084800000]
BODY = {
    "bars": {
        "SPY": [
            {"t": "2026-09-10T04:00:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 42},
            {"t": "2026-09-11T04:00:00Z", "o": 101, "h": 102, "l": 99, "c": 100, "v": 43},
        ]
    },
    "next_page_token": None,
}


def test_complete_history():
    rows = normalize_history(BODY, sessions=SESSIONS, symbols=["SPY"])
    assert [r["session_ms"] for r in rows] == SESSIONS
    assert [r["close"] for r in rows] == [101, 100]


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b["bars"]["SPY"].pop(),
        lambda b: b["bars"]["SPY"].append(b["bars"]["SPY"][0]),
        lambda b: b["bars"]["SPY"][0].update(t="2026-09-09T04:00:00Z"),
        lambda b: b.update(next_page_token="more"),
        lambda b: b["bars"]["SPY"][0].update(t="2026-09-10T00:00:00Z"),
    ],
)
def test_incomplete_or_ambiguous_history(change):
    body = copy.deepcopy(BODY)
    change(body)
    with pytest.raises(ObservationError):
        normalize_history(body, sessions=SESSIONS, symbols=["SPY"])


def test_duplicate_expected_sessions():
    with pytest.raises(ObservationError):
        normalize_history(BODY, sessions=SESSIONS + SESSIONS, symbols=["SPY"])
