"""The regime gate has NO same-day leak (``12_FINAL.md`` test 3 / D2 / CRITIQUE
leakage #4 / #13).

The HMM gross multiplier ``G`` applied on day ``D`` is the FILTERED posterior computed
from observations available strictly BEFORE day ``D`` — through day ``D-1``'s close,
using NO observation from day ``D`` itself (``regime.hmm`` §4). Phase 12 then broadcasts
that daily, already-lagged ``G`` onto the hourly ``(ts_open, instrument_id)`` ``mu_ann``
panel with ONE backward :func:`pandas.merge_asof` keyed on the day-``D`` ``ts_open``
(:func:`~alphaforge.signals.gating.apply_regime_gate` / D2) — never on ``available_at``,
never a second shift. This module pins all four load-bearing D2 invariants on a TINY
synthetic fixture (one real :class:`~alphaforge.regime.hmm.RegimeHMM` fit on a deliberate
vol-regime-flip daily series of just over :data:`~alphaforge.regime.hmm.MIN_FIT_DAYS`
rows — a few seconds — plus pure broadcast assertions, no engine/lake):

1. **Same-day no-leak (the headline):** poison the day-``d`` (and EVERY later) daily BTC
   observation to NaN, recompute the lagged daily ``G`` and the hourly broadcast, and
   assert every hourly ``mu_ann`` row of day ``d`` is BIT-IDENTICAL to the clean run.
   The gate for day ``d`` used only data through day ``d-1`` close, so corrupting day
   ``d``'s own (and the future's) observation cannot move it — the forward filter at row
   ``d-1`` is a function of rows ``0..d-1`` ONLY, and the lag maps ``filt_{d-1}`` onto the
   value APPLIED at day ``d`` (CRITIQUE leakage #13, the leak-regression invariant).
2. **00:00 boundary:** the first hour of day ``D`` (``ts == day-``D`` open) receives the
   gate keyed at day ``D``'s own ``ts_open`` (= the producer's already-lagged
   ``filt_{D-1}`` value), via the single backward merge_asof with
   ``allow_exact_matches=True`` — the exact-match at the day boundary, NOT the prior day's.
3. **Cold start:** hourly rows before the first available gate day get ``G = 1.0`` (never
   NaN) — a missing regime read must not zero the book.
4. **Monotone shrink (μ-contract rule 5):** ``0 < G ≤ 1`` everywhere, so
   ``|mu_ann_gated| ≤ |mu_ann|`` row-for-row; the optimizer's ``|mu_ann| < 3.0`` tripwire
   can only get safer.

Offline, deterministic (seeded), no network, no lake.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.core.time import Timeframe
from alphaforge.regime.hmm import (
    MIN_FIT_DAYS,
    RegimeHMM,
    build_observations,
)
from alphaforge.signals.gating import REGIME_GATE_COLUMN, apply_regime_gate

HOUR: int = Timeframe.H1.ms  # 3_600_000
DAY: int = Timeframe.D1.ms  # 86_400_000
T0: int = 1_672_531_200_000  # 2023-01-01T00:00:00Z (both 1h- and 1d-aligned)

# Just over MIN_FIT_DAYS so a single real HMM fit is cheap (a few seconds) yet exercises
# the genuine forward filter (not the IdentityRegime cold-start fallback). The series has
# a deliberate ~120-day vol cycle so the gate's daily G genuinely MOVES day-to-day (a flat
# G would make the no-leak / monotone assertions vacuous).
_N_DAYS: int = MIN_FIT_DAYS + 60  # 790 daily BTC rows
_INSTRUMENTS: tuple[str, ...] = ("BINANCE:PERP:BTCUSDT", "BINANCE:PERP:ETHUSDT")


def _daily_btc(n_days: int = _N_DAYS, *, seed: int = 7) -> pd.DataFrame:
    """A synthetic daily BTC OHLC frame with a clear vol-regime cycle (D3 fit input).

    Indexed by int64 1d-aligned ``ts_open`` from ``T0``; the ~120-day sinusoidal vol
    band drives two well-separated HMM states so the gross multiplier ``G`` is a
    genuinely time-varying series (not a constant the leak test could pass trivially).
    """
    rng = np.random.default_rng(seed)
    ts = np.array([T0 + k * DAY for k in range(n_days)], dtype=np.int64)
    t = np.arange(n_days)
    vol = 0.01 + 0.010 * (1.0 + np.sin(2.0 * np.pi * t / 120.0))  # 1%..3% daily vol cycle
    rets = rng.normal(0.0, 1.0, n_days) * vol
    close = 20_000.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": close * (1.0 - 0.5 * vol),
            "high": close * (1.0 + vol),
            "low": close * (1.0 - vol),
            "close": close,
        },
        index=pd.Index(ts, dtype="int64", name="ts_open"),
    )


def _hourly_mu(obs_ts: np.ndarray, *, seed: int = 11) -> pd.Series:
    """A dense hourly ``mu_ann`` panel on ``(ts_open, instrument_id)`` spanning ``obs``.

    Every UTC day covered by the daily observation index gets all 24 hourly bars for
    every instrument, with non-zero, mixed-sign ``mu_ann`` (so the monotone-shrink and
    bit-identity assertions are non-vacuous). Plus a leading cold-start day BEFORE the
    first gate day to exercise the ``G = 1.0`` fill.
    """
    rng = np.random.default_rng(seed)
    # One cold-start day before the first observed day, then every observed day's 24 hours.
    day_opens = [int(obs_ts[0]) - DAY, *(int(d) for d in obs_ts)]
    hour_ts: list[int] = []
    iids: list[str] = []
    for day in day_opens:
        for h in range(24):
            for iid in _INSTRUMENTS:
                hour_ts.append(day + h * HOUR)
                iids.append(iid)
    index = pd.MultiIndex.from_arrays(
        [np.array(hour_ts, dtype=np.int64), np.array(iids, dtype=object)],
        names=["ts_open", "instrument_id"],
    )
    # Mixed-sign, non-zero mu_ann well inside the |mu_ann| < 3.0 tripwire.
    values = rng.uniform(-0.4, 0.4, size=len(hour_ts))
    values[values == 0.0] = 0.1
    return pd.Series(values, index=index, name="mu_ann", dtype="float64")


@pytest.fixture(scope="module")
def fitted_gate() -> tuple[RegimeHMM, pd.DataFrame]:
    """ONE real 3-state HMM fit on the synthetic daily series (shared across tests)."""
    obs = build_observations(_daily_btc())
    assert len(obs) >= MIN_FIT_DAYS, "fixture must clear MIN_FIT_DAYS for a real fit"
    hmm = RegimeHMM(n_states=3).fit(obs)
    return hmm, obs


def _day_floor(ts: np.ndarray) -> np.ndarray:
    """UTC-day open (1d floor) of each epoch-ms ``ts`` (T0 is day-aligned)."""
    return (ts // DAY) * DAY


def _poison_from(obs: pd.DataFrame, d: int) -> pd.DataFrame:
    """A copy of ``obs`` with the day-``d`` (and EVERY later) ``m``/``v`` set to NaN.

    The leak probe: corrupting the day-``d`` observation must not move the gate APPLIED
    at day ``d`` (which used data through day ``d-1`` close, via the forward filter +
    the single lag). Never mutates ``obs``.
    """
    poisoned = obs.copy()
    poisoned.loc[poisoned.index[d:], ["m", "v"]] = np.nan
    return poisoned


def _gate_by_day(g: pd.Series) -> dict[int, float]:
    """The day-``D`` ``ts_open`` (int64) -> gate value mapping (mypy-clean items())."""
    keys = g.index.to_numpy(dtype=np.int64)
    vals = g.to_numpy(dtype=float)
    return {int(ts): float(val) for ts, val in zip(keys, vals, strict=True)}


class TestSameDayNoLeak:
    """Poison day-``d`` (and later) BTC obs -> day-``d`` hourly ``mu_ann`` is unchanged."""

    def test_poisoning_day_d_does_not_move_day_d_gate(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        hmm, obs = fitted_gate
        obs_ts = obs.index.to_numpy(dtype=np.int64)
        mu = _hourly_mu(obs_ts)

        # CLEAN run: lagged daily G (value at day D = filtered posterior through D-1),
        # broadcast to the hourly panel via the single backward merge_asof (D2).
        g_clean = hmm.gross_multiplier_series(obs, lag_days=1)
        mu_clean = apply_regime_gate(mu, g_clean)

        # POISON: corrupt the day-d observation and EVERY later day to NaN. The forward
        # filter at row d-1 reads rows 0..d-1 only, and the lag_days=1 shift maps
        # filt_{d-1} onto the value APPLIED at day d -- so day d's applied gate must not
        # move. Pick a day mid-series (clear of the cold-start lag and the warm-up).
        d = len(obs) - 30  # an observed-day row well inside the series
        poisoned = _poison_from(obs, d)

        g_poison = hmm.gross_multiplier_series(poisoned, lag_days=1)
        mu_poison = apply_regime_gate(mu, g_poison)

        day_d_open = int(obs_ts[d])
        hour_ts = mu.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
        day_d_rows = _day_floor(hour_ts) == day_d_open
        assert bool(day_d_rows.any()), "fixture must cover day d's hourly bars"

        # The gate APPLIED to day d originated entirely from data through day d-1 close;
        # corrupting day d (and the future) cannot perturb a single hourly mu_ann of day d.
        np.testing.assert_array_equal(
            mu_clean.to_numpy(dtype=float)[day_d_rows],
            mu_poison.to_numpy(dtype=float)[day_d_rows],
        )

        # Tripwire against a vacuous test: the daily gate the broadcast applies actually
        # varies across the series (a constant G would make the bit-identity trivial).
        g_vals = g_clean.to_numpy(dtype=float)
        assert float(np.nanstd(g_vals)) > 1e-6, "gate G is ~constant; the no-leak test is vacuous"

    def test_poisoning_does_perturb_a_later_day(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        """Control: poisoning day d DOES change a LATER day's gate (so the no-leak result
        above is the timing discipline, not an inert pipeline that ignores its input)."""
        hmm, obs = fitted_gate
        obs_ts = obs.index.to_numpy(dtype=np.int64)
        mu = _hourly_mu(obs_ts)

        g_clean = hmm.gross_multiplier_series(obs, lag_days=1)
        mu_clean = apply_regime_gate(mu, g_clean)

        d = len(obs) - 30
        poisoned = _poison_from(obs, d)
        g_poison = hmm.gross_multiplier_series(poisoned, lag_days=1)
        mu_poison = apply_regime_gate(mu, g_poison)

        # Day d+1's applied gate = filt_d (now poisoned) -> NaN -> fillna(max_g)=1.0,
        # so the broadcast value DIFFERS from the clean run on day d+1's hours.
        later_open = int(obs_ts[d + 1])
        hour_ts = mu.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
        later_rows = _day_floor(hour_ts) == later_open
        assert bool(later_rows.any())
        clean_later = mu_clean.to_numpy(dtype=float)[later_rows]
        poison_later = mu_poison.to_numpy(dtype=float)[later_rows]
        assert not np.allclose(clean_later, poison_later), (
            "poisoning day d should change a LATER day's gate; the pipeline ignored its input"
        )


class TestDayBoundaryBroadcast:
    """The single backward merge_asof keys on the day-D ts_open (D2), exact at 00:00."""

    def test_first_hour_of_day_gets_that_days_gate_via_exact_match(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        hmm, obs = fitted_gate
        obs_ts = obs.index.to_numpy(dtype=np.int64)
        mu = _hourly_mu(obs_ts)
        g = hmm.gross_multiplier_series(obs, lag_days=1)
        mu_gated = apply_regime_gate(mu, g)

        # Recover the broadcast multiplier per hour (gated / ungated; mu is non-zero).
        applied = mu_gated.to_numpy(dtype=float) / mu.to_numpy(dtype=float)
        hour_ts = mu.index.get_level_values("ts_open").to_numpy(dtype=np.int64)

        g_by_day = _gate_by_day(g)
        # Every hour H of day D (including the 00:00 open, the allow_exact_matches=True
        # boundary) gets g[D] -- the day-D-keyed value, which is the producer's already-
        # lagged filt_{D-1}. Check a few interior observed days that have a gate.
        checked = 0
        for d in range(5, len(obs_ts) - 5):
            day_open = int(obs_ts[d])
            if day_open not in g_by_day:
                continue
            expected = g_by_day[day_open]
            day_rows = _day_floor(hour_ts) == day_open
            # The 00:00 (exact-match) hour AND every later hour of the day map to g[D].
            np.testing.assert_allclose(applied[day_rows], expected, rtol=0.0, atol=1e-12)
            # Pin the 00:00 boundary explicitly: the first hour is the exact-match key.
            open_row = (hour_ts == day_open)
            assert bool(open_row.any())
            np.testing.assert_allclose(applied[open_row], expected, rtol=0.0, atol=1e-12)
            checked += 1
            if checked >= 3:
                break
        assert checked >= 3, "did not exercise enough day boundaries"

    def test_value_at_day_d_equals_lagged_filtered_posterior(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        """The day-D gate value equals ``blend(filt_{D-1})`` — the lag lives in the
        producer (``gross_multiplier_series``) ONLY; the broadcast adds no second shift."""
        hmm, obs = fitted_gate
        probs = hmm.filtered_probs(obs)
        raw = hmm.gross_multiplier(probs)  # un-lagged: raw[D] = blend(filt_D)
        g = hmm.gross_multiplier_series(obs, lag_days=1)  # gate[D] = raw[D-1]

        raw_vals = raw.to_numpy(dtype=float)
        g_vals = g.to_numpy(dtype=float)
        # gate[D] == raw[D-1] for every D >= 1 (the single shift); the broadcast keys on
        # this day-D index, so NO extra lag is introduced downstream (D2).
        np.testing.assert_array_equal(g_vals[1:], raw_vals[:-1])


class TestColdStartAndMonotoneShrink:
    """Cold-start G=1.0 (never NaN) and 0 < G <= 1 => |mu_gated| <= |mu| (rule 5)."""

    def test_cold_start_rows_get_unit_gate_never_nan(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        hmm, obs = fitted_gate
        obs_ts = obs.index.to_numpy(dtype=np.int64)
        mu = _hourly_mu(obs_ts)  # carries a leading cold-start day before the first gate day
        g = hmm.gross_multiplier_series(obs, lag_days=1)
        mu_gated = apply_regime_gate(mu, g)

        first_gate_day = int(g.index.min())
        hour_ts = mu.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
        cold = hour_ts < first_gate_day
        assert bool(cold.any()), "fixture must carry hourly rows before the first gate day"

        # No NaN anywhere (a missing regime read must not zero/NaN the book)...
        assert np.isfinite(mu_gated.to_numpy(dtype=float)).all()
        # ...and the cold-start rows are passed through UNCHANGED (G = 1.0).
        np.testing.assert_array_equal(
            mu_gated.to_numpy(dtype=float)[cold], mu.to_numpy(dtype=float)[cold]
        )

    def test_gate_shrinks_magnitude_everywhere(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        hmm, obs = fitted_gate
        obs_ts = obs.index.to_numpy(dtype=np.int64)
        mu = _hourly_mu(obs_ts)
        g = hmm.gross_multiplier_series(obs, lag_days=1)
        mu_gated = apply_regime_gate(mu, g)

        # The producer guarantees G in [0.3, 1.0]; the broadcast fills cold start with 1.0.
        # So 0 < G <= 1 row-for-row, hence |mu_gated| <= |mu| everywhere (rule 5), and the
        # |mu_ann| < 3.0 tripwire can only get safer. A tiny ULP slack on the <= for the
        # float multiply.
        assert float(g.min()) > 0.0
        assert float(g.max()) <= 1.0 + 1e-12
        gated = np.abs(mu_gated.to_numpy(dtype=float))
        base = np.abs(mu.to_numpy(dtype=float))
        assert np.all(gated <= base + 1e-12), "gate must only SHRINK |mu_ann| (rule 5)"
        # Non-vacuous: at least some rows are STRICTLY shrunk (G < 1 on real-fit days).
        assert np.any(gated < base - 1e-9), "no row was shrunk; the gate did nothing"

    def test_broadcast_column_name_and_index_preserved(
        self, fitted_gate: tuple[RegimeHMM, pd.DataFrame]
    ) -> None:
        """The broadcast returns a float Series aligned to ``mu_ann.index`` (D2 contract)
        and uses the canonical ``regime_gate`` column name on the right side."""
        hmm, obs = fitted_gate
        mu = _hourly_mu(obs.index.to_numpy(dtype=np.int64))
        g = hmm.gross_multiplier_series(obs, lag_days=1)
        out = apply_regime_gate(mu, g)
        assert out.name == mu.name == "mu_ann"
        assert out.index.equals(mu.index)
        assert str(out.dtype) == "float64"
        # The gate's own producer stamps the canonical broadcast column name.
        assert g.name == REGIME_GATE_COLUMN
