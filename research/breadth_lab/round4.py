"""Round 4 of the breadth lab (PROTOCOL amendment 10): new ideas from local data, registered beside rounds 1-3
and run through the same engine (48-industry sleeves, then the four cell schemes of amendment 4).

Fundamental signals read the as-reported SF1 quarters exactly as round 2 (each row usable from its filing
date, flows trailing four quarters, market value carried from the quarter's end by the stock's own return).

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.round4 --signals
    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.pods --build --only <round-4 signals>
    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.round4 --books
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import numpy as np
import pandas as pd

from research.breadth_lab import fundamentals2, lab
from research.breadth_lab.fundamentals import month_end_frame
from research.breadth_lab.lab import Ctx, _ret

_cache: dict[int, dict[str, pd.DataFrame]] = {}
EXTRA_FLOWS = ["sbcomp", "depamor", "taxexp", "ebt"]


def _streak(s: pd.Series) -> pd.Series:
    """Consecutive quarters of earnings above the same quarter a year before, up to 8."""
    out, run = np.full(len(s), np.nan), 0.0
    for i, v in enumerate(s.to_numpy()):
        run = run + 1.0 if v == 1.0 else 0.0
        out[i] = np.nan if np.isnan(v) else min(run, 8.0)
    return pd.Series(out, index=s.index)


def quarterly() -> pd.DataFrame:
    q = fundamentals2.quarterly()
    g = q.groupby("instrument_id", sort=False)
    for f in EXTRA_FLOWS:
        q[f"{f}_ttm"] = g[f].transform(lambda s: s.rolling(4, min_periods=4).sum())
    q["cfo_q_assets"] = q["ncfo"] / q["assets"].where(q["assets"] > 0)
    q["roa_q"] = q["netinc"] / q["assets"].where(q["assets"] > 0)
    g = q.groupby("instrument_id", sort=False)
    for f in ("equity", "ppnenet", "receivables", "cashneq", "opinc_ttm", "sgna_ttm", "ncfdiv_ttm", "rnd_ttm", "depamor_ttm"):
        q[f"{f}_4q"] = g[f].shift(4)
    q["cfo_vol"] = g["cfo_q_assets"].transform(lambda s: s.rolling(8, min_periods=6).std())
    q["roa_vol"] = g["roa_q"].transform(lambda s: s.rolling(8, min_periods=6).std())
    prev = g["netinc"].shift(4)
    q["ni_up"] = (q["netinc"] > prev).astype("float64").where(prev.notna() & q["netinc"].notna())
    q["ni_streak"] = q.groupby("instrument_id", sort=False)["ni_up"].transform(_streak)
    return q


def signals(ltri: pd.DataFrame, close: pd.DataFrame, month_ends: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    q = quarterly()
    ids = ltri.columns
    m = month_end_frame(q, month_ends, ids)
    dates = ltri.index
    cl = close.astype("float64").ffill(limit=5).to_numpy()
    lt = ltri.ffill(limit=5).to_numpy()
    col = ids.get_indexer(m["instrument_id"])
    pe_row = dates.searchsorted(m["pe_date"].fillna(dates[0]), side="right") - 1
    d_row = dates.searchsorted(m["d"], side="right") - 1
    ok = m["pe_date"].notna().to_numpy() & (pe_row >= 0) & (col >= 0)
    mv_pe = np.where(ok, cl[pe_row.clip(0), col.clip(0)], np.nan) * m["sharesbas"]
    ltri_pe = np.where(ok, lt[pe_row.clip(0), col.clip(0)], np.nan)
    ltri_d = np.where(col >= 0, lt[d_row.clip(0), col.clip(0)], np.nan)
    mv = pd.Series(mv_pe * np.exp(ltri_d - ltri_pe), index=m.index)
    pos = lambda s: s.where(s > 0)  # noqa: E731
    growth = lambda a, b: a / pos(b) - 1.0  # noqa: E731
    assets, liab = m["assets"], m["liabilities"]
    wc = m["assetsc"] - m["liabilitiesc"]
    ni, ni4 = m["netinc_ttm"], m["netinc_ttm_4q"]
    sales = growth(m["revenue_ttm"], m["revenue_ttm_4q"])
    out = {
        "book_lev": liab / pos(assets),
        "mkt_lev": m["debt"] / pos(mv),
        "current_ratio": m["assetsc"] / pos(m["liabilitiesc"]),
        # Altman's Z without the retained-earnings term (SF1 has none).
        "zscore": 1.2 * wc / pos(assets) + 3.3 * m["ebit_ttm"] / pos(assets) + 0.6 * mv / pos(liab) + m["revenue_ttm"] / pos(assets),
        # Ohlson's O, negated so that higher is safer.
        "oscore": -(-0.407 * np.log(pos(assets)) + 6.03 * liab / pos(assets) - 1.43 * wc / pos(assets)
                    + 0.0757 * m["liabilitiesc"] / pos(m["assetsc"]) - 2.37 * ni / pos(assets) - 1.83 * m["ncfo_ttm"] / pos(liab)
                    + 0.285 * ((ni < 0) & (ni4 < 0)) - 1.72 * (liab > assets)
                    - 0.521 * (ni - ni4) / pos(ni.abs() + ni4.abs())),
        "tangibility": (m["cashneq"].fillna(0.0) + 0.715 * m["receivables"].fillna(0.0) + 0.547 * m["inventory"].fillna(0.0)
                        + 0.535 * m["ppnenet"].fillna(0.0)) / pos(assets),
        "intang_assets": m["intangibles"].fillna(0.0) / pos(assets),
        "cfo_debt": m["ncfo_ttm"] / pos(m["debt"]),
        "gross_margin": m["gp_ttm"] / pos(m["revenue_ttm"]),
        "dmargin": m["opinc_ttm"] / pos(m["revenue_ttm"]) - m["opinc_ttm_4q"] / pos(m["revenue_ttm_4q"]),
        "droe": ni / pos(m["equity"]) - ni4 / pos(m["equity_4q"]),
        "droa": ni / pos(assets) - ni4 / pos(m["assets_4q"]),
        "sales_growth": -sales,
        "dsales_dsga": sales - growth(m["sgna_ttm"], m["sgna_ttm_4q"]),
        "dgm_dsales": growth(m["gp_ttm"], m["gp_ttm_4q"]) - sales,
        "dsales_drec": sales - growth(m["receivables"], m["receivables_4q"]),
        "sga_assets": m["sgna_ttm"] / pos(assets),
        "tax_income": m["taxexp_ttm"] / pos(m["ebt_ttm"]),
        "ddep": m["depamor_ttm"] / pos(m["ppnenet"]) - m["depamor_ttm_4q"] / pos(m["ppnenet_4q"]),
        "ppe_growth": -(m["ppnenet"] - m["ppnenet_4q"]) / pos(m["assets_4q"]),
        "capex_dep": -m["capex_ttm"].abs() / pos(m["depamor_ttm"]),
        "asset_turnover": m["revenue_ttm"] / pos(m["assets_4q"]),
        # Sloan's balance-sheet accruals: change in non-cash current assets less change in current liabilities other
        # than current debt, less depreciation, over average assets; negated (low accruals earn more).
        "wc_accruals": -(((m["assetsc"] - m["assetsc_4q"]) - (m["cashneq"] - m["cashneq_4q"]))
                         - ((m["liabilitiesc"] - m["liabilitiesc_4q"]) - ((m["debt"] - m["debtnc"]) - (m["debt_4q"] - m["debtnc_4q"])))
                         - m["depamor_ttm"]) / pos((assets + m["assets_4q"]) / 2.0),
        # Dividends paid are negative in the cash flow statement: an increase makes the trailing sum more negative.
        "ddiv": (m["ncfdiv_ttm_4q"].fillna(0.0) - m["ncfdiv_ttm"].fillna(0.0)) / pos(assets),
        "sbc_assets": -m["sbcomp_ttm"].fillna(0.0) / pos(assets),
        "drnd": (m["rnd_ttm"].fillna(0.0) - m["rnd_ttm_4q"].fillna(0.0)) / pos(assets),
        "ni_streak": m["ni_streak"],
        "cfo_vol": -m["cfo_vol"],
        "roa_vol": -m["roa_vol"],
    }
    frames = {}
    for k, v in out.items():
        s = pd.Series(np.asarray(v, dtype="float64"), index=pd.MultiIndex.from_arrays([m["d"], m["instrument_id"]]))
        s = s.replace([np.inf, -np.inf], np.nan)
        frames[k] = s.unstack().reindex(index=month_ends, columns=ids)
    return frames


def _mean(x: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return x.rolling(252, min_periods=200).mean()


def _coskew(c: Ctx) -> pd.DataFrame:
    """Coskewness with the market over a year (Harvey and Siddique), negated: negative coskewness earns more."""
    m, r = c.market, c.r.astype("float64")
    mu_m, mu_r = _mean(m), _mean(r)
    var_m = _mean(m * m) - mu_m**2
    num = _mean(r.mul(m * m, axis=0)) - 2.0 * _mean(r.mul(m, axis=0)).mul(mu_m, axis=0) + mu_r.mul(mu_m**2 - var_m, axis=0)
    sd_r = np.sqrt((_mean(r * r) - mu_r**2).clip(lower=0.0))
    return -num / sd_r.mul(var_m, axis=0)


def _dbeta(c: Ctx) -> pd.DataFrame:
    """Downside beta (Ang, Chen and Xing): beta on the year's days when the market fell."""
    d = (c.market < 0).astype("float64")
    md = c.market * d
    n = _mean(d)
    erm = _mean(c.r0.mul(md, axis=0)).div(n, axis=0)
    er = _mean(c.r0.mul(d, axis=0)).div(n, axis=0)
    em, em2 = _mean(md) / n, _mean(md * md) / n
    return (erm - er.mul(em, axis=0)).div(em2 - em**2, axis=0)


def _lag_corr(c: Ctx) -> pd.DataFrame:
    """Price delay (Hou and Moskowitz): correlation of the day's return with the previous day's market, over a year."""
    ml, r = c.market.shift(1), c.r0
    cov = _mean(r.mul(ml, axis=0)) - _mean(r).mul(_mean(ml), axis=0)
    sd_m = np.sqrt(_mean(ml * ml) - _mean(ml) ** 2)
    sd_r = np.sqrt((_mean(r * r) - _mean(r) ** 2).clip(lower=1e-12))
    return cov.div(sd_m, axis=0) / sd_r


def _eap(c: Ctx) -> pd.DataFrame:
    """The earnings announcement premium (Frazzini and Lamont): at a month end, 1 for a stock expected to file in the
    coming month, i.e. one that filed two or eleven months before this month."""
    q = fundamentals2.quarterly()
    months = pd.PeriodIndex(c.month_ends.tz_convert(None), freq="M")
    filed = pd.PeriodIndex(q["av_date"].dt.tz_convert(None), freq="M")
    col = c.r.columns.get_indexer(q["instrument_id"])
    out = np.zeros((len(months), len(c.r.columns)))
    for lag in (2, 11):
        row = months.get_indexer(filed + lag)
        ok = (row >= 0) & (col >= 0)
        out[row[ok], col[ok]] = 1.0
    return pd.DataFrame(out, index=c.month_ends, columns=c.r.columns)


def fundamental4(name: str) -> Callable[[Ctx], pd.DataFrame]:
    def fn(c: Ctx) -> pd.DataFrame:
        if id(c) not in _cache:
            _cache[id(c)] = signals(c.ltri, c.p.close, c.month_ends)
        return _cache[id(c)][name]
    return fn


PRICE = {
    "coskew_252": (_coskew, "M"),
    "dbeta_252": (_dbeta, "M"),
    "lag_corr_252": (_lag_corr, "M"),
    "zero_days_252": (lambda c: (c.r == 0).astype("float64").where(c.r.notna()).rolling(252, min_periods=200).mean(), "M"),
    "mom_accel": (lambda c: _ret(c, 126, 21) - _ret(c, 252, 147), "M"),
    "eap": (_eap, "M"),
}
FUNDAMENTAL4 = ["book_lev", "mkt_lev", "current_ratio", "zscore", "oscore", "tangibility", "intang_assets", "cfo_debt",
                "gross_margin", "dmargin", "droe", "droa", "sales_growth", "dsales_dsga", "dgm_dsales", "dsales_drec",
                "sga_assets", "tax_income", "ddep", "ppe_growth", "capex_dep", "asset_turnover", "wc_accruals", "ddiv",
                "sbc_assets", "drnd", "ni_streak", "cfo_vol", "roa_vol"]
NEW = list(PRICE) + FUNDAMENTAL4
HELD_ONE_MONTH = {"eap"}


def register() -> list[str]:
    """Add the round-4 signals to the engine's registry, as overlapping portfolios (3 monthly rebalances; the
    announcement premium held one month)."""
    for n, spec in PRICE.items():
        lab.SIGNALS[f"{n}_s"] = spec
        lab.SMOOTH[f"{n}_s"] = 1 if n in HELD_ONE_MONTH else 3
    for n in FUNDAMENTAL4:
        lab.SIGNALS[f"{n}_s"] = (fundamental4(n), "M")
        lab.SMOOTH[f"{n}_s"] = 3
    return [f"{n}_s" for n in NEW]


def books() -> None:
    """Amendment 10's two books, both chosen on 1998-2007 and run on 2008-2017, with one netted share for both."""
    from research.breadth_lab import pods
    from research.breadth_lab.netting_law import full_share
    own = {n: pods.sign_on(n, *pods.FIRST) for n in pods.signals()}
    share = full_share(pods.FIRST, own)
    print("netted_share_1998_2007", round(share, 4), flush=True)
    pods.netted_d(weighting="ideas", share=share, ablations=False, out="round4_ideas.json", tag="round4_ideas")
    pods.netted_d(weighting="sleeves", share=share, ablations=False, out="round4_d_rules.json", tag="round4_d_rules")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", action="store_true", help="48-industry sleeves of the round-4 signals (the sign each is built with)")
    ap.add_argument("--books", action="store_true", help="the two books of amendment 10")
    a = ap.parse_args()
    if a.signals:
        lab.run("search", register())
    if a.books:
        books()
