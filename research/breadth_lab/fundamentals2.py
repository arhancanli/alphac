"""Round-2 fundamental signals from the full Sharadar SF1 file (PROTOCOL amendment 3), sampled at month ends.

As-reported quarterly rows (dimension ARQ); a row is usable from its SEC filing date (datekey), as in the
lake, and an amended filing for the same quarter is ignored (the first filing is what was known). Flows are
trailing four quarters. Market value is computed as in round 1: the quarter-end close times shares, carried
to the month end by the stock's own total return. Extract the rows first:

    unzip SF1.zip into var/breadth_lab/sf1, then COPY ... WHERE dimension='ARQ' TO arq.parquet (see the ledger)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.breadth_lab.fundamentals import month_end_frame
from research.breadth_lab.panel import CACHE

ARQ = CACHE / "sf1" / "arq.parquet"
FLOWS = ["revenue", "cor", "sgna", "rnd", "opinc", "ebit", "ebitda", "netinc", "ncfo", "ncfdiv", "ncfcommon", "ncfdebt", "capex", "gp"]
NAMES = ["noa", "ebitda_ev", "rnd_mv", "fscore", "oper_leverage", "inv_growth", "dsales_dinv", "cash_assets", "payout_yield",
         "xfin", "debt_issuance", "capex_growth", "ato_change", "roic", "turnover"]


def quarterly() -> pd.DataFrame:
    q = pd.read_parquet(ARQ)
    q["instrument_id"] = "XUSE:CASH:" + q["ticker"] + "USD"
    q["pe_date"] = pd.to_datetime(q["reportperiod"]).dt.tz_localize("UTC").astype("datetime64[ms, UTC]")
    q["av_date"] = pd.to_datetime(q["datekey"]).dt.tz_localize("UTC").astype("datetime64[ms, UTC]")
    q = q.sort_values(["instrument_id", "pe_date", "av_date"]).drop_duplicates(["instrument_id", "pe_date"], keep="first")
    g = q.groupby("instrument_id", sort=False)
    for f in FLOWS:
        q[f"{f}_ttm"] = g[f].transform(lambda s: s.rolling(4, min_periods=4).sum())
    for f in ("assets", "inventory", "debt", "revenue_ttm", "netinc_ttm", "ncfo_ttm", "gp_ttm", "assetsc", "liabilitiesc", "debtnc", "sharesbas"):
        q[f"{f}_4q"] = g[f].shift(4)
    # Mean TTM capex of the three prior years (Titman, Wei and Xie's abnormal investment), at least two of them.
    q["capex_prev3"] = g["capex_ttm"].transform(lambda s: pd.concat([s.shift(4), s.shift(8), s.shift(12)], axis=1).mean(axis=1).where(
        pd.concat([s.shift(4), s.shift(8), s.shift(12)], axis=1).notna().sum(axis=1) >= 2))
    q["noa_raw"] = (q["assets"] - q["cashneq"]) - (q["liabilities"] - q["debt"].fillna(0.0))
    q["noa_4q"] = g["noa_raw"].shift(4)
    return q


def _fscore(m: pd.DataFrame) -> pd.Series:
    roa = m["netinc_ttm"] / m["assets_4q"]
    roa_prev = m["netinc_ttm_4q"] / m["assets_4q"]
    cfo = m["ncfo_ttm"] / m["assets_4q"]
    lev = m["debtnc"] / m["assets"]
    lev_prev = m["debtnc_4q"] / m["assets_4q"]
    cr = m["assetsc"] / m["liabilitiesc"]
    cr_prev = m["assetsc_4q"] / m["liabilitiesc_4q"]
    gm = m["gp_ttm"] / m["revenue_ttm"]
    gm_prev = m["gp_ttm_4q"] / m["revenue_ttm_4q"]
    ato = m["revenue_ttm"] / m["assets_4q"]
    parts = [roa > 0, cfo > 0, roa > roa_prev, cfo > roa, lev < lev_prev, cr > cr_prev,
             m["sharesbas"] <= m["sharesbas_4q"], gm > gm_prev, ato > m["revenue_ttm_4q"] / m["assets_4q"]]
    score = sum(p.astype(float) for p in parts)
    return score.where(m["assets_4q"].notna() & m["revenue_ttm_4q"].notna())


def signals(ltri: pd.DataFrame, close: pd.DataFrame, month_ends: pd.DatetimeIndex, dollar_volume: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
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
    ev = mv + m["debt"].fillna(0.0) - m["cashneq"].fillna(0.0)
    out = {
        "noa": -m["noa_raw"] / pos(m["assets_4q"]),
        "ebitda_ev": m["ebitda_ttm"] / pos(ev),
        "rnd_mv": m["rnd_ttm"].fillna(0.0).where(m["revenue_ttm"].notna()) / pos(mv),
        "fscore": _fscore(m),
        "oper_leverage": (m["cor_ttm"].fillna(0.0) + m["sgna_ttm"].fillna(0.0)) / pos(m["assets"]),
        "inv_growth": -(m["inventory"] / pos(m["inventory_4q"]) - 1.0),
        "dsales_dinv": (m["revenue_ttm"] / pos(m["revenue_ttm_4q"]) - 1.0) - (m["inventory"] / pos(m["inventory_4q"]) - 1.0),
        "cash_assets": m["cashneq"] / pos(m["assets"]),
        "payout_yield": (-m["ncfdiv_ttm"].fillna(0.0) - m["ncfcommon_ttm"].fillna(0.0)) / pos(mv),
        "xfin": -(m["ncfcommon_ttm"].fillna(0.0) + m["ncfdebt_ttm"].fillna(0.0)) / pos(m["assets"]),
        "debt_issuance": -(m["debt"] - m["debt_4q"]) / pos(m["assets_4q"]),
        "capex_growth": -(m["capex_ttm"].abs() / pos(m["capex_prev3"].abs()) - 1.0),
        "ato_change": m["revenue_ttm"] / pos(m["noa_raw"]) - m["revenue_ttm_4q"] / pos(m["noa_4q"]),
        "roic": m["ebit_ttm"] / pos(m["invcap"]),
    }
    if dollar_volume is not None:  # share turnover: 126-day mean dollar volume over market value (low turnover earns more)
        dv = dollar_volume.astype("float64").rolling(126, min_periods=80).mean().to_numpy()
        out["turnover"] = -np.log(pd.Series(np.where(col >= 0, dv[d_row.clip(0), col.clip(0)], np.nan), index=m.index) / pos(mv))
    frames = {}
    for k, v in out.items():
        s = pd.Series(np.asarray(v, dtype="float64"), index=pd.MultiIndex.from_arrays([m["d"], m["instrument_id"]]))
        s = s.replace([np.inf, -np.inf], np.nan)
        frames[k] = s.unstack().reindex(index=month_ends, columns=ids)
    return frames
