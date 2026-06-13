"""Unit tests for alphaforge.risk.monitors — historical VaR/CVaR, the
drawdown ladder state machine, and the staleness breaker.

VaR/CVaR assertions are hand-computed next to each fixture (order-statistic
estimator: k = max(1, floor((1-c)*n)); VaR = -r_(k); CVaR = -mean of the k
worst) and checked to 1e-12 absolute. Ladder walks assert state, HWM and
gross multiplier at EVERY step.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from alphaforge.risk import (
    DDState,
    DrawdownLadder,
    StalenessBreaker,
    historical_var_cvar,
)

# ------------------------------------------------------------------- VaR/CVaR

# 10-day fixture, already sorted in the comment for hand-checking:
# sorted: -0.05, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05
TEN_DAYS = [0.01, -0.03, 0.05, -0.01, 0.02, -0.05, 0.0, 0.04, -0.02, 0.03]


class TestHistoricalVarCvar:
    def test_ten_day_fixture_c99(self) -> None:
        # c=0.99 -> p=0.01, n=10 -> k = max(1, floor(0.1)) = 1:
        # VaR = -r_(1) = 0.05; CVaR = -mean({-0.05}) = 0.05.
        rep = historical_var_cvar(TEN_DAYS, confidence=0.99, window_days=365)
        assert rep.n_obs == 10
        assert rep.k_tail == 1
        assert rep.var_frac == pytest.approx(0.05, abs=1e-12)
        assert rep.cvar_frac == pytest.approx(0.05, abs=1e-12)

    def test_ten_day_fixture_c80(self) -> None:
        # c=0.80 -> p=0.2, n=10 -> k = floor(2.0) = 2:
        # VaR = -r_(2) = 0.03; CVaR = -(-0.05 + -0.03)/2 = 0.04.
        rep = historical_var_cvar(TEN_DAYS, confidence=0.80, window_days=365)
        assert rep.k_tail == 2
        assert rep.var_frac == pytest.approx(0.03, abs=1e-12)
        assert rep.cvar_frac == pytest.approx(0.04, abs=1e-12)

    def test_window_cut_drops_old_observations(self) -> None:
        # 35 catastrophic days followed by 365 in-window days; the -0.5 prints
        # must NOT appear in a 365-day window. In-window: 362 zeros plus
        # {-0.01, -0.02, -0.03}; n=365 -> k = floor(3.65) = 3:
        # VaR = -r_(3) = 0.01; CVaR = -(-0.03 - 0.02 - 0.01)/3 = 0.02.
        returns = [-0.5] * 35 + [0.0] * 362 + [-0.01, -0.02, -0.03]
        rep = historical_var_cvar(returns, confidence=0.99, window_days=365)
        assert rep.n_obs == 365
        assert rep.k_tail == 3
        assert rep.var_frac == pytest.approx(0.01, abs=1e-12)
        assert rep.cvar_frac == pytest.approx(0.02, abs=1e-12)

    def test_cvar_never_below_var(self) -> None:
        rng = np.random.default_rng(7)
        returns = rng.normal(0.0, 0.02, size=500)
        rep = historical_var_cvar(returns, confidence=0.95, window_days=365)
        assert rep.cvar_frac >= rep.var_frac

    def test_input_validation(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            historical_var_cvar([])
        with pytest.raises(ValueError, match="non-finite"):
            historical_var_cvar([0.01, math.nan])
        with pytest.raises(ValueError, match="confidence"):
            historical_var_cvar(TEN_DAYS, confidence=1.0)
        with pytest.raises(ValueError, match="window_days"):
            historical_var_cvar(TEN_DAYS, window_days=0)
        with pytest.raises(ValueError, match="1-D"):
            historical_var_cvar(np.zeros((2, 5)))


# ------------------------------------------------------------ drawdown ladder


class TestDrawdownLadder:
    def test_full_walk(self) -> None:
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15)
        assert ladder.state is DDState.NORMAL
        assert math.isnan(ladder.hwm)

        # Rise: NORMAL, HWM tracks equity.
        assert ladder.update(100_000.0) is DDState.NORMAL
        assert ladder.hwm == 100_000.0
        assert ladder.update(105_000.0) is DDState.NORMAL
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 1.0

        # Drawdown -10.001% from HWM -> HALF_GROSS; HWM unchanged.
        assert ladder.update(105_000.0 * (1.0 - 0.10001)) is DDState.HALF_GROSS
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 0.5

        # Recover to -7.4% (< 0.75 * 10% = 7.5%) -> NORMAL; HWM unchanged.
        assert ladder.update(105_000.0 * (1.0 - 0.074)) is DDState.NORMAL
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 1.0

        # Crash -15.0001% -> FLAT_HALTED; HWM frozen.
        assert ladder.update(105_000.0 * (1.0 - 0.150001)) is DDState.FLAT_HALTED
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 0.0

        # Full recovery does NOT exit the halt (absorbing), HWM stays frozen.
        assert ladder.update(120_000.0) is DDState.FLAT_HALTED
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 0.0

        # Only the explicit human re-arm exits; HWM resets to last equity.
        ladder.rearm()
        assert ladder.state is DDState.NORMAL
        assert ladder.hwm == 120_000.0
        assert ladder.gross_multiplier() == 1.0
        assert ladder.update(121_000.0) is DDState.NORMAL
        assert ladder.hwm == 121_000.0

    def test_hysteresis_no_flapping(self) -> None:
        # Oscillating around the -10% trigger must produce ONE transition:
        # release requires dd < 7.5%, so 9.5/10.1/9.5% all stay HALF_GROSS.
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15)
        ladder.update(100_000.0)
        states = [ladder.update(e) for e in (89_990.0, 90_500.0, 89_900.0, 90_500.0, 89_990.0)]
        assert states == [DDState.HALF_GROSS] * 5
        # Single release once past the hysteresis band.
        assert ladder.update(92_600.0) is DDState.NORMAL  # dd = 7.4%

    def test_normal_straight_to_flat_on_crash(self) -> None:
        ladder = DrawdownLadder()
        ladder.update(100_000.0)
        assert ladder.update(80_000.0) is DDState.FLAT_HALTED  # dd = 20%

    def test_drawdown_property(self) -> None:
        ladder = DrawdownLadder()
        assert math.isnan(ladder.drawdown)
        ladder.update(100_000.0)
        ladder.update(95_000.0)
        assert ladder.drawdown == pytest.approx(0.05, abs=1e-12)

    def test_rearm_outside_halt_is_operator_error(self) -> None:
        ladder = DrawdownLadder()
        with pytest.raises(RuntimeError, match="FLAT_HALTED"):
            ladder.rearm()
        ladder.update(100_000.0)
        ladder.update(89_000.0)  # HALF_GROSS
        with pytest.raises(RuntimeError, match="FLAT_HALTED"):
            ladder.rearm()

    def test_invalid_inputs(self) -> None:
        with pytest.raises(ValueError, match="dd_half_frac"):
            DrawdownLadder(dd_half_frac=0.15, dd_flat_frac=0.10)
        ladder = DrawdownLadder()
        for bad in (0.0, -1.0, math.nan, math.inf):
            with pytest.raises(ValueError, match="equity"):
                ladder.update(bad)


# ---------------------------------------------------------- staleness breaker


class TestStalenessBreaker:
    BAR_MS = 3_600_000  # 1h
    CLOSE_TS = 1_700_000_000_000

    def test_fresh_at_exact_limit_allowed(self) -> None:
        breaker = StalenessBreaker(max_bars=2)
        assert breaker.trading_allowed(
            now=self.CLOSE_TS + 2 * self.BAR_MS,
            latest_bar_close=self.CLOSE_TS,
            bar_ms=self.BAR_MS,
        )

    def test_one_ms_over_forbidden(self) -> None:
        breaker = StalenessBreaker(max_bars=2)
        assert not breaker.trading_allowed(
            now=self.CLOSE_TS + 2 * self.BAR_MS + 1,
            latest_bar_close=self.CLOSE_TS,
            bar_ms=self.BAR_MS,
        )

    def test_future_stamped_bar_counts_as_fresh(self) -> None:
        breaker = StalenessBreaker(max_bars=2)
        assert breaker.trading_allowed(
            now=self.CLOSE_TS,
            latest_bar_close=self.CLOSE_TS + self.BAR_MS,
            bar_ms=self.BAR_MS,
        )

    def test_invalid_params(self) -> None:
        with pytest.raises(ValueError, match="max_bars"):
            StalenessBreaker(max_bars=0)
        breaker = StalenessBreaker(max_bars=2)
        with pytest.raises(ValueError, match="bar_ms"):
            breaker.trading_allowed(now=1, latest_bar_close=0, bar_ms=0)
