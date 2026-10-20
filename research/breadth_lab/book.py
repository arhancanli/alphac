"""The combined book of many sleeves, as one account would trade it: every sleeve's stock positions are
summed first, so opposite trades in the same stock cancel before any cost is paid; the market hedge is
one position; the book is scaled to TARGET_VOL with its own trailing volatility.

A selection is a list of (signal, industry, sign). Each sleeve enters at 1/N of its risk-scaled
position, so every sleeve carries the same risk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.breadth_lab.lab import BORROW, TARGET_VOL, Ctx, stats
from research.breadth_lab.panel import CACHE

HEDGE_COST = 0.00005  # one-way, a liquid index future or ETF
MAX_BOOK_LEVERAGE = 20.0


def _read(mode: str, signal: str, tag: str) -> pd.DataFrame:
    f = pd.read_parquet(CACHE / mode / f"{signal}.{tag}.parquet")
    if tag != "weights":
        f.columns = [col.split("|", 1)[1] for col in f.columns]
    return f.astype("float64")


def positions(c: Ctx, mode: str, selection: list[tuple[str, str, int]], timing: dict[str, pd.DataFrame] | None = None) -> tuple[pd.DataFrame, pd.Series]:
    """Stock positions and the market hedge per unit of book capital, before the book's own scaling.

    ``timing`` (round 2) maps a signal to a month-end frame of multipliers per industry (decided at that close);
    a sleeve's size is multiplied by it from the second close after, like its leverage. None: round 1's book."""
    n = len(selection)
    pos = np.zeros(c.r.shape)
    hedge = np.zeros(len(c.r))
    by_signal: dict[str, dict[str, int]] = {}
    for sig, ind, sign in selection:
        by_signal.setdefault(sig, {})[ind] = sign
    industry = c.bucket.reindex(c.r.columns)
    for sig, picks in by_signal.items():
        wr = _read(mode, sig, "weights")
        w = wr.reindex(c.r.index).ffill().fillna(0.0).shift(2).fillna(0.0)
        # Leverage and hedge ratio change only when the sleeve rebalances, so holding them costs no trades.
        on = pd.Series(np.nan, index=c.r.index)
        on.loc[wr.index] = 1.0
        hold = lambda f: f.where(on.notna(), axis=0).ffill().shift(2).fillna(0.0)  # noqa: E731
        lev = hold(_read(mode, sig, "lev").reindex(c.r.index))
        beta = hold(_read(mode, sig, "beta").reindex(c.r.index))
        mult = None
        if timing is not None and sig in timing:
            mult = timing[sig].reindex(c.r.index).ffill().shift(2).fillna(0.0)
        for ind, sign in picks.items():
            if ind not in lev.columns:
                continue
            # An industry-rotation sleeve (round 2) spans every industry under the pseudo-industry "ALL".
            cols = np.arange(len(industry)) if ind == "ALL" else np.flatnonzero((industry == ind).to_numpy())
            k = lev[ind].to_numpy() * (mult[ind].to_numpy() if mult is not None and ind in mult.columns else 1.0)
            scale = (k * sign / n)[:, None]
            pos[:, cols] += w.iloc[:, cols].to_numpy() * scale
            hedge -= beta[ind].to_numpy() * k * sign / n
    return pd.DataFrame(pos, index=c.r.index, columns=c.r.columns), pd.Series(hedge, index=c.r.index)


def banded(target: np.ndarray, band: float) -> np.ndarray:
    """Positions that follow the target but skip any change smaller than ``band`` times the day's mean
    absolute target position; a name leaving the target is always closed."""
    if band <= 0:
        return target
    held = np.zeros_like(target)
    cur = np.zeros(target.shape[1])
    for t in range(target.shape[0]):
        tgt = target[t]
        size = np.abs(tgt[tgt != 0]).mean() if np.any(tgt != 0) else 0.0
        move = (np.abs(tgt - cur) > band * size) | (tgt == 0)
        cur = np.where(move, tgt, cur)
        held[t] = cur
    return held


def account(c: Ctx, pos: pd.DataFrame, hedge: pd.Series, scale: pd.Series | None = None, band: float = 0.0) -> tuple[pd.Series, pd.Series, dict]:
    """Daily return net of netted trading costs and borrow, before-cost return, and exposure figures."""
    if scale is not None:
        pos, hedge = pos.mul(scale, axis=0), hedge * scale
    p = banded(np.nan_to_num(pos.to_numpy()), band)
    h = np.nan_to_num(hedge.to_numpy())
    gross = (p * c.r0.to_numpy()).sum(axis=1) + h * c.market.to_numpy()
    trades = np.abs(np.diff(p, axis=0, prepend=0.0))
    cost = (trades * c.cost.to_numpy()).sum(axis=1) + np.abs(np.diff(h, prepend=0.0)) * HEDGE_COST
    borrow = np.clip(-p, 0.0, None).sum(axis=1) * BORROW / 252.0
    net = pd.Series(gross - cost - borrow, index=c.r.index)
    live = np.abs(p).sum(axis=1) > 0
    expo = {"mean_gross_exposure": round(float(np.abs(p).sum(axis=1)[live].mean()), 2),
            "turnover_per_year": round(float(trades.sum(axis=1)[live].mean() * 252), 1),
            "cost_per_year": round(float(cost[live].mean() * 252), 4),
            "names_held": int(np.median((np.abs(p) > 1e-9).sum(axis=1)[live]))}
    return net.where(live), pd.Series(gross, index=c.r.index).where(live), expo


def book(c: Ctx, mode: str, selection: list[tuple[str, str, int]], band: float = 0.0, timing: dict[str, pd.DataFrame] | None = None) -> dict:
    pos, hedge = positions(c, mode, selection, timing)
    net0, _, _ = account(c, pos, hedge)
    vol = net0.rolling(126, min_periods=63).std() * np.sqrt(252)
    # The book's own scale moves at month ends only, for the same reason.
    target = (TARGET_VOL / vol).clip(upper=MAX_BOOK_LEVERAGE)
    scale = target.where(target.index.isin(c.month_ends)).ffill().shift(2)
    net, gross, expo = account(c, pos, hedge, scale, band)
    net, gross = net.where(scale.notna()), gross.where(scale.notna())
    return {"sleeves": len(selection), "net": stats(net), "before_costs": stats(gross), **expo, "_net": net, "_gross": gross}
