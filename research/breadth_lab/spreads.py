"""Each stock's bid-ask spread estimated from its daily close, high and low (Abdi and Ranaldo 2017), as a check on
the cost tiers every round has used (10, 20 and 40 bp one way by dollar volume). The estimate at a day uses only
the six months of bars before it.

    PYTHONPATH=src:. ~/alphaforge/.venv/bin/python -m research.breadth_lab.spreads
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from research.breadth_lab.lab import Ctx, stats
from research.breadth_lab.panel import CACHE, LAKE

HERE = Path(__file__).resolve().parent
COMMISSION = 0.0001
FLOOR, CAP = 0.0002, 0.02


def half_spreads(c: Ctx) -> pd.DataFrame:
    """Trailing half-spread per name and day: S^2 = 4 E[(c_t - eta_t)(c_t - eta_t+1)], eta the log mid-range, over
    126 days of pairs, lagged two days (a pair needs the next day's bar); pairs across a gap above 30% are dropped."""
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    bars = con.execute(f"""SELECT instrument_id, epoch_ms(ts_open) AS t, high, low, close FROM read_parquet('{LAKE}/ohlcv_1d/*/*/data.parquet')
                           WHERE close > 0 AND low > 0 AND high >= low""").df()
    bars = bars[bars["instrument_id"].isin(c.r.columns)]
    bars["t"] = pd.to_datetime(bars["t"], unit="ms", utc=True)
    wide = {k: bars.pivot(index="t", columns="instrument_id", values=k).reindex(index=c.r.index, columns=c.r.columns) for k in ("high", "low", "close")}
    eta = (np.log(wide["high"]) + np.log(wide["low"])) / 2.0
    cl = np.log(wide["close"])
    nxt = eta.shift(-1)
    pair = ((cl - eta) * (cl - nxt)).where((nxt - cl).abs() <= 0.3)
    s2 = 4.0 * pair.rolling(126, min_periods=60).mean()
    return (np.sqrt(s2.clip(lower=0.0)) / 2.0).shift(2)


def main() -> dict:
    from research.breadth_lab import pods
    from research.breadth_lab.book import account
    from research.breadth_lab.lab import context
    from research.breadth_lab.panel import Panel
    from research.breadth_lab.test_d import FROZEN, TEST, _scale
    c = context(Panel("test"))
    half = half_spreads(c)
    est = (half + COMMISSION).clip(FLOOR, CAP).where(c.eligible).fillna(c.cost)
    tier = c.cost.where(c.eligible)
    out = {"method": "Abdi-Ranaldo half-spread over 126 trading days, lagged 2, plus 1 bp commission, floor 2 bp, cap 200 bp; tiers where no estimate",
           "median_one_way_by_tier_and_period": {}}
    for label, tc in (("tier_10bp", 0.0010), ("tier_20bp", 0.0020), ("tier_40bp", 0.0040)):
        m = tier == tc
        out["median_one_way_by_tier_and_period"][label] = {
            p: round(float(np.nanmedian(est.where(m).loc[a:z].to_numpy())), 5)
            for p, (a, z) in {"1998-2007": ("1998", "2007"), "2008-2017": ("2008", "2017"), "2018-2026": ("2018", "2026")}.items()}
    print("medians", json.dumps(out["median_one_way_by_tier_and_period"]), flush=True)
    f = json.loads(FROZEN.read_text())
    pos, hedge = pods._positions(c, f["sleeves"], f["weights"], f["signs"])
    scale = _scale(c, pos, hedge)
    for name, cost in (("tier_costs", c.cost), ("estimated_costs", est)):
        cc = dataclasses.replace(c, cost=cost)
        n, g, expo = account(cc, pos, hedge, scale, float(f["band"]["width"]), bool(f["band"]["edge"]))
        n = n.where(scale.notna())
        out[name] = {"test_years": stats(n.loc[TEST[0]:TEST[1]]), "2008_2017": stats(n.loc["2008-01-01":"2017-12-31"]), **expo}
        print(name, json.dumps(out[name]), flush=True)
    (HERE / "spreads_variant_d.json").write_text(json.dumps(out, indent=1))
    est.astype("float32").to_parquet(CACHE / "estimated_costs.parquet")
    return out


if __name__ == "__main__":
    main()
