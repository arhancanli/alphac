"""The published live curve must be a RECORD, not a reconstruction.

`combined_live` rebuilds ALPHAC's NAV from go-live on every publish. It used to do that at whatever
the sleeve weights were on the day it ran, so changing a weight — or adding a sleeve — would have
silently restated every previously published live day. While the book sat at a frozen 40/40/20 the
defect was invisible; it would have surfaced the moment the six-sleeve deployment landed, and the
first anyone would have known is that a past number had moved.

The load-bearing test here is `test_appending_a_new_weight_entry_cannot_change_history`. If it ever
fails, the published record is being rewritten and the project's central claim goes with it.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from paper_trading_state import (  # noqa: E402
    GO_LIVE,
    WEIGHT_SCHEDULE,
    _weights_on,
    combined_live,
)


def _curve(start_equity: float, daily: list[tuple[str, float]]) -> list[dict]:
    """Build a live curve from (date, simple_return) steps."""
    out, val = [], start_equity
    for i, (d, r) in enumerate(daily):
        val = val if i == 0 else val * (1.0 + r)
        out.append({"date": d, "equity": val})
    return out


# Derived from GO_LIVE, never hardcoded: a re-baseline moves that date (v1 -> v2 -> v3 so far),
# and a test pinned to a literal would fail for the wrong reason every time the record restarts.
_D0 = datetime.strptime(GO_LIVE, "%Y-%m-%d").replace(tzinfo=UTC)
DAYS = [(_D0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
CUTOVER = DAYS[3]


def _sleeves() -> dict[str, list[dict]]:
    return {
        "crypto": _curve(100.0, list(zip(DAYS, [0.0, 0.010, -0.004, 0.006, 0.002], strict=True))),
        "equity": _curve(100.0, list(zip(DAYS, [0.0, -0.002, 0.008, 0.001, -0.003], strict=True))),
        "mf": _curve(100.0, list(zip(DAYS, [0.0, 0.004, 0.001, -0.007, 0.005], strict=True))),
    }


def test_appending_a_new_weight_entry_cannot_change_history() -> None:
    """THE TEST THIS FILE EXISTS FOR.

    Add a sleeve mid-record, as the six-sleeve deployment will. Every day BEFORE the new entry's
    effective date must be byte-identical. Under the old implementation every one of them moved.
    """
    sleeves = _sleeves()
    before = combined_live(sleeves, schedule=[(GO_LIVE, {"crypto": 0.4, "equity": 0.4, "mf": 0.2})])
    after = combined_live(
        sleeves,
        schedule=[
            (GO_LIVE, {"crypto": 0.4, "equity": 0.4, "mf": 0.2}),
            (CUTOVER, {"crypto": 0.25, "equity": 0.25, "mf": 0.15, "ledger": 0.35}),
        ],
    )
    cutover = CUTOVER
    hist_before = [p for p in before if p["date"] < cutover]
    hist_after = [p for p in after if p["date"] < cutover]
    assert hist_before == hist_after, (
        "appending a weight change restated published history — the live curve is a "
        "reconstruction, not a record"
    )
    # ...and the change must actually take effect from its date, or the schedule does nothing.
    tail_before = [p["equity"] for p in before if p["date"] >= cutover]
    tail_after = [p["equity"] for p in after if p["date"] >= cutover]
    assert tail_before != tail_after


def test_weights_on_picks_the_entry_in_force() -> None:
    sched = [
        (DAYS[0], {"a": 1.0}),
        (DAYS[3], {"a": 0.5, "b": 0.5}),
    ]
    assert _weights_on(DAYS[0], sched) == {"a": 1.0}
    assert _weights_on(DAYS[2], sched) == {"a": 1.0}
    assert _weights_on(DAYS[3], sched) == {"a": 0.5, "b": 0.5}
    assert _weights_on("2027-09-01", sched) == {"a": 0.5, "b": 0.5}


def test_weights_are_normalised() -> None:
    got = _weights_on(DAYS[2], [(DAYS[0], {"a": 2.0, "b": 2.0, "c": 1.0})])
    assert got == pytest.approx({"a": 0.4, "b": 0.4, "c": 0.2})


def test_out_of_order_schedule_is_rejected() -> None:
    """An out-of-order entry would silently apply the wrong weights to a past day."""
    with pytest.raises(ValueError, match="ascending date order"):
        combined_live(
            _sleeves(),
            schedule=[(DAYS[3], {"crypto": 1.0}), (GO_LIVE, {"crypto": 1.0})],
        )


def test_a_sleeve_with_no_mark_contributes_nothing_that_day() -> None:
    """Sleeves come online on different days; the flagship must still accrue from go-live."""
    sleeves = _sleeves()
    sleeves["mf"] = _curve(100.0, list(zip(DAYS[3:], [0.0, 0.005], strict=True)))
    out = combined_live(sleeves, schedule=[(GO_LIVE, {"crypto": 0.5, "equity": 0.5, "mf": 0.0})])
    assert out[0] == {"date": GO_LIVE, "equity": 100000.0}
    assert len(out) == len(DAYS)


def test_shipped_schedule_is_ascending_and_starts_at_go_live() -> None:
    dates = [d for d, _ in WEIGHT_SCHEDULE]
    assert dates == sorted(dates), "WEIGHT_SCHEDULE is out of order"
    assert dates[0] == GO_LIVE, "the schedule must cover the first published day"
    for _, w in WEIGHT_SCHEDULE:
        assert abs(sum(w.values()) - 1.0) < 1e-9, f"weights must sum to 1, got {w}"
