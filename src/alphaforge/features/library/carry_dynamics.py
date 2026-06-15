"""Funding-dynamics factors (BUILD SLATE Pod B) -- self-relative funding anomaly
``carry_z_252`` and funding-rate momentum ``carry_mom_21_63``.

These are the *dynamics* of the funding series, NOT its level. The level is already
traded by :mod:`alphaforge.features.library.carry` (``carry_fund_21/90``); these two
factors are orthogonal to it by construction:

* ``carry_z_252`` is a SELF-RELATIVE z-score of the most recent settled rate against a
  name's own trailing 252-settlement (84d at 8h) distribution. A permanently-high
  funder contributes z ~ 0 (its level says nothing about how *unusual* the current
  rate is), so this factor shares almost no information with the cross-sectional level.
  Economically: an anomalously high funding rate *vs a name's own history* flags
  crowded one-sided leverage -> impending squeeze / normalization -> FADE it. The
  ``fn`` returns ``-Z`` (reversal sign) so ``direction=+1`` (higher value => higher
  expected forward return). This is the only reversal-sign carry factor in the slate,
  diversifying the carry sleeve's direction.

* ``carry_mom_21_63`` is the SLOPE of the funding series: trailing-21-settlement mean
  minus trailing-63-settlement mean (level vs slope of the same series). A
  permanently-high funder has a high level but zero slope, so this is near-orthogonal
  to ``carry_fund_*`` by construction. Economically: basis trends on medium horizons --
  rising funding (basis widening, leverage demand building) persists for days before
  crowding compresses it; the carry analogue of FX/commodity "trend in the slow state
  variable". A rising basis (positive fast-minus-slow) means longs are paying MORE, so
  carry for a long is getting WORSE; the ``fn`` returns ``-(fast - slow)`` so
  ``direction=+1`` (a *falling* funding trend is the long-friendly signal).

Sign convention (inherited from :mod:`carry`): on Binance USDT-M perps ``f > 0`` means
longs PAY shorts, so the carry earned by a LONG per settlement is ``-f``. Both factors
operate on the RAW rate and apply the negation in their ``fn`` to keep the
"higher value => higher expected forward return for a long" convention.

PIT discipline (leakage findings 6/18, identical to :mod:`carry`): every settlement
enters only once its stored ``available_at <= t + Delta`` (the decision time), via a
single backward :func:`pandas.merge_asof` on ``available_at`` -- NEVER on
``ts_funding``. Per-instrument trailing statistics are computed prefix-independently
with ``numpy sliding_window_view`` (``min_periods = k`` semantics) so the finite-window
parity contract holds bit-for-bit (atol = 0).

No annualizer is applied to either factor: ``carry_z_252`` is scale-free (a z-score
divides out the ``8760/interval`` constant), and ``carry_mom_21_63`` is a difference of
two means of the same series whose relative cross-sectional ranking is unchanged by a
common positive multiplier (the CS pipeline z-scores it downstream regardless).

Lookback honesty (leakage finding 20): ``lookback_bars`` is derived in the spec
factories from :func:`~alphaforge.features.library.carry._carry_lookback_bars` at the
single construction site -- ``(K + 1) * MAX_FUNDING_INTERVAL_HOURS + 1`` 1h bars for
the longest settlement window each factor reads (252 for ``carry_z_252``, 63 for
``carry_mom_21_63``).

Registered: ``carry_z_252`` and ``carry_mom_21_63``. Both ``family=CARRY``,
``direction=+1``, ``cross_sectional=True`` (winsorize/z-score over the PIT universe
before blending). Spot instruments (no funding leg) and instruments with fewer than
the required settlements => NaN (the CS pipeline mean-imputes 0 after z-scoring).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from alphaforge.core.time import Timeframe
from alphaforge.features.library.carry import (
    MAX_FUNDING_INTERVAL_HOURS,
    _carry_lookback_bars,
)
from alphaforge.features.registry import feature
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from collections.abc import Callable

    from alphaforge.features.context import FeatureContext

__all__ = [
    "Z_CLIP",
    "carry_mom_21_63",
    "carry_z_252",
]

Z_CLIP: float = 5.0
"""Belt-and-suspenders clip on the self-relative funding z-score before negation.

A near-constant trailing window already yields NaN (the relative-eps sigma floor in
:func:`_trailing_stat_by_instrument`), so a genuinely huge ``|Z|`` only arises from a
real outlier rate against a real (small-but-finite) spread; clipping to ``[-5, 5]``
caps a pathological single print before the downstream CS winsorizer also handles it.
"""

#: Relative-eps factor for the trailing-std floor. A window whose sample variance is
#: below ``(_VAR_REL_EPS * k * eps) * mean_square`` is treated as constant (NaN sigma),
#: mirroring the catastrophic-cancellation guard in
#: :func:`alphaforge.features.library.mean_reversion.rolling_beta`.
_VAR_REL_EPS: float = 8.0


def _trailing_stat_by_instrument(f: pd.DataFrame, k: int, stat: str) -> pd.Series:
    """Strict trailing-``k`` statistic of ``rate`` per instrument, prefix-independent.

    ``f`` must be sorted by ``(instrument_id, available_at)``. Each output is reduced
    from ONLY its own ``k`` rates (``numpy sliding_window_view``), never a streaming
    accumulator -- a pandas ``rolling(...)`` carries last-ulp state from rows *before*
    the window, breaking the finite-window parity contract (atol = 0) between the
    full-history batch pass and the minimal live window (see the prefix-independence
    note in :mod:`alphaforge.features.library.vol`). NaN until ``k`` rates exist
    (``min_periods = k`` semantics).

    Supported ``stat``:

    * ``"mean"`` -- the trailing arithmetic mean.
    * ``"last"`` -- the rate at the window's right edge (the most recent settled rate;
      a trivial reduction, included so the z-score numerator reuses one code path).
    * ``"z"`` -- the self-relative z-score ``(last - mean) / std`` (ddof=1) of the
      window, NaN where the window is (near-)constant (relative-eps sigma floor) so the
      ratio never amplifies pure rounding residue into a spurious signal.
    """
    rates = f["rate"].to_numpy(dtype="float64")
    out = np.full(len(f), np.nan, dtype="float64")
    for positions in f.groupby("instrument_id", sort=False).indices.values():
        if len(positions) < k:
            continue
        view = np.lib.stride_tricks.sliding_window_view(rates[positions], k)
        edge = positions[k - 1 :]
        if stat == "mean":
            out[edge] = view.mean(axis=-1)
        elif stat == "last":
            out[edge] = view[:, -1]
        elif stat == "z":
            mean = view.mean(axis=-1)
            # ddof=1 sample variance, prefix-independent (computed per window).
            var = view.var(axis=-1, ddof=1)
            mean_sq = (view * view).mean(axis=-1)
            floor = _VAR_REL_EPS * k * float(np.finfo(np.float64).eps) * mean_sq
            last = view[:, -1]
            with np.errstate(invalid="ignore", divide="ignore"):
                z = np.where(var > floor, (last - mean) / np.sqrt(var), np.nan)
            out[edge] = z
        else:  # pragma: no cover - guarded by the caller's spec params
            raise ValueError(f"unknown trailing stat {stat!r}")
    return pd.Series(out, index=f.index, dtype="float64")


def _funding_grid_join(
    ctx: FeatureContext, name: str, per_instrument: Callable[[pd.DataFrame], pd.Series]
) -> pd.Series:
    """Compute a per-instrument funding statistic and as-of join it onto the bar grid.

    ``per_instrument`` is given the funding frame sorted by
    ``(instrument_id, available_at)`` and returns a float64 Series (aligned to that
    frame's index) of the trailing statistic at each settlement's ``available_at``.
    The single backward :func:`pandas.merge_asof` on ``available_at`` then carries, for
    every ``(ts_open, instrument_id)`` grid slot, the value the live trader knew at the
    decision time ``ts_open + Delta`` (leakage findings 6/18). NaN for spot instruments,
    before the required number of settlements, and on instruments with no funding rows.
    Returns the canonical long Series; the spec ``fn`` applies the sign convention.
    """
    tf = Timeframe.H1
    grid = ctx.panel("close").index
    ids = list(ctx.instrument_ids)
    target = pd.MultiIndex.from_product([grid, ids], names=("ts_open", "instrument_id"))

    funding = ctx.funding()
    if funding.empty:
        return pd.Series(np.nan, index=target, dtype="float64", name=name)

    f = funding.sort_values(["instrument_id", "available_at"], kind="stable").reset_index(drop=True)
    f = f.assign(stat=per_instrument(f))

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
        f[["instrument_id", "available_at", "stat"]].sort_values("available_at", kind="stable"),
        left_on="decision_ts",
        right_on="available_at",
        by="instrument_id",
        direction="backward",
        allow_exact_matches=True,
    )
    stat_long = pd.Series(
        merged["stat"].to_numpy(dtype="float64"),
        index=pd.MultiIndex.from_arrays(
            [merged["ts_open"], merged["instrument_id"]],
            names=("ts_open", "instrument_id"),
        ),
        dtype="float64",
    ).reindex(target)
    return stat_long.rename(name)


# -------------------------------------------------------------------- feature fns


def _carry_z_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``carry_z_252``: self-relative funding z-score (fade sign).

    Per instrument over the last ``K = params["n_settlements"]`` settled rates
    (ordered by ``available_at``)::

        Z(i, t) = (last - mean_K) / std_K          # std ddof=1, NaN if near-constant
        CARRY_Z(i, t) = - clip(Z, -5, +5)          # fade an anomalously high funder

    ``fn`` returns ``-clip(Z)`` so ``direction=+1`` (anomalously high funding => fade =>
    expected to underperform a long, hence a low factor value). Pure function of the
    settlements available at the decision close ``t + Delta``; NaN for spot, before the
    ``K``-th publication, and on instruments with no funding rows.
    """
    k = int(spec.params["n_settlements"])
    z = _funding_grid_join(ctx, spec.name, lambda f: _trailing_stat_by_instrument(f, k, "z"))
    clipped = z.clip(lower=-Z_CLIP, upper=Z_CLIP)
    return (-clipped).rename(spec.name)


def _carry_mom_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """Registered body for ``carry_mom_21_63``: funding-rate momentum (slope, fade sign).

    Per instrument, the difference of two trailing means of the RAW rate::

        slope(i, t) = mean_{Kf}(rate) - mean_{Ks}(rate)        # Kf < Ks
        CARRY_MOM(i, t) = - slope(i, t)

    A positive slope (rising funding, basis widening) means a long pays MORE going
    forward, so the long-friendly signal is a *falling* trend: ``fn`` returns
    ``-slope`` so ``direction=+1``. The fast leg needs ``Kf`` settlements and the slow
    leg ``Ks``; the combined value is NaN until the slow leg is warm (and for spot /
    no-funding instruments). Single as-of join on ``available_at``.
    """
    k_fast = int(spec.params["k_fast"])
    k_slow = int(spec.params["k_slow"])

    def slope(f: pd.DataFrame) -> pd.Series:
        fast = _trailing_stat_by_instrument(f, k_fast, "mean")
        slow = _trailing_stat_by_instrument(f, k_slow, "mean")
        return fast - slow

    val = _funding_grid_join(ctx, spec.name, slope)
    return (-val).rename(spec.name)


# ------------------------------------------------------------ registered factories


@feature
def carry_z_252() -> FeatureSpec:
    """Self-relative funding z-score over 252 settlements (84d at 8h); fade sign.

    ``lookback_bars = _carry_lookback_bars(252) = 2025`` -- covers 252 settlements at
    the slowest supported interval (finite window, parity atol = 0).
    """
    n_settlements = 252
    return FeatureSpec(
        name="carry_z_252",
        family=Family.CARRY,
        direction=+1,  # -Z: an anomalously high funder is faded
        cross_sectional=True,
        lookback_bars=_carry_lookback_bars(n_settlements),
        params={
            "n_settlements": n_settlements,
            "max_funding_interval_hours": MAX_FUNDING_INTERVAL_HOURS,
        },
        fn=_carry_z_fn,
    )


@feature
def carry_mom_21_63() -> FeatureSpec:
    """Funding-rate momentum: 21-settlement mean minus 63-settlement mean; fade sign.

    ``lookback_bars = _carry_lookback_bars(63) = 513`` -- bound by the slow (63)
    settlement leg at the slowest supported interval (finite window, parity atol = 0).
    """
    k_fast, k_slow = 21, 63
    return FeatureSpec(
        name="carry_mom_21_63",
        family=Family.CARRY,
        direction=+1,  # -(fast - slow): a falling funding trend is long-friendly
        cross_sectional=True,
        lookback_bars=_carry_lookback_bars(k_slow),
        params={
            "k_fast": k_fast,
            "k_slow": k_slow,
            "max_funding_interval_hours": MAX_FUNDING_INTERVAL_HOURS,
        },
        fn=_carry_mom_fn,
    )
