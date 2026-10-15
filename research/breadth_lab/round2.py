"""Round 2 of the breadth lab (PROTOCOL amendment 3): new stock signals, registered beside round 1's and run
through the same engine (inside every industry, overlapping portfolios, net of costs, hedged and scaled).

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.round2 --signals
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from research.breadth_lab import lab
from research.breadth_lab.lab import Ctx, _beta, _ret, context, stats
from research.breadth_lab.panel import CACHE, Panel

HERE = Path(__file__).resolve().parent
FIRST = ("1998-01-01", "2007-12-31")
SECOND = ("2008-01-01", "2017-12-31")

_f2_cache: dict[int, dict[str, pd.DataFrame]] = {}


def _resid_mom(c: Ctx) -> pd.DataFrame:
    """Residual momentum (Blitz, Huij and Martens): months 12 to 2 of market-residual returns over their volatility."""
    e = c.r0 - _beta(c, 252).shift(1).mul(c.market, axis=0)
    w = e.shift(21).rolling(231, min_periods=180)
    return w.sum() / (w.std() * np.sqrt(231))


def _updays(c: Ctx) -> pd.DataFrame:
    """Share of up days minus share of down days, months 12 to 2 (continuous information, Da, Gurun and Warachka)."""
    s = (c.r > 0).astype("float64") - (c.r < 0).astype("float64")
    return s.where(c.r.notna()).shift(21).rolling(231, min_periods=180).mean()


def _dvol_cv(c: Ctx) -> pd.DataFrame:
    """Variability of liquidity (Chordia, Subrahmanyam and Anshuman): steadier dollar volume earns more."""
    dv = c.p.dollar_volume.astype("float64").where(lambda x: x > 0)
    w = dv.rolling(126, min_periods=80)
    return -(w.std() / w.mean())


def fundamental2(name: str) -> Callable[[Ctx], pd.DataFrame]:
    def fn(c: Ctx) -> pd.DataFrame:
        if id(c) not in _f2_cache:
            from research.breadth_lab.fundamentals2 import signals
            _f2_cache[id(c)] = signals(c.ltri, c.p.close, c.month_ends, c.p.dollar_volume)
        return _f2_cache[id(c)][name]
    return fn


PRICE = {
    "resid_mom": (_resid_mom, "M"),
    "mom_12_7": (lambda c: _ret(c, 252, 147), "M"),
    "updays": (_updays, "M"),
    "dvol_cv": (_dvol_cv, "M"),
    "overnight_21": (lambda c: c.p.overnight.astype("float64").rolling(21, min_periods=15).sum(), "M"),
    "intraday_21": (lambda c: c.p.intraday.astype("float64").rolling(21, min_periods=15).sum(), "M"),
}
FUNDAMENTAL2 = ["noa", "ebitda_ev", "rnd_mv", "fscore", "oper_leverage", "inv_growth", "dsales_dinv", "cash_assets", "payout_yield",
                "xfin", "debt_issuance", "capex_growth", "ato_change", "roic", "turnover"]
NEW = list(PRICE) + FUNDAMENTAL2


def register() -> list[str]:
    """Add the round-2 signals to the engine's registry, as overlapping portfolios (3 monthly rebalances)."""
    for n, spec in PRICE.items():
        lab.SIGNALS[f"{n}_s"] = spec
        lab.SMOOTH[f"{n}_s"] = 3
    for n in FUNDAMENTAL2:
        lab.SIGNALS[f"{n}_s"] = (fundamental2(n), "M")
        lab.SMOOTH[f"{n}_s"] = 3
    return [f"{n}_s" for n in NEW]


def _gross(mode: str, sig: str) -> pd.DataFrame:
    f = pd.read_parquet(CACHE / mode / f"{sig}.gross.parquet").astype("float64")
    f.columns = [col.split("|", 1)[1] for col in f.columns]
    return f


def _sharpe(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std() * np.sqrt(252)) if len(x) > 60 and x.std() > 0 else 0.0


def choose(gross: dict[str, pd.DataFrame], pool: list[str], a: str, z: str, min_pre: float) -> tuple[list[tuple[str, str, int]], dict[str, int]]:
    """Round 1's rule: every signal whose book before costs has |Sharpe| >= min_pre on [a, z], signed by it, in every industry."""
    sel, signs = [], {}
    for s in pool:
        pre = _sharpe(gross[s].loc[a:z].mean(axis=1))
        if abs(pre) < min_pre:
            continue
        signs[s] = 1 if pre > 0 else -1
        sel += [(s, ind, signs[s]) for ind in gross[s].columns]
    return sel, signs


def timing(gross: dict[str, pd.DataFrame], signs: dict[str, int], kind: str, month_ends: pd.DatetimeIndex) -> dict[str, pd.DataFrame] | None:
    """Factor momentum: each signal (or sleeve) sized by its own trailing 12-month return before costs, decided at month ends."""
    if kind == "static":
        return None
    out = {}
    for s, sign in signs.items():
        g = gross[s] * sign
        if kind.startswith("sleeve"):
            tr = g.rolling(252, min_periods=126).sum()
        else:
            t1 = g.mean(axis=1).rolling(252, min_periods=126).sum()
            tr = pd.DataFrame({ind: t1 for ind in g.columns})
        if kind.endswith("onoff"):
            m = (tr > 0).astype(float)
        elif kind.endswith("soft"):
            m = 0.5 + 0.5 * (tr > 0).astype(float)
        elif kind.endswith("flip"):
            m = np.sign(tr).replace(0.0, 1.0)
        else:
            raise ValueError(kind)
        m = m.where(tr.notna(), 1.0)
        out[s] = m.loc[m.index.isin(month_ends)]
    return out


def experiments(variants: list[str] | None = None, band: float = 1.5, tag: str = "") -> None:
    from research.breadth_lab import book as bk
    t0 = time.time()
    c = context(Panel("search"))
    # Books need returns, costs, the market and the calendar only; drop the rest (this machine runs other jobs).
    c.p.overnight = c.p.intraday = c.p.close = c.p.dollar_volume = c.p.total = None
    c.ltri = c.adv = c.eligible = None
    r1_pool = [s for s in lab.SIGNALS if s.endswith("_s") and s[:-2] in lab.BASE]
    new = [f"{n}_s" for n in NEW if (CACHE / "search" / f"{n}_s.gross.parquet").exists()]
    gross = {s: _gross("search", s) for s in r1_pool + new}
    print(f"loaded {len(gross)} signals ({time.time() - t0:.0f}s)", flush=True)
    plans = {
        "r1_static": (r1_pool, 0.3, "static"),
        "r2_static": (r1_pool + new, 0.3, "static"),
        "r2_all_signed_static": (r1_pool + new, 0.0, "static"),
        "r2_fm_signal_onoff": (r1_pool + new, 0.3, "signal_onoff"),
        "r2_fm_signal_soft": (r1_pool + new, 0.3, "signal_soft"),
        "r2_fm_signal_flip": (r1_pool + new, 0.3, "signal_flip"),
        "r2_fm_sleeve_onoff": (r1_pool + new, 0.3, "sleeve_onoff"),
        "r1_fm_signal_onoff": (r1_pool, 0.3, "signal_onoff"),
    }
    results = {}
    for name, (pool, min_pre, kind) in plans.items():
        if variants and name not in variants:
            continue
        t1 = time.time()
        sel, signs = choose(gross, pool, "1998-01-01", "2017-12-31", min_pre)
        b = bk.book(c, "search", sel, band=band, timing=timing(gross, signs, kind, c.month_ends))
        sel1, signs1 = choose(gross, pool, *FIRST, min_pre)
        b1 = bk.book(c, "search", sel1, band=band, timing=timing(gross, signs1, kind, c.month_ends))
        results[name] = {"signals": len(signs), "sleeves": len(sel), "net": b["net"], "before_costs": b["before_costs"].get("sharpe"),
                         "halves_net": [stats(b["_net"].loc[a:z]).get("sharpe") for a, z in (FIRST, SECOND)],
                         "chosen_on_first_half_scored_on_second": stats(b1["_net"].loc[SECOND[0]:SECOND[1]]).get("sharpe"),
                         "gross_exposure": b["mean_gross_exposure"], "turnover": b["turnover_per_year"], "cost_per_year": b["cost_per_year"],
                         "band": band, "timing": kind, "signs": signs, "seconds": round(time.time() - t1)}
        print(name, json.dumps(results[name]), flush=True)
    path = CACHE / "search" / f"round2_books{tag}.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(results)
    path.write_text(json.dumps(merged, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", action="store_true")
    ap.add_argument("--books", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--band", type=float, default=1.5)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    names = register()
    if a.signals:
        lab.run("search", a.only.split(",") if a.only else names)
    if a.books:
        experiments(a.only.split(",") if a.only else None, a.band, a.tag)
