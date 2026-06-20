"""CrossAssetBook — top-level capital allocation across independent sleeve P&L streams.

The unified cross-asset book the way multi-strategy funds actually run it. Each sleeve
(crypto funding-carry on H1, equity momentum on D1, ...) is an INDEPENDENT strategy that
produces its own net-of-cost equity curve on its own calendar. This module is the layer
ABOVE the per-sleeve backtests: it does NOT re-optimize positions across mixed-frequency
instruments (that conflates incompatible calendars and trading hours and is not how books
are run) — it allocates CAPITAL/RISK across the sleeves' return streams and applies a
single book-level risk budget. The diversification benefit (combined Sharpe approaching
``sqrt(sum of sleeve Sharpe^2)`` when sleeves are decorrelated — the Fundamental Law of
Active Management realized across asset classes) emerges here.

Calendar: each sleeve is resampled to one return per UTC day (last equity of the day), then
combined on the UNION of calendar days inside the common live window. A sleeve with no bar
on a day (equity on a weekend; the market is closed and the book's positions are flat) earns
0 that day while another sleeve (crypto, 24/7) still earns — exactly the real book's P&L.
Annualization therefore uses 365 (the book trades every calendar day via the 24/7 sleeve);
padding a session sleeve with weekend zeros and annualizing by 365 is ~equivalent to its
own 252-session Sharpe (the zeros scale mean and variance together), so standalone numbers
reconcile.

PIT discipline (the honesty non-negotiable). Every weight and every vol-target leverage
applied to a forward day's return is a pure function of returns strictly BEFORE that day.
Weights rebalance on a fixed cadence from a trailing volatility window; the book-level
vol-target scales forward returns by trailing realized vol, capped at ``max_leverage``.
There is NO full-sample look in the deployable path. A ``scheme="static"`` full-sample
equal-risk mode exists only as a labelled diagnostic (it reproduces the naive offline
combine and quantifies how much of it was hindsight) — never deploy off it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Final, Literal

import numpy as np

__all__ = [
    "DAY_MS",
    "BookResult",
    "SleeveCurve",
    "Weighting",
    "combine_book",
]

DAY_MS: Final[int] = 86_400_000
_EPS: Final[float] = 1e-12

Weighting = Literal["equal_risk", "inverse_var", "equal_weight", "fixed", "static"]
"""Sleeve capital-allocation scheme.

- ``equal_risk`` (default, deployable): weight ∝ 1/sigma over a trailing window, normalized so
  each sleeve contributes equal risk — PIT (rebalanced from past vol only).
- ``inverse_var``: weight ∝ 1/sigma² (trailing) — tilts harder to the calmer sleeve; PIT.
- ``equal_weight``: fixed 1/N capital weights.
- ``fixed``: caller-supplied capital weights (``fixed_weights``).
- ``static``: DIAGNOSTIC ONLY — full-sample equal-risk (1/sigma over the WHOLE window). Uses
  hindsight; reproduces the naive offline combine. Never deploy off this.
"""


@dataclass(frozen=True)
class SleeveCurve:
    """One sleeve's net-of-cost equity curve: ascending ``ts_ms`` (epoch ms UTC) + equity."""

    name: str
    ts_ms: Sequence[int]
    equity: Sequence[float]


@dataclass(frozen=True)
class BookResult:
    """The combined cross-asset book over the common live window (all metrics net of cost).

    Time series are aligned to ``days`` (epoch-day indices, contiguous over the window).
    ``weights``/``leverage`` are the PIT values actually applied to each day's return — the
    audit trail proving no look-ahead.
    """

    names: tuple[str, ...]
    days: np.ndarray  # epoch-day index per row (ts_ms // DAY_MS), contiguous
    sleeve_returns: dict[str, np.ndarray]  # daily returns per sleeve (0 where flat)
    weights: dict[str, np.ndarray]  # applied capital weight per sleeve per day
    leverage: np.ndarray  # applied book leverage per day (vol-target; 1.0 if off)
    sleeve_gross_exposure: dict[str, np.ndarray]  # realized gross per sleeve (lev*w*sleeve_gross)
    book_returns: np.ndarray  # final book daily returns (post weights + leverage)
    equity_curve: np.ndarray  # cumprod(1 + book_returns), starts at 1.0

    sharpe: float
    cagr: float
    vol: float
    maxdd: float
    corr: dict[tuple[str, str], float]  # pairwise corr on common ACTIVE days
    diversification_ratio: float  # (Σ w̄_i sigma_i) / sigma_book ; 1.0 = no diversification

    n_days: int
    window: tuple[int, int]  # (first_day, last_day) epoch-day
    scheme: str
    pit: bool
    vol_target_ann: float | None
    sharpe_theory_uncorr: float  # sqrt(Σ standalone-Sharpe^2): the decorrelated ceiling


def _daily_returns(curve: SleeveCurve) -> tuple[np.ndarray, np.ndarray]:
    """Resample an equity curve to one simple return per UTC day.

    Last equity of each day is the day's mark; the return on day ``d`` is
    ``eq[d]/eq[prev]-1`` where ``prev`` is the previous PRESENT day (gaps are bridged by
    carrying the last mark — a flat day, not a fabricated bar). Returns ``(days, rets)``
    aligned so ``rets[i]`` is the return realized ON ``days[i]`` (the first present day is
    dropped — it has no prior mark).
    """
    by_day: dict[int, float] = {}
    for t, e in zip(curve.ts_ms, curve.equity, strict=True):
        by_day[int(t) // DAY_MS] = float(e)  # ascending ts ⇒ last write wins per day
    sorted_days = sorted(by_day)
    if len(sorted_days) < 2:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)
    eq = np.array([by_day[d] for d in sorted_days], dtype=float)
    rets = eq[1:] / eq[:-1] - 1.0
    return np.array(sorted_days[1:], dtype=np.int64), rets


def _annualized_vol(rets: np.ndarray, trading_days: int) -> float:
    if rets.size < 2:
        return 0.0
    return float(np.std(rets, ddof=1) * math.sqrt(trading_days))


def _equal_risk_weights(vols: np.ndarray) -> np.ndarray:
    """Weights ∝ 1/sigma, normalized to sum 1. Zero-vol sleeves fall back to equal weight."""
    inv = np.where(vols > _EPS, 1.0 / np.maximum(vols, _EPS), 0.0)
    total = float(inv.sum())
    if total <= _EPS:
        return np.full(vols.shape, 1.0 / vols.size)
    return np.asarray(inv / total, dtype=float)


def _inverse_var_weights(vols: np.ndarray) -> np.ndarray:
    inv = np.where(vols > _EPS, 1.0 / np.maximum(vols, _EPS) ** 2, 0.0)
    total = float(inv.sum())
    if total <= _EPS:
        return np.full(vols.shape, 1.0 / vols.size)
    return np.asarray(inv / total, dtype=float)


def combine_book(
    sleeves: Sequence[SleeveCurve],
    *,
    scheme: Weighting = "equal_risk",
    fixed_weights: Mapping[str, float] | None = None,
    vol_lookback_days: int = 90,
    rebalance_days: int = 21,
    vol_target_ann: float | None = None,
    max_leverage: float = 3.0,
    sleeve_gross: Mapping[str, float] | None = None,
    venue_gross_cap: Mapping[str, float] | None = None,
    trading_days: int = 365,
) -> BookResult:
    """Combine independent sleeve equity curves into one PIT cross-asset book.

    ``scheme`` selects capital allocation (see :data:`Weighting`). ``vol_lookback_days`` is
    the trailing window for vol/risk estimates; ``rebalance_days`` the weight/leverage update
    cadence. ``vol_target_ann`` (e.g. 0.20) scales the book to a target annual vol via
    trailing realized vol, capped at ``max_leverage`` — ``None`` leaves the book unscaled
    (leverage 1.0). All estimates use only data strictly before the day they act on.

    ``sleeve_gross`` is each sleeve's INTERNAL gross exposure per unit of allocated capital
    (default 1.0). A dollar-neutral L/S sleeve deploys 2.0 (1 long + 1 short per $1 of NAV);
    its own returns/vol already reflect that, but the FEASIBILITY of book leverage does not —
    so ``venue_gross_cap`` (max deployable gross at each sleeve's venue, e.g. equity Reg-T
    2.0) additionally caps the vol-target leverage so no sleeve's realized gross
    (``leverage * weight * sleeve_gross``) exceeds its venue cap. Without this, a book-level
    vol-target silently demands equity gross that breaches Reg-T (the audit finding). Both
    default to no constraint — byte-identical to the unconstrained book.

    The book runs over the COMMON live window = [max(sleeve start), min(sleeve end)] so every
    sleeve is live throughout — the honest apples-to-apples diversification measurement.
    Raises ``ValueError`` if fewer than one sleeve has data or the window is empty.
    """
    daily = {s.name: _daily_returns(s) for s in sleeves}
    daily = {n: dr for n, dr in daily.items() if dr[0].size > 0}
    if not daily:
        raise ValueError("no sleeve has at least two daily marks")
    names = tuple(sorted(daily))

    # Common live window: every sleeve present from window_start..window_end.
    window_start = max(int(dr[0][0]) for dr in daily.values())
    window_end = min(int(dr[0][-1]) for dr in daily.values())
    if window_end <= window_start:
        raise ValueError(
            f"empty common window: starts {window_start}, ends {window_end} "
            "(sleeves do not overlap)"
        )
    days = np.arange(window_start, window_end + 1, dtype=np.int64)
    n = days.size

    # Align each sleeve onto the contiguous calendar-day axis; 0 where the sleeve is flat.
    # `active` marks days where the sleeve has a genuine (non-padded) return.
    aligned: dict[str, np.ndarray] = {}
    active: dict[str, np.ndarray] = {}
    for name in names:
        sd, sr = daily[name]
        ret_by_day = dict(zip(sd.tolist(), sr.tolist(), strict=True))
        aligned[name] = np.array([ret_by_day.get(int(d), 0.0) for d in days], dtype=float)
        active[name] = np.array([int(d) in ret_by_day for d in days], dtype=bool)

    ret_matrix = np.column_stack([aligned[name] for name in names])  # (n, k)
    k = len(names)

    # ---- weights (PIT unless scheme == "static") ----
    weights_ts = np.full((n, k), 1.0 / k, dtype=float)
    pit = scheme != "static"
    if scheme == "fixed":
        if fixed_weights is None:
            raise ValueError("scheme='fixed' requires fixed_weights")
        w = np.array([float(fixed_weights.get(name, 0.0)) for name in names], dtype=float)
        if w.sum() <= _EPS:
            raise ValueError("fixed_weights sum to zero over the sleeves present")
        weights_ts[:] = w / w.sum()
    elif scheme == "equal_weight":
        weights_ts[:] = 1.0 / k
    elif scheme == "static":
        vols = np.array([_annualized_vol(ret_matrix[:, j], trading_days) for j in range(k)])
        weights_ts[:] = _equal_risk_weights(vols)
    else:  # equal_risk / inverse_var — PIT, rebalanced on cadence from trailing vol
        wfn = _inverse_var_weights if scheme == "inverse_var" else _equal_risk_weights
        cur = np.full(k, 1.0 / k)
        for i in range(n):
            if i >= vol_lookback_days and (i - vol_lookback_days) % rebalance_days == 0:
                win = ret_matrix[i - vol_lookback_days : i, :]  # strictly before day i
                vols = np.array([_annualized_vol(win[:, j], trading_days) for j in range(k)])
                cur = wfn(vols)
            weights_ts[i, :] = cur

    weighted = np.einsum("ij,ij->i", ret_matrix, weights_ts)  # book return pre-leverage

    # per-sleeve internal gross + venue caps (the feasibility constraint on book leverage)
    sgross = np.array([float((sleeve_gross or {}).get(name, 1.0)) for name in names], dtype=float)
    vcap = np.array(
        [float((venue_gross_cap or {}).get(name, math.inf)) for name in names], dtype=float
    )

    # ---- book-level vol target (PIT), feasibility-capped per sleeve ----
    leverage = np.ones(n, dtype=float)
    if vol_target_ann is not None:
        cur_lev = 1.0
        for i in range(n):
            if i >= vol_lookback_days and (i - vol_lookback_days) % rebalance_days == 0:
                realized = _annualized_vol(weighted[i - vol_lookback_days : i], trading_days)
                cur_lev = min(max_leverage, vol_target_ann / max(realized, _EPS))
                # bind to the most-constrained sleeve: leverage * w_j * sgross_j <= vcap_j
                denom = weights_ts[i, :] * sgross
                feasible = np.where(denom > _EPS, vcap / np.maximum(denom, _EPS), math.inf)
                cur_lev = float(min(cur_lev, feasible.min()))
            leverage[i] = cur_lev

    book_returns = weighted * leverage
    equity_curve = np.cumprod(1.0 + book_returns)

    # realized per-sleeve gross exposure (transparency: the audit's "equity gross 2.75x" series)
    sleeve_gross_exposure = {
        name: leverage * weights_ts[:, j] * sgross[j] for j, name in enumerate(names)
    }

    # ---- metrics ----
    sharpe = (
        float(np.mean(book_returns) / np.std(book_returns, ddof=1) * math.sqrt(trading_days))
        if np.std(book_returns, ddof=1) > _EPS
        else 0.0
    )
    final = float(equity_curve[-1])
    cagr = final ** (trading_days / n) - 1.0 if final > 0 else -1.0
    vol = _annualized_vol(book_returns, trading_days)
    running_max = np.maximum.accumulate(equity_curve)
    maxdd = float(np.min(equity_curve / running_max - 1.0))

    # pairwise correlation on days where BOTH sleeves are genuinely active (no padded zeros)
    corr: dict[tuple[str, str], float] = {}
    for a, b in combinations(names, 2):
        mask = active[a] & active[b]
        if mask.sum() >= 2:
            ca = aligned[a][mask]
            cb = aligned[b][mask]
            if np.std(ca) > _EPS and np.std(cb) > _EPS:
                corr[a, b] = float(np.corrcoef(ca, cb)[0, 1])
            else:
                corr[a, b] = 0.0
        else:
            corr[a, b] = float("nan")

    # diversification ratio with average applied weights and full-window sleeve vols
    avg_w = weights_ts.mean(axis=0)
    sleeve_vols = np.array([_annualized_vol(ret_matrix[:, j], trading_days) for j in range(k)])
    weighted_avg_vol = float(np.dot(avg_w, sleeve_vols))
    book_pre_lev_vol = _annualized_vol(weighted, trading_days)
    div_ratio = weighted_avg_vol / book_pre_lev_vol if book_pre_lev_vol > _EPS else 1.0

    # theoretical decorrelated ceiling: sqrt(Σ standalone Sharpe^2)
    standalone_sharpes = []
    for j in range(k):
        sd_ret = ret_matrix[active[names[j]], j]
        sigma_j = float(np.std(sd_ret, ddof=1)) if sd_ret.size >= 2 else 0.0
        standalone_sharpes.append(
            float(np.mean(sd_ret) / sigma_j * math.sqrt(trading_days)) if sigma_j > _EPS else 0.0
        )
    sharpe_theory = math.sqrt(sum(s * s for s in standalone_sharpes))

    return BookResult(
        names=names,
        days=days,
        sleeve_returns=aligned,
        weights={name: weights_ts[:, j] for j, name in enumerate(names)},
        leverage=leverage,
        sleeve_gross_exposure=sleeve_gross_exposure,
        book_returns=book_returns,
        equity_curve=equity_curve,
        sharpe=sharpe,
        cagr=cagr,
        vol=vol,
        maxdd=maxdd,
        corr=corr,
        diversification_ratio=div_ratio,
        n_days=n,
        window=(window_start, window_end),
        scheme=scheme,
        pit=pit,
        vol_target_ann=vol_target_ann,
        sharpe_theory_uncorr=sharpe_theory,
    )
