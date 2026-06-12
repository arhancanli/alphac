"""Market-level shared inputs (buildabilityCritique.md finding 3.9) —
``adv_quote_30d`` and ``sigma_daily``.

These two are THE shared denominators of the system: the execution-cost model
(participation = order notional / ADV), the risk module (position vol budgeting)
and the universe filter all consume the SAME registered features — computing them
twice with slightly different conventions is how a backtest and the live book end up
disagreeing about tradability. Both are ``direction=0`` (utility features, not
alphas) and ``cross_sectional=False`` (consumed raw, in native units: USDT/day and
daily vol fraction).

* ``adv_quote_30d`` — 30-day rolling MEDIAN of *daily* quote volume (USDT/day).
  Daily = 1h ``quote_volume`` summed per complete UTC day; the median (not mean)
  makes the tradability estimate robust to single-day volume spikes (a listing
  pump must not double the cost model's depth estimate for a month). PIT: the value
  at bar ``t`` uses the last 30 UTC days fully completed by the decision time
  ``t + Δ`` — the day ending exactly at ``t + Δ`` (i.e. when ``t`` is the 23:00
  bar) is already included.
* ``sigma_daily`` — EWMA volatility of 1h log returns (halflife 240 bars = 10 days)
  scaled to daily horizon: ``sigma_daily = sigma_1h · sqrt(24)``. EWMA-family spec
  (buildabilityCritique.md §6.1): infinite-memory recursion, parity rtol 1e-9.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.features.context import long_series
from alphaforge.features.library.vol import ewma_vol_halflife, log_returns
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "BARS_PER_DAY",
    "DAY_MS",
    "SIGMA_DAILY_HALFLIFE",
    "adv_quote_30d",
    "sigma_daily",
]

DAY_MS: Final[int] = 86_400_000
"""One UTC day in milliseconds (24/7 market — no DST, no calendar logic)."""

BARS_PER_DAY: Final[int] = 24
"""1h bars per UTC day; the ``sqrt(24)`` daily-horizon scaling of ``sigma_daily``."""

SIGMA_DAILY_HALFLIFE: Final[int] = 240
"""EWMA halflife of ``sigma_daily`` in 1h bars (10 days)."""


def _adv_quote_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``adv_quote_30d``.

    Formula, with ``days = params["days"]`` and quote volume ``QV``::

        DQV(i, d)  = Σ_{bars k in UTC day d} QV_{i,k}        # complete days only
        ADV(i, t)  = median( DQV(i, d - days + 1) ... DQV(i, d) )

    where ``d`` is the last UTC day fully completed by the decision time
    ``t + Δ``:  ``d = floor_day(t + Δ) - 1 day``. Mechanics on the complete
    expected grid (parity-exact across both engine windows):

    1. Sum 1h ``QV`` per UTC day (NaN gap slots are skipped within a day,
       ``min_count=1``; a day with no data at all is NaN).
    2. Drop days not FULLY contained in the context window — a boundary-truncated
       partial day must never masquerade as a full day (this is what keeps the
       minimal live window and the batch pass bit-identical).
    3. Rolling ``days``-day MEDIAN with ``min_periods = days`` — any NaN day in
       the span => NaN (a 30d ADV over fewer than 30 traded days is undefined).
    4. Map each bar to its last completed day's median.

    NaN until ``days`` complete UTC days exist. Median, not mean: a planted
    single-day 100x spike leaves the value unchanged (tested).
    """
    days = int(spec.params["days"])
    qv = ctx.panel("quote_volume")
    grid = np.asarray(qv.index, dtype="int64")
    day_key = (grid // DAY_MS) * DAY_MS
    daily = qv.groupby(day_key).sum(min_count=1)

    first_full_day = -(-ctx.start // DAY_MS) * DAY_MS  # ceil to the next UTC day
    day_index = np.asarray(daily.index, dtype="int64")
    complete = (day_index >= first_full_day) & (day_index + DAY_MS <= ctx.end)
    daily = daily.loc[complete]

    med = daily.rolling(days, min_periods=days).median()

    # Last UTC day fully completed at the decision time t + Δ.
    last_day = ((grid + 3_600_000) // DAY_MS) * DAY_MS - DAY_MS
    wide = med.reindex(last_day)
    wide.index = qv.index
    wide.columns = qv.columns
    return long_series(wide, name=spec.name)


def _sigma_daily_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``sigma_daily``.

    Formula, with ``r_t = ln(C_t / C_{t-1})`` (positional on the complete grid —
    gaps yield NaN, never bridged) and ``h = params["halflife"]``::

        alpha        = 1 - exp(ln(0.5) / h)                       # halflife form
        sigma²_t     = alpha · r_t² + (1 - alpha) · sigma²_{t-1}              # zero-mean recursion
        sigma_daily  = sqrt(sigma²_t) · sqrt(24)                      # daily-horizon scaling

    Delegates the recursion to the ONE sanctioned implementation,
    :func:`alphaforge.features.library.vol.ewma_vol_halflife` (``adjust=False``,
    ``min_periods = int(h)`` — NaN until ``h`` valid returns exist).
    Infinite-memory: the spec opts into the EWMA-family parity convention
    (rtol 1e-9).
    """
    halflife = float(spec.params["halflife"])
    sigma = ewma_vol_halflife(log_returns(ctx.panel("close")), halflife)
    out = sigma * math.sqrt(float(spec.params["bars_per_day"]))
    return long_series(out, name=spec.name)


@feature
def adv_quote_30d() -> FeatureSpec:
    """30d median daily quote volume (USDT/day) — cost/risk/universe shared input.

    Lookback derivation: ``days·24`` bars of complete days plus up to ``23`` bars
    of the in-progress UTC day between the last day boundary and the decision bar
    (worst case: decision at 23:00, i.e. the 22:00 bar) => ``days·24 + 23``.
    """
    days = 30
    return FeatureSpec(
        name="adv_quote_30d",
        family=Family.MARKET,
        direction=0,
        cross_sectional=False,
        lookback_bars=days * BARS_PER_DAY + (BARS_PER_DAY - 1),
        params={"days": days},
        fn=_adv_quote_fn,
    )


@feature
def sigma_daily() -> FeatureSpec:
    """EWMA daily vol (halflife 240 bars x sqrt(24)) — cost/risk/universe shared input.

    EWMA-family lookback derivation (buildabilityCritique.md §6.1): the halflife
    form has ``alpha = 1 - 2^(-1/240)``, equivalent span ``s = 2/alpha - 1 ≈ 692.4``,
    declared as ``ceil = 693``. Lookback = ``12·span`` (above the 10-span minimum:
    tail weight ``(1-alpha)^L = 2^(-L/240) ≈ 4e-11``, giving margin for old-regime
    observations that deviate from the current vol level by O(1) fractions).
    """
    halflife = SIGMA_DAILY_HALFLIFE
    alpha = 1.0 - 0.5 ** (1.0 / halflife)
    span = math.ceil(2.0 / alpha - 1.0)
    return FeatureSpec(
        name="sigma_daily",
        family=Family.MARKET,
        direction=0,
        cross_sectional=False,
        lookback_bars=12 * span,
        params={
            "halflife": halflife,
            "bars_per_day": BARS_PER_DAY,
            "ewma_family": True,
            "span": span,
        },
        fn=_sigma_daily_fn,
    )
