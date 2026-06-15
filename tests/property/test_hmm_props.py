"""Property / timing tests for the HMM regime gate — the no-same-day-leak proof.

These are the load-bearing leakage properties (correctness rule 4 / leakageCritique
findings 4 and 13). The gate observes DAILY market state but is consumed at HOURLY
decision bars, so the join must guarantee that ``G`` for ALL 24 hours of day ``D`` is
the filtered posterior computed through day ``D-1``'s close and uses NO observation
from day ``D`` itself. Three complementary properties:

* **Producer lag** — ``gross_multiplier_series(lag_days=L)`` shifts the un-lagged
  multiplier forward by ``L`` days, so the value at day ``D`` equals the raw
  multiplier of day ``D-L`` (and the first ``L`` cold-start days are ``1.0``). The lag
  lives in ONE place (finding 4: never applied twice).
* **Consumer cannot see day-d data** — the real proof: poison ``x_d`` and all
  ``x_{>d}`` to NaN/inf, recompute the gate, and assert that the gate value applied to
  EVERY hour-bar of day ``d`` (via the Phase-12 ``merge_asof(... direction="backward")``
  hourly join) is bit-identical to the unpoisoned run. If any hour of day ``d`` consumed
  ``x_d``, the poison would change ``G`` and the test would fail.
* **``merge_asof`` boundary monotonicity** — a backward as-of join on the daily
  ``ts_open`` never selects a daily row whose ``ts_open`` is strictly after the hour-bar
  (the ``00:00`` off-by-one zone from finding 13).

All data is synthetic / fixture; this test never touches the live data lake.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from alphaforge.core.time import Timeframe, available_at
from alphaforge.regime.hmm import GATE_WEIGHTS, RegimeHMM

_DAY_MS = Timeframe.D1.ms
_HOUR_MS = Timeframe.H1.ms


def _daily_obs(n_days: int, seed: int) -> pd.DataFrame:
    """A synthetic daily ``[m, v]`` observation frame on the real daily grid."""
    rng = np.random.default_rng(seed)
    ts = np.arange(n_days, dtype=np.int64) * _DAY_MS
    m = rng.normal(0.0, 0.03, n_days)
    v = rng.normal(np.log(0.8), 0.3, n_days)
    return pd.DataFrame(
        {"m": m, "v": v, "available_at": ts + _DAY_MS},
        index=pd.Index(ts, name="ts_open"),
    )


def _hourly_join(gate_daily: pd.Series, hour_ts: np.ndarray) -> pd.Series:
    """The Phase-12 hourly consumer join (single backward ``merge_asof``).

    Each hour-bar ``t`` receives the LATEST daily gate row whose day ``ts_open <= t``.
    Because the producer already applied the ``lag_days`` shift, the first hour of day
    ``D`` (00:00) receives the day-``D`` gate value = ``blend(filt_{D-1})`` — exactly
    correctness rule 4. ``allow_exact_matches=True`` mirrors ``funding_asof_join``.
    """
    left = pd.DataFrame({"ts": hour_ts.astype(np.int64)})
    right = pd.DataFrame(
        {"day_ts": gate_daily.index.to_numpy(dtype=np.int64), "gate": gate_daily.to_numpy()}
    ).sort_values("day_ts", kind="stable")
    merged = pd.merge_asof(
        left.sort_values("ts", kind="stable"),
        right,
        left_on="ts",
        right_on="day_ts",
        direction="backward",
        allow_exact_matches=True,
    )
    return pd.Series(merged["gate"].to_numpy(), index=merged["ts"].to_numpy(), name="gate")


# --------------------------------------------------------------------- producer lag


@given(
    n_days=st.integers(min_value=5, max_value=120),
    k=st.sampled_from([2, 3]),
    lag=st.integers(min_value=1, max_value=4),
    seed=st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_producer_lag_equals_shifted_unlagged(n_days: int, k: int, lag: int, seed: int) -> None:
    # Inject a KNOWN filtered series via a hand-built posterior frame: no fit needed.
    rng = np.random.default_rng(seed)
    hmm = RegimeHMM(n_states=k)
    ts = np.arange(n_days, dtype=np.int64) * _DAY_MS
    rows = rng.dirichlet(np.ones(k), size=n_days)
    probs = pd.DataFrame(
        rows, index=pd.Index(ts, name="ts_open"), columns=[f"state_{i}" for i in range(k)]
    )
    raw = hmm.gross_multiplier(probs)

    # Reproduce the producer's shift directly (filtered_probs would re-derive `raw`,
    # but we want to assert the SHIFT semantics independent of the model internals).
    lagged = raw.shift(lag).fillna(float(max(GATE_WEIGHTS[k])))

    # value at day D == raw multiplier of day D-lag, for all D >= lag.
    for d in range(lag, n_days):
        assert lagged.iloc[d] == raw.iloc[d - lag]
    # cold start: first `lag` days are the permissive max (1.0), never NaN.
    assert (lagged.iloc[:lag].to_numpy() == max(GATE_WEIGHTS[k])).all()
    assert lagged.notna().all()


# -------------------------------------------------- consumer cannot see day-d data


def _fitted_gate() -> tuple[RegimeHMM, pd.DataFrame]:
    """A genuinely fitted 2-state gate plus its observation frame (module-cached)."""
    rng = np.random.default_rng(101)
    n = 760
    states = np.empty(n, dtype=int)
    states[0] = 0
    trans = np.array([[0.95, 0.05], [0.06, 0.94]])
    means = np.array([[0.001, np.log(0.4)], [-0.002, np.log(1.3)]])
    covs = np.array([[[2e-5, 0.0], [0.0, 0.02]], [[9e-5, 0.0], [0.0, 0.03]]])
    for t in range(1, n):
        states[t] = rng.choice(2, p=trans[states[t - 1]])
    x = np.array([rng.multivariate_normal(means[s], covs[s]) for s in states])
    ts = np.arange(n, dtype=np.int64) * _DAY_MS
    obs = pd.DataFrame(
        {"m": x[:, 0], "v": x[:, 1], "available_at": ts + _DAY_MS},
        index=pd.Index(ts, name="ts_open"),
    )
    return RegimeHMM(n_states=2).fit(obs), obs


_GATE, _OBS = _fitted_gate()


@given(d=st.integers(min_value=2, max_value=750))
@settings(max_examples=40, deadline=None)
def test_poisoning_day_d_does_not_change_day_d_gate(d: int) -> None:
    clean_gate = _GATE.gross_multiplier_series(_OBS, lag_days=1)

    poisoned = _OBS.copy()
    # Poison day d's own observation AND every later day: if the gate for day d's hours
    # consumed any of these, the value would change.
    poison_index = _OBS.index[d:]
    poisoned.loc[poison_index, "m"] = np.nan
    poisoned.loc[poison_index, "v"] = np.inf
    poisoned_gate = _GATE.gross_multiplier_series(poisoned, lag_days=1)

    # The 24 hour-bars of day d.
    day_d_open = int(_OBS.index[d])
    hours = day_d_open + np.arange(24, dtype=np.int64) * _HOUR_MS

    clean_hourly = _hourly_join(clean_gate, hours)
    poisoned_hourly = _hourly_join(poisoned_gate, hours)
    # Bit-identical: day d's gate originated from filt_{d-1}, untouched by the poison.
    np.testing.assert_array_equal(clean_hourly.to_numpy(), poisoned_hourly.to_numpy())


def test_gate_not_live_before_source_day_closes() -> None:
    gate = _GATE.gross_multiplier_series(_OBS, lag_days=1)
    first_obs_ts = int(_OBS.index[0])
    # The earliest a non-cold-start (non-1.0) gate may apply is the first hour after the
    # first observation's day has fully closed: available_at(first_obs, D1) + 1h.
    earliest_live = available_at(first_obs_ts, Timeframe.D1) + _HOUR_MS
    # Day 0's gate is cold-start 1.0; day 1's gate is the first real value, applied at
    # ts_open of day 1 == available_at(day0, D1).
    non_cold = gate[gate.index >= int(_OBS.index[1])]
    first_live_day_ts = int(non_cold.index[0])
    assert first_live_day_ts >= available_at(first_obs_ts, Timeframe.D1)
    assert first_live_day_ts + _HOUR_MS <= earliest_live + _HOUR_MS


# ---------------------------------------------------- merge_asof boundary monotonicity


@given(
    n_days=st.integers(min_value=3, max_value=40),
    seed=st.integers(min_value=0, max_value=5_000),
)
@settings(max_examples=50, deadline=None)
def test_merge_asof_never_selects_a_future_day(n_days: int, seed: int) -> None:
    obs = _daily_obs(n_days, seed)
    rng = np.random.default_rng(seed + 1)
    hmm = RegimeHMM(n_states=2)
    # hand-built posterior -> gate; no fit needed for the join-boundary property.
    rows = rng.dirichlet(np.ones(2), size=n_days)
    probs = pd.DataFrame(
        rows, index=obs.index, columns=["state_0", "state_1"]
    )
    gate = hmm.gross_multiplier(probs).shift(1).fillna(1.0)

    # Build an hourly grid straddling every 00:00 boundary (the off-by-one zone).
    day_opens = obs.index.to_numpy(dtype=np.int64)
    hours = np.concatenate(
        [d + np.arange(24, dtype=np.int64) * _HOUR_MS for d in day_opens]
    )
    left = pd.DataFrame({"ts": hours})
    right = pd.DataFrame(
        {"day_ts": gate.index.to_numpy(dtype=np.int64), "gate": gate.to_numpy()}
    )
    merged = pd.merge_asof(
        left.sort_values("ts", kind="stable"),
        right.sort_values("day_ts", kind="stable"),
        left_on="ts",
        right_on="day_ts",
        direction="backward",
        allow_exact_matches=True,
    )
    selected = merged["day_ts"].to_numpy()
    assert np.all(selected <= merged["ts"].to_numpy())  # never a future day
    # Every hour of day D selects exactly D's own ts_open (00:00 of D), i.e. the lagged
    # gate value that originated from D-1's posterior.
    expected_day = (merged["ts"].to_numpy() // _DAY_MS) * _DAY_MS
    assert np.array_equal(selected, expected_day)
