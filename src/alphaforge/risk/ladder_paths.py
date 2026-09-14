"""Vectorized research twin of :class:`alphaforge.risk.monitors.DrawdownLadder` over many paths.

WHY A TWIN. The live ladder is a scalar state machine updated one bar at a time; a drawdown study
needs it applied to 10,000 simulated paths of 730 days, and a Python loop over 7.3 million updates
is too slow to run inside the hourly publish. This module transcribes the same transitions over
NumPy arrays. It is only trustworthy because :mod:`tests.unit.test_ladder_paths` drives the scalar
class and this function over the same random paths, bar by bar, and asserts identical states,
multipliers and high-water marks; any divergence between the two is a test failure, never a
silent difference in the published number.

Semantics (one call to ``update`` == one daily close, see the class docstring):

- the multiplier in force at the previous close scales the next day's return
  (``equity_t = equity_{t-1} * (1 + m_{t-1} * r_t)``), as sizing acts on the next bar live;
- NORMAL -> HALF_GROSS at ``dd >= dd_half_frac``; any live state -> FLAT_HALTED at
  ``dd >= dd_flat_frac``; HALF_GROSS -> NORMAL below ``release_frac * dd_half_frac``;
- FLAT_HALTED is absorbing when ``flat_cooldown_bars`` is ``None`` (a book-level bound: rearming is
  an owner review), otherwise it auto-rearms after that many updates with the high-water mark reset
  to current equity, exactly as the live class does.

Maximum drawdowns are reported from the **all-time** peak of the realized (ladder-applied) equity,
which is what a reader means by "maximum drawdown"; the ladder's internal high-water mark resets
on rearm and would understate it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

NORMAL = 0
HALF_GROSS = 1
FLAT_HALTED = 2

MULTIPLIER_BY_STATE: FloatArray = np.array([1.0, 0.5, 0.0], dtype=np.float64)


@dataclass(frozen=True)
class LadderPaths:
    """Per-path outcome of running the ladder over a ``(paths, days)`` return matrix."""

    realized_returns: FloatArray
    """Book returns after the multiplier, ``(paths, days)``."""
    multipliers: FloatArray
    """Multiplier applied to each day's return, ``(paths, days)``."""
    states: IntArray
    """Ladder state after each day's close, ``(paths, days)``."""
    max_drawdowns: FloatArray
    """Maximum drawdown from the all-time peak of realized equity, per path."""
    halted: BoolArray
    """Whether the path ever entered FLAT_HALTED."""
    first_halt_day: IntArray
    """Zero-based day of the first halt, or -1."""
    days_reduced: IntArray
    """Days on which the applied multiplier was below 1."""
    auto_rearms: IntArray
    """Time-based rearms per path (always 0 when absorbing)."""


def simulate_book_ladder(
    returns: FloatArray,
    *,
    dd_half_frac: float,
    dd_flat_frac: float,
    flat_cooldown_bars: int | None,
    release_frac: float = 0.75,
) -> LadderPaths:
    """Run the ladder over every row of ``returns`` (simple daily returns, ``(paths, days)``)."""
    if returns.ndim != 2 or returns.shape[1] < 1:
        raise ValueError("returns must be a (paths, days) matrix with at least one day")
    if not np.all(np.isfinite(returns)) or np.any(returns <= -1.0):
        raise ValueError("returns contain invalid simple returns")
    if not 0.0 < dd_half_frac < dd_flat_frac < 1.0:
        raise ValueError(
            f"require 0 < dd_half_frac ({dd_half_frac}) < dd_flat_frac ({dd_flat_frac}) < 1"
        )
    if flat_cooldown_bars is not None and flat_cooldown_bars <= 0:
        raise ValueError("flat_cooldown_bars must be > 0 or None (absorbing)")
    paths, days = returns.shape
    release = release_frac * dd_half_frac

    equity = np.ones(paths, dtype=np.float64)
    # The live class initialises its high-water mark on the FIRST update, i.e. after the first
    # bar's return; a loss on the first bar would then never count as drawdown. A book-level
    # bound is measured from starting capital, so the twin marks the initial equity of 1.0 first
    # (the live loop marks equity at boot before it trades, which is the same thing). The
    # equality test calls ``update(1.0)`` on the class before its loop for the same reason.
    hwm = np.ones(paths, dtype=np.float64)
    state = np.zeros(paths, dtype=np.int64)
    halt_bars = np.zeros(paths, dtype=np.int64)
    rearms = np.zeros(paths, dtype=np.int64)
    first_halt = np.full(paths, -1, dtype=np.int64)

    realized = np.empty((paths, days), dtype=np.float64)
    multipliers = np.empty((paths, days), dtype=np.float64)
    states = np.empty((paths, days), dtype=np.int64)

    for day in range(days):
        multiplier = MULTIPLIER_BY_STATE[state]
        realized_day = multiplier * returns[:, day]
        equity = equity * (1.0 + realized_day)
        realized[:, day] = realized_day
        multipliers[:, day] = multiplier

        halted = state == FLAT_HALTED
        if flat_cooldown_bars is not None and np.any(halted):
            halt_bars[halted] += 1
            rearm = halted & (halt_bars >= flat_cooldown_bars)
            hwm[rearm] = equity[rearm]
            state[rearm] = NORMAL
            halt_bars[rearm] = 0
            rearms[rearm] += 1
        # A halted path returns before evaluating its drawdown, rearmed or not (class semantics).
        live = ~halted
        hwm[live] = np.where(np.isnan(hwm[live]), equity[live], np.maximum(hwm[live], equity[live]))
        dd = np.zeros(paths, dtype=np.float64)
        dd[live] = 1.0 - equity[live] / hwm[live]

        to_flat = live & (dd >= dd_flat_frac)
        to_half = live & ~to_flat & (state == NORMAL) & (dd >= dd_half_frac)
        to_normal = live & ~to_flat & (state == HALF_GROSS) & (dd < release)
        newly_halted = to_flat & (first_halt < 0)
        first_halt[newly_halted] = day
        state[to_flat] = FLAT_HALTED
        halt_bars[to_flat] = 0
        state[to_half] = HALF_GROSS
        state[to_normal] = NORMAL
        states[:, day] = state

    wealth = np.cumprod(1.0 + realized, axis=1)
    # Peak INCLUDES the current close (standard definition: a new high is a zero drawdown, never
    # a negative one), starting from the initial wealth of 1.
    peaks = np.maximum.accumulate(np.concatenate([np.ones((paths, 1)), wealth], axis=1), axis=1)[
        :, 1:
    ]
    max_drawdowns = np.max(1.0 - wealth / peaks, axis=1)
    return LadderPaths(
        realized_returns=realized,
        multipliers=multipliers,
        states=states,
        max_drawdowns=np.asarray(max_drawdowns, dtype=np.float64),
        halted=first_halt >= 0,
        first_halt_day=first_halt,
        days_reduced=np.asarray(np.sum(multipliers < 1.0, axis=1), dtype=np.int64),
        auto_rearms=rearms,
    )
