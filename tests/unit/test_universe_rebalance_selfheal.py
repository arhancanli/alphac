"""A monthly rebalance with one attempt and no retry loses a month every time it misses.

WHAT HAPPENED. The universe rebalances on the first bar of each UTC month, and `_is_month_boundary`
is true for exactly ONE bar — 00:00 on the 1st. That was the only trigger. The crypto sleeve was
unreachable across both 2026-07-01 and 2026-08-01, so both rebalances were simply never attempted
and the sleeve traded a 2026-06-01 cross-section for ten weeks. Nobody noticed until it was looked
for; nothing logged, because nothing ran.

The venue outage was the occasion. The DEFECT is a once-a-month trigger with no catch-up.

These tests pin the repair and, just as importantly, its limits — a rebuild that fires when it
should not is worse than one that fires late, so "unknown" and "broken" must both mean "do nothing".
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.live.loop import LiveLoop, _is_month_boundary  # noqa: E402


def _ms(y: int, m: int, d: int, h: int = 0) -> int:
    return int(dt.datetime(y, m, d, h, tzinfo=dt.UTC).timestamp() * 1000)


class _Refresher:
    """Minimal stand-in exposing the optional accessor the loop duck-types."""

    def __init__(self, newest: int | None, *, raises: bool = False) -> None:
        self._newest, self._raises = newest, raises
        self.refreshed: list[int] = []

    def refresh(self, *, cycle_ts: int) -> None:
        self.refreshed.append(cycle_ts)

    def newest_rebalance_ms(self) -> int | None:
        if self._raises:
            raise RuntimeError("membership store unreadable")
        return self._newest


class _NoAccessor:
    """An adapter predating the accessor — must keep the old boundary-only behaviour."""

    def refresh(self, *, cycle_ts: int) -> None: ...


def _loop(refresher: Any) -> Any:
    """A bare LiveLoop instance; _universe_is_stale needs only the refresher attribute."""
    obj = LiveLoop.__new__(LiveLoop)
    obj._universe_refresher = refresher
    return obj


def test_the_missed_month_is_detected() -> None:
    """THE TEST THIS FILE EXISTS FOR — June membership, an August cycle, ten weeks stale."""
    loop = _loop(_Refresher(_ms(2026, 6, 1)))
    assert loop._universe_is_stale(_ms(2026, 8, 11, 7)), (
        "a 2026-06-01 universe on a 2026-08-11 cycle is two rebalances behind and must be repaired "
        "on the next healthy cycle, not left until 2026-09-01"
    )


def test_current_month_is_not_stale() -> None:
    """Same month = the rebalance already happened. Rebuilding every cycle would be the bug."""
    loop = _loop(_Refresher(_ms(2026, 8, 1)))
    assert not loop._universe_is_stale(_ms(2026, 8, 11, 7))
    assert not loop._universe_is_stale(_ms(2026, 8, 31, 23))


def test_month_comparison_not_elapsed_days() -> None:
    """31 days apart but the SAME month must not fire; 1 day apart across a boundary must."""
    loop = _loop(_Refresher(_ms(2026, 8, 1)))
    assert not loop._universe_is_stale(_ms(2026, 8, 31, 23)), "30 days, same month — not due"
    assert loop._universe_is_stale(_ms(2026, 9, 1, 0)), "next month — due"


def test_unknown_is_not_stale() -> None:
    """None means 'cannot tell'. Treating it as stale would rebuild on every single cycle."""
    assert not _loop(_Refresher(None))._universe_is_stale(_ms(2026, 8, 11))


def test_a_broken_reader_never_spins_the_loop() -> None:
    """A diagnostic that throws must not take the trading path with it, nor force a rebuild."""
    assert not _loop(_Refresher(0, raises=True))._universe_is_stale(_ms(2026, 8, 11))


def test_adapter_without_the_accessor_keeps_old_behaviour() -> None:
    """Duck-typed and optional: an older refresher is boundary-only, exactly as before."""
    assert not _loop(_NoAccessor())._universe_is_stale(_ms(2026, 8, 11))


def test_boundary_trigger_still_fires_on_the_first_bar() -> None:
    """The catch-up ADDS a path; it must not replace the declared monthly cadence."""
    assert _is_month_boundary(_ms(2026, 9, 1, 0))
    assert not _is_month_boundary(_ms(2026, 9, 1, 1))
    assert not _is_month_boundary(_ms(2026, 8, 31, 23))
