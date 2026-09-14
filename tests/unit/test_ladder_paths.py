"""The vectorized ladder must be the live ladder, bar for bar, on paths that visit every state.

If these two ever disagree the published drawdown-control study is describing a brake the book
does not run. The equality test therefore drives both over the same random paths (with forced
crashes and recoveries so HALF_GROSS, FLAT_HALTED, hysteresis release and auto-rearm all fire)
and compares state, multiplier and high-water mark after every single update.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from alphaforge.risk.ladder_paths import (
    FLAT_HALTED,
    HALF_GROSS,
    MULTIPLIER_BY_STATE,
    NORMAL,
    simulate_book_ladder,
)
from alphaforge.risk.monitors import DDState, DrawdownLadder

STATE_CODE = {
    DDState.NORMAL: NORMAL,
    DDState.HALF_GROSS: HALF_GROSS,
    DDState.FLAT_HALTED: FLAT_HALTED,
}


def _eventful_paths(seed: int, paths: int, days: int) -> np.ndarray:
    """Daily returns with enough dispersion and a few forced crashes to reach every transition."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.012, size=(paths, days))
    for p in range(paths):
        crash_day = int(rng.integers(5, days - 40))
        # Six days of -3.5%: with half gross engaging after the second day the drawdown runs
        # 3.5, 6.9, 8.5, 10.1, 11.7 ... percent, so the path passes through HALF_GROSS into
        # FLAT_HALTED on the fifth day rather than stalling just under the bound.
        returns[p, crash_day : crash_day + 6] = -0.035
        returns[p, crash_day + 20 : crash_day + 30] = 0.02  # a recovery leg after any rearm
    return returns


@pytest.mark.parametrize("cooldown", [None, 14])
def test_vectorized_ladder_equals_the_live_class_after_every_update(cooldown) -> None:
    returns = _eventful_paths(seed=7, paths=25, days=160)
    result = simulate_book_ladder(
        returns, dd_half_frac=0.055, dd_flat_frac=0.11, flat_cooldown_bars=cooldown
    )
    seen = {NORMAL, HALF_GROSS, FLAT_HALTED}
    for p in range(returns.shape[0]):
        ladder = DrawdownLadder(
            dd_half_frac=0.055, dd_flat_frac=0.11, flat_cooldown_bars=cooldown or 10**9
        )
        equity = 1.0
        ladder.update(equity)  # the boot mark: drawdown is measured from starting capital
        assert ladder.state is DDState.NORMAL
        for day in range(returns.shape[1]):
            multiplier = ladder.gross_multiplier()
            assert multiplier == result.multipliers[p, day]
            equity *= 1.0 + multiplier * returns[p, day]
            state = ladder.update(equity)
            assert STATE_CODE[state] == result.states[p, day], (p, day)
            assert math.isclose(equity, float(np.cumprod(1.0 + result.realized_returns[p])[day]))
        if cooldown is not None:
            assert ladder.n_auto_rearms == result.auto_rearms[p]
        seen.discard(int(result.states[p].max()))
    # The paths must actually have exercised every state or the equality proved nothing.
    assert int(np.max(result.states)) == FLAT_HALTED
    assert np.any(result.states == HALF_GROSS)


def test_absorbing_ladder_bounds_the_all_time_drawdown_up_to_one_half_gross_day() -> None:
    returns = _eventful_paths(seed=11, paths=200, days=400)
    result = simulate_book_ladder(
        returns, dd_half_frac=0.055, dd_flat_frac=0.11, flat_cooldown_bars=None
    )
    assert result.halted.all()
    worst_half_gross_day = 0.5 * float(np.max(-returns))
    assert np.all(result.max_drawdowns <= 0.11 + worst_half_gross_day + 1e-12)
    assert np.all(result.max_drawdowns >= 0.11 - 1e-12)  # it halted, so it reached the bound
    # Once halted the multiplier is zero for the rest of the path.
    for p in range(returns.shape[0]):
        assert np.all(result.multipliers[p, result.first_halt_day[p] + 1 :] == 0.0)
    assert np.all(result.auto_rearms == 0)


def test_auto_rearm_ladder_can_exceed_the_bound_across_episodes() -> None:
    """The reason the book-level ladder is absorbing: with a timer rearm the next 11 percent is
    permitted again, so the drawdown from the all-time peak is not bounded."""
    rng = np.random.default_rng(3)
    returns = rng.normal(0.0, 0.01, size=(50, 300))
    returns[:, 10:14] = -0.035
    returns[:, 60:64] = -0.035
    result = simulate_book_ladder(
        returns, dd_half_frac=0.055, dd_flat_frac=0.11, flat_cooldown_bars=14
    )
    assert np.all(result.auto_rearms >= 1)
    assert float(np.max(result.max_drawdowns)) > 0.11 + 0.035


def test_a_path_that_never_draws_down_is_untouched() -> None:
    returns = np.full((3, 50), 0.001)
    result = simulate_book_ladder(
        returns, dd_half_frac=0.055, dd_flat_frac=0.11, flat_cooldown_bars=None
    )
    assert np.all(result.multipliers == 1.0)
    assert np.all(result.realized_returns == returns)
    assert not result.halted.any()
    assert np.all(result.first_halt_day == -1)
    assert np.all(result.max_drawdowns == 0.0)


def test_inputs_are_validated() -> None:
    good = np.zeros((2, 5))
    with pytest.raises(ValueError):
        simulate_book_ladder(good, dd_half_frac=0.2, dd_flat_frac=0.1, flat_cooldown_bars=None)
    with pytest.raises(ValueError):
        simulate_book_ladder(good, dd_half_frac=0.05, dd_flat_frac=0.1, flat_cooldown_bars=0)
    with pytest.raises(ValueError):
        simulate_book_ladder(
            np.array([[-1.5, 0.0]]), dd_half_frac=0.05, dd_flat_frac=0.1, flat_cooldown_bars=None
        )
    assert MULTIPLIER_BY_STATE.tolist() == [1.0, 0.5, 0.0]
