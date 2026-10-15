"""Point-in-time fundamental signals for the breadth lab, sampled at month ends.

Each quarterly row of the Sharadar lake becomes usable on its ``available_at``; a month-end signal reads
the latest row available by that date (and none older than 400 days). Flows are trailing four
quarters. Market value at a month end is the value at the quarter's end moved by the stock's own total
return since then, so splits between the two dates cancel.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from research.breadth_lab.panel import LAKE

FLOWS = ["revenues", "gross_profit", "operating_income", "net_income", "op_cash_flow", "free_cash_flow", "net_common_issued", "capex"]


def quarterly() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    q = con.execute(
        f"""SELECT instrument_id, epoch_ms(period_end) AS pe, epoch_ms(available_at) AS av, fiscal_period,
                   {", ".join(FLOWS)}, equity, assets, shares_basic
            FROM read_parquet('{LAKE}/fundamentals/*/*/data.parquet')"""
    ).df()
    q = q.sort_values(["instrument_id", "pe", "av"]).drop_duplicates(["instrument_id", "pe"], keep="last")
    g = q.groupby("instrument_id", sort=False)
    for f in FLOWS:
        q[f"{f}_ttm"] = g[f].transform(lambda s: s.rolling(4, min_periods=4).sum())
    q["assets_4q"] = g["assets"].shift(4)
    q["ni_yoy"] = q["net_income"] - g["net_income"].shift(4)
    q["rev_yoy"] = q["revenues"] - g["revenues"].shift(4)
    q["ni_yoy_sd"] = g["ni_yoy"].transform(lambda s: s.rolling(8, min_periods=6).std())
    q["rev_yoy_sd"] = g["rev_yoy"].transform(lambda s: s.rolling(8, min_periods=6).std())
    q["pe_date"] = pd.to_datetime(q["pe"], unit="ms", utc=True)
    q["av_date"] = pd.to_datetime(q["av"], unit="ms", utc=True)
    return q


def month_end_frame(q: pd.DataFrame, month_ends: pd.DatetimeIndex, ids: pd.Index) -> pd.DataFrame:
    grid = pd.MultiIndex.from_product([month_ends, ids], names=["d", "instrument_id"]).to_frame(index=False)
    grid = grid.sort_values("d")
    rows = q.dropna(subset=["av_date"]).sort_values("av_date")
    m = pd.merge_asof(grid, rows, left_on="d", right_on="av_date", by="instrument_id", direction="backward")
    stale = (m["d"] - m["av_date"]) > pd.Timedelta(days=400)
    m.loc[stale, rows.columns.difference(["instrument_id"])] = np.nan
    return m


def signals(ltri: pd.DataFrame, close: pd.DataFrame, month_ends: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    q = quarterly()
    ids = ltri.columns
    m = month_end_frame(q, month_ends, ids)
    # Market value at the quarter's end from that day's close (as-reported shares); carried to the month end
    # by the total return since, which is free of splits.
    dates = ltri.index
    cl = close.astype("float64").ffill(limit=5).to_numpy()
    lt = ltri.ffill(limit=5).to_numpy()
    col = ids.get_indexer(m["instrument_id"])
    pe_row = dates.searchsorted(m["pe_date"].fillna(dates[0]), side="right") - 1
    d_row = dates.searchsorted(m["d"], side="right") - 1
    ok = m["pe_date"].notna().to_numpy() & (pe_row >= 0) & (col >= 0)
    m["mv_pe"] = np.where(ok, cl[pe_row.clip(0), col.clip(0)], np.nan) * m["shares_basic"]
    m["ltri_pe"] = np.where(ok, lt[pe_row.clip(0), col.clip(0)], np.nan)
    m["ltri_d"] = np.where(col >= 0, lt[d_row.clip(0), col.clip(0)], np.nan)
    mv = m["mv_pe"] * np.exp(m["ltri_d"] - m["ltri_pe"])
    pos = lambda s: s.where(s > 0)  # noqa: E731
    recent = (m["d"] - m["av_date"]) <= pd.Timedelta(days=92)
    out = {
        "gp_assets": m["gross_profit_ttm"] / pos(m["assets"]),
        "op_equity": m["operating_income_ttm"] / pos(m["equity"]),
        "roa": m["net_income_ttm"] / pos(m["assets"]),
        "cfo_assets": m["op_cash_flow_ttm"] / pos(m["assets"]),
        "accruals": -(m["net_income_ttm"] - m["op_cash_flow_ttm"]) / pos(m["assets"]),
        "asset_growth": -(m["assets"] / pos(m["assets_4q"]) - 1.0),
        "net_issuance": -m["net_common_issued_ttm"] / pos(mv),
        "book_to_market": m["equity"] / pos(mv),
        "earnings_yield": m["net_income_ttm"] / pos(mv),
        "fcf_yield": m["free_cash_flow_ttm"] / pos(mv),
        "sales_yield": m["revenues_ttm"] / pos(mv),
        "capex_assets": -(-m["capex_ttm"]).abs() / pos(m["assets"]),
        "sue": (m["ni_yoy"] / m["ni_yoy_sd"].where(m["ni_yoy_sd"] > 0)).where(recent),
        "revenue_surprise": (m["rev_yoy"] / m["rev_yoy_sd"].where(m["rev_yoy_sd"] > 0)).where(recent),
    }
    frames = {}
    for k, v in out.items():
        s = pd.Series(v.to_numpy(), index=pd.MultiIndex.from_arrays([m["d"], m["instrument_id"]]))
        s = s.replace([np.inf, -np.inf], np.nan)
        frames[k] = s.unstack().reindex(index=month_ends, columns=ids)
    return frames
