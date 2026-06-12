"""Funding-carry factors (alphaDesign.md §2.5) — ``carry_fund_21`` / ``carry_fund_90``.

Sign convention (explicit, load-bearing). On Binance USDT-M perps a funding rate
``f > 0`` means **longs PAY shorts** at settlement, so the carry *earned* by a LONG
position per settlement is ``-f``. The factor is defined so that **positive value =
positive expected carry for a long position**::

    CARRY(i, t) = - f̄_{i,t} · (8760 / funding_interval_hours_i)
    f̄_{i,t}    = (1/K) Σ_{j=1..K} f_{i, τ_j}

where the ``τ_j`` are the last ``K`` SETTLED-AND-PUBLISHED rates at the decision time
``t + Δ``: a settlement enters only once its stored ``available_at <= t + Δ``
(backward as-of merge on ``available_at`` — NEVER on ``ts_funding``; leakage findings
6/18: exchanges publish the settled rate with a lag, and joining on settlement time
would let the factor read a number the live trader does not have yet).

Annualization is **interval-aware** (leakage finding 6): the multiplier is
``8760 / funding_interval_hours`` read from the SCD2 instrument record
(:meth:`FeatureContext.instrument`), never a hard-coded ``3 · 365`` — for the
classic 8h interval the two coincide (``8760 / 8 = 1095 = 3 · 365``), but Binance
runs 4h (and occasionally 1h) intervals on volatile names. Funding approximates the
annualized perp-spot basis, so this is the crypto analogue of FX/futures carry:
perp premium => positive funding => negative carry for longs => shorts get paid.

Spot instruments (``funding_interval_hours is None``) get NaN — the CS pipeline
mean-imputes 0 *after* z-scoring (neutral exposure). Fewer than ``K`` published
settlements => NaN (``min_periods = K``).

Lookback honesty (leakage finding 20): ``lookback_bars`` is derived in the spec
factories as ``(K + 1) · MAX_FUNDING_INTERVAL_HOURS + 1`` 1h bars. Derivation: with
interval ``I <= MAX_FUNDING_INTERVAL_HOURS`` hours and publication lag ``< I``, the
last published settlement is younger than ``2·I`` and the oldest of the last ``K``
is younger than ``(K + 1)·I`` relative to the decision time — one extra interval of
slack absorbs grid offset plus publication lag, ``+1`` covers the decision bar
itself. An instrument with a *slower* interval than the declared maximum would be
caught by :func:`alphaforge.features.parity.verify_truncation` (the minimal live
window could not see all ``K`` settlements).

Registered: ``carry_fund_21`` (7d mean at 8h, primary) and ``carry_fund_90``
(30d mean, slow). Both ``direction=+1`` (higher carry => higher expected forward
return), ``cross_sectional=True`` (winsorize/z-score over the PIT universe before
blending).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.core.time import Timeframe
from alphaforge.features.context import long_series
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from alphaforge.features.context import FeatureContext

__all__ = [
    "HOURS_PER_YEAR",
    "MAX_FUNDING_INTERVAL_HOURS",
    "carry_fund_21",
    "carry_fund_90",
]

HOURS_PER_YEAR: Final[int] = 8760
"""24/7 crypto year in hours; annualizer numerator (``8760 / interval_hours``)."""

MAX_FUNDING_INTERVAL_HOURS: Final[int] = 8
"""Slowest supported funding interval (Binance maximum). Sizes ``lookback_bars``;
a slower interval would fail the truncation harness, by design (fail loud)."""


def _carry_lookback_bars(n_settlements: int) -> int:
    """``lookback_bars`` covering the last K settlements at the slowest interval.

    ``(K + 1) · MAX_FUNDING_INTERVAL_HOURS + 1`` 1h bars — see the module docstring
    for the derivation (one interval of slack for grid offset + publication lag,
    plus the decision bar). Derived from params at the single construction site
    (leakage finding 20).
    """
    return (n_settlements + 1) * MAX_FUNDING_INTERVAL_HOURS + 1


def _annualizer(ctx: FeatureContext, instrument_id: str) -> float:
    """Interval-aware annualization multiplier ``8760 / funding_interval_hours``.

    Read from the SCD2 instrument record as-of the decision cutoff (leakage
    finding 6) — never hard-coded. Spot instruments (interval ``None``) get NaN:
    carry is undefined without a funding leg. A missing instrument record raises
    ``KeyError`` (metadata is mandatory; silent NaN would hide a config error).
    """
    interval = ctx.instrument(instrument_id).funding_interval_hours
    if interval is None:
        return float("nan")
    return float(HOURS_PER_YEAR) / float(interval)


def _trailing_mean_by_instrument(f: pd.DataFrame, k: int) -> pd.Series:
    """Strict trailing-``k`` mean of ``rate`` per instrument, prefix-independent.

    ``f`` must be sorted by ``(instrument_id, available_at)``. Each output is
    reduced from ONLY its own ``k`` rates (``numpy sliding_window_view``), never a
    streaming accumulator — a pandas ``rolling(...).mean()`` carries last-ulp state
    from rows *before* the window, which breaks the finite-window parity contract
    (atol = 0) between the full-history batch pass and the minimal live window
    (see the prefix-independence note in :mod:`alphaforge.features.library.vol`).
    NaN until ``k`` rates exist (``min_periods = k`` semantics).
    """
    rates = f["rate"].to_numpy(dtype="float64")
    out = np.full(len(f), np.nan, dtype="float64")
    for positions in f.groupby("instrument_id", sort=False).indices.values():
        if len(positions) >= k:
            view = np.lib.stride_tricks.sliding_window_view(rates[positions], k)
            out[positions[k - 1 :]] = view.mean(axis=-1)
    return pd.Series(out, index=f.index, dtype="float64")


def _funding_carry_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``carry_fund_{K}``.

    Formula (alphaDesign.md §2.5)::

        CARRY(i, t) = - f̄_{i,t} · (8760 / funding_interval_hours_i)
        f̄_{i,t}    = (1/K) Σ_{j=1..K} f_{i, τ_j}

    over the last ``K = params["n_settlements"]`` funding rates of instrument ``i``
    with ``available_at <= t + Δ`` (published by the decision time). Mechanics:

    1. Per instrument, order settlements by the stored ``available_at`` and take the
       rolling mean of the last ``K`` rates (``min_periods = K`` => NaN until ``K``
       settlements have been published).
    2. Backward as-of merge of each grid slot's decision time ``ts_open + Δ``
       against ``available_at`` (leakage findings 6/18) — the joined value is the
       trailing mean *as the live trader knew it* at that instant.
    3. Negate and annualize with the per-instrument interval (module docstring).

    NaN for spot instruments, before the ``K``-th publication, and on instruments
    with no funding rows. Pure function of context data; inputs never mutated.
    """
    k = int(spec.params["n_settlements"])
    tf = Timeframe.H1
    grid = ctx.panel("close").index  # complete expected 1h grid of the window
    ids = list(ctx.instrument_ids)
    target = pd.MultiIndex.from_product([grid, ids], names=("ts_open", "instrument_id"))
    ann = np.array([_annualizer(ctx, iid) for iid in ids], dtype="float64")

    funding = ctx.funding()
    if funding.empty:
        return pd.Series(np.nan, index=target, dtype="float64", name=spec.name)

    f = funding.sort_values(["instrument_id", "available_at"], kind="stable").reset_index(drop=True)
    f = f.assign(fbar=_trailing_mean_by_instrument(f, k))

    grid_arr = np.asarray(grid, dtype="int64")
    left = pd.DataFrame(
        {
            "ts_open": np.repeat(grid_arr, len(ids)),
            "instrument_id": ids * len(grid_arr),
        }
    )
    left["decision_ts"] = left["ts_open"] + tf.ms
    merged = pd.merge_asof(
        left.sort_values("decision_ts", kind="stable"),
        f[["instrument_id", "available_at", "fbar"]].sort_values("available_at", kind="stable"),
        left_on="decision_ts",
        right_on="available_at",
        by="instrument_id",
        direction="backward",
        allow_exact_matches=True,
    )
    fbar_long = pd.Series(
        merged["fbar"].to_numpy(dtype="float64"),
        index=pd.MultiIndex.from_arrays(
            [merged["ts_open"], merged["instrument_id"]],
            names=("ts_open", "instrument_id"),
        ),
        dtype="float64",
    ).reindex(target)

    values = -fbar_long.to_numpy(dtype="float64").reshape(len(grid_arr), len(ids))
    values = values * ann[np.newaxis, :]
    wide = pd.DataFrame(values, index=grid, columns=pd.Index(ids, name="instrument_id"))
    wide.index.name = "ts_open"
    return long_series(wide, name=spec.name)


def _carry_spec(name: str, n_settlements: int) -> FeatureSpec:
    """Construct a carry spec; the ONE place lookback is derived from params."""
    return FeatureSpec(
        name=name,
        family=Family.CARRY,
        direction=+1,
        cross_sectional=True,
        lookback_bars=_carry_lookback_bars(n_settlements),
        params={
            "n_settlements": n_settlements,
            "max_funding_interval_hours": MAX_FUNDING_INTERVAL_HOURS,
        },
        fn=_funding_carry_fn,
    )


@feature
def carry_fund_21() -> FeatureSpec:
    """Primary carry: trailing mean of the last 21 settlements (7d at 8h)."""
    return _carry_spec("carry_fund_21", 21)


@feature
def carry_fund_90() -> FeatureSpec:
    """Slow carry: trailing mean of the last 90 settlements (30d at 8h)."""
    return _carry_spec("carry_fund_90", 90)
