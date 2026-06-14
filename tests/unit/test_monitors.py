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
        with pytest.raises(ValueError, match="flat_cooldown_bars"):
            DrawdownLadder(flat_cooldown_bars=0)
        with pytest.raises(ValueError, match="flat_cooldown_bars"):
            DrawdownLadder(flat_cooldown_bars=-5)
        ladder = DrawdownLadder()
        for bad in (0.0, -1.0, math.nan, math.inf):
            with pytest.raises(ValueError, match="equity"):
                ladder.update(bad)

    # --------------------------------------------------- FLAT_HALTED cooldown

    def test_absorbing_during_cooldown(self) -> None:
        # FLAT_HALTED stays absorbing for < cooldown bars even on full equity
        # recovery: gross 0, HWM frozen, no transition, no flapping.
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15, flat_cooldown_bars=5)
        ladder.update(100_000.0)
        assert ladder.update(80_000.0) is DDState.FLAT_HALTED  # dd = 20%
        assert ladder.hwm == 100_000.0
        assert ladder.bars_in_halt == 0
        # Drive recoveries for 4 < 5 cooldown bars; halt absorbs all of them.
        for i, equity in enumerate((120_000.0, 130_000.0, 90_000.0, 200_000.0), start=1):
            assert ladder.update(equity) is DDState.FLAT_HALTED
            assert ladder.gross_multiplier() == 0.0
            assert ladder.hwm == 100_000.0  # HWM frozen despite new highs
            assert ladder.bars_in_halt == i
        assert ladder.n_auto_rearms == 0

    def test_auto_rearm_after_exact_cooldown(self) -> None:
        # On the update where bars-in-halt REACHES flat_cooldown_bars: NORMAL,
        # gross 1.0, HWM == current equity, drawdown 0, n_auto_rearms += 1.
        cooldown = 5
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15, flat_cooldown_bars=cooldown)
        ladder.update(100_000.0)
        ladder.update(80_000.0)  # FLAT_HALTED, dd = 20%
        # The first (cooldown - 1) updates remain halted.
        for _ in range(cooldown - 1):
            assert ladder.update(82_000.0) is DDState.FLAT_HALTED
        assert ladder.bars_in_halt == cooldown - 1
        assert ladder.n_auto_rearms == 0
        # The cooldown-th update auto-rearms at the CURRENT equity.
        assert ladder.update(83_000.0) is DDState.NORMAL
        assert ladder.gross_multiplier() == 1.0
        assert ladder.hwm == 83_000.0  # fresh HWM = current equity, NOT 100k
        assert ladder.drawdown == pytest.approx(0.0, abs=1e-12)
        assert ladder.bars_in_halt == 0
        assert ladder.n_auto_rearms == 1
        # Resumed: a new high tracks HWM, a fresh 15% can halt again.
        assert ladder.update(90_000.0) is DDState.NORMAL
        assert ladder.hwm == 90_000.0

    def test_ratchet_sustained_decline_does_not_die(self) -> None:
        # A long sustained decline must AUTO-REARM repeatedly (never permanent
        # death) and gross must stay within [0, 1] throughout.
        cooldown = 4
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15, flat_cooldown_bars=cooldown)
        equity = 100_000.0
        ladder.update(equity)
        normal_bars_seen = 0
        # ~50% total decline at 1% per bar over 700 bars; flat book means the
        # decline only "registers" right after each rearm resets the HWM.
        for _ in range(700):
            equity *= 0.99
            assert equity > 0.0
            ladder.update(equity)
            mult = ladder.gross_multiplier()
            assert 0.0 <= mult <= 1.0
            if ladder.state is DDState.NORMAL:
                normal_bars_seen += 1
        # It did NOT die permanently: many auto-rearms over the decline, and
        # it spent live (NORMAL/HALF) bars between halts.
        assert ladder.n_auto_rearms >= 5
        assert normal_bars_seen > 0
        # Manual rearm path is still available regardless of cooldown progress.
        if ladder.state is DDState.FLAT_HALTED:
            ladder.rearm()
            assert ladder.state is DDState.NORMAL

    def test_half_gross_hysteresis_unaffected_by_cooldown(self) -> None:
        # HALF_GROSS still auto-recovers via the dd < 0.75*dd_half hysteresis;
        # the cooldown only governs FLAT_HALTED.
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15, flat_cooldown_bars=5)
        ladder.update(100_000.0)
        assert ladder.update(89_990.0) is DDState.HALF_GROSS  # dd = 10.01%
        assert ladder.gross_multiplier() == 0.5
        assert ladder.bars_in_halt == 0
        assert ladder.update(92_600.0) is DDState.NORMAL  # dd = 7.4% < 7.5%
        assert ladder.gross_multiplier() == 1.0
        assert ladder.n_auto_rearms == 0

    def test_manual_rearm_is_immediate_within_cooldown(self) -> None:
        # rearm() exits FLAT_HALTED immediately, before the cooldown elapses,
        # resetting HWM to current equity; it does NOT count as an auto-rearm.
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15, flat_cooldown_bars=100)
        ladder.update(100_000.0)
        ladder.update(80_000.0)  # FLAT_HALTED
        ladder.update(85_000.0)  # still halted, bars_in_halt = 1
        assert ladder.state is DDState.FLAT_HALTED
        assert ladder.bars_in_halt == 1
        ladder.rearm()
        assert ladder.state is DDState.NORMAL
        assert ladder.hwm == 85_000.0
        assert ladder.bars_in_halt == 0
        assert ladder.n_auto_rearms == 0  # manual rearm is not an auto-rearm

    def test_full_ladder_walk_with_cooldown_rearm(self) -> None:
        # NORMAL -> HALF -> FLAT -> cooldown -> NORMAL, HWM asserted at every
        # step (auto-rearm flavor of the full walk).
        cooldown = 3
        ladder = DrawdownLadder(dd_half_frac=0.10, dd_flat_frac=0.15, flat_cooldown_bars=cooldown)

        assert ladder.update(100_000.0) is DDState.NORMAL
        assert ladder.hwm == 100_000.0
        assert ladder.update(105_000.0) is DDState.NORMAL
        assert ladder.hwm == 105_000.0

        # -10.001% -> HALF_GROSS, HWM held.
        assert ladder.update(105_000.0 * (1.0 - 0.10001)) is DDState.HALF_GROSS
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 0.5

        # -15.0001% -> FLAT_HALTED, HWM frozen, cooldown clock starts.
        flat_equity = 105_000.0 * (1.0 - 0.150001)
        assert ladder.update(flat_equity) is DDState.FLAT_HALTED
        assert ladder.hwm == 105_000.0
        assert ladder.gross_multiplier() == 0.0
        assert ladder.bars_in_halt == 0

        # Cooldown: first (cooldown - 1) updates absorbed, HWM frozen.
        for _ in range(cooldown - 1):
            assert ladder.update(108_000.0) is DDState.FLAT_HALTED
            assert ladder.hwm == 105_000.0
            assert ladder.gross_multiplier() == 0.0

        # cooldown-th update auto-rearms; HWM resets to current equity.
        assert ladder.update(110_000.0) is DDState.NORMAL
        assert ladder.hwm == 110_000.0
        assert ladder.gross_multiplier() == 1.0
        assert ladder.drawdown == pytest.approx(0.0, abs=1e-12)
        assert ladder.n_auto_rearms == 1
        # Trading resumed: new highs track HWM again.
        assert ladder.update(115_000.0) is DDState.NORMAL
        assert ladder.hwm == 115_000.0


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
