#!/usr/bin/env python3
"""READ-ONLY: decompose sim's big day (label 07-02 = session 07-01) name-by-name,
and compare with what the LIVE account actually held that session (from Alpaca fills).
Also final aligned tracking-error stats. Outputs to stdout + artifacts/diag/ only."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

AF = Path(__file__).resolve().parent.parent
LEG = AF / "artifacts/walkforward/equity_live_fwd/legs/leg_01"

pos = pq.read_table(LEG / "positions.parquet").to_pandas()
pos["date"] = pd.to_datetime(pos["ts"], unit="ms").dt.date
pos = pos[~pos["instrument_id"].str.startswith("BINANCE")]

d_prev = dt.date(2026, 7, 1)   # book held during the session labeled 07-02
d_this = dt.date(2026, 7, 2)
book = pos[pos["date"] == d_prev].set_index("instrument_id")["weight"]

def bar(iid: str, year: int = 2026) -> pd.DataFrame | None:
    p = AF / f"data/lake/ohlcv_1d/instrument_id={iid}/year={year}/data.parquet"
    if not p.exists():
        return None
    df = pq.ParquetFile(p).read(columns=["ts_open", "close"]).to_pandas()
    df["date"] = pd.to_datetime(df["ts_open"]).dt.date
    return df.set_index("date")

# bars are stamped at ts_open (session date); session 07-01 return = close(07-01)/close(06-30).
d_base = dt.date(2026, 6, 30)
d_sess = dt.date(2026, 7, 1)
rows = []
for iid, w in book.items():
    df = bar(iid)
    if df is None or d_base not in df.index or d_sess not in df.index:
        rows.append((iid, w, float("nan"), float("nan")))
        continue
    r = df.loc[d_sess, "close"] / df.loc[d_base, "close"] - 1.0
    rows.append((iid, w, r, w * r))
dec = pd.DataFrame(rows, columns=["iid", "w", "bar_ret", "contrib"]).dropna()
dec = dec.sort_values("contrib")
print(f"SIM decomposition, session {d_sess} (book labeled {d_prev}): "
      f"sum w*r = {dec['contrib'].sum()*100:.2f}%  (sim day labeled 07-02 was -7.33%)")
print("\nWORST 15 contributors:")
print(dec.head(15).to_string(index=False))
print("\nBEST 5:")
print(dec.tail(5).to_string(index=False))

# what did LIVE hold in those names going into session 07-01?
orders = json.load(open(AF / "artifacts/diag/alpaca_equity_orders.json"))
fills = [o for o in orders if float(o["filled_qty"] or 0) > 0]
def sym(iid: str) -> str:
    return iid.split(":")[-1][:-3]  # XUSE:CASH:ABCUSD -> ABC
live_qty: dict[str, float] = {}
for o in fills:
    fa = o.get("filled_at")
    if fa and fa < "2026-07-01T13:00:00Z":  # filled before session 07-01 open (13:30 UTC)
        q = float(o["filled_qty"]) * (1 if o["side"] == "buy" else -1)
        s = o["symbol"]
        live_qty[s] = live_qty.get(s, 0.0) + q

print("\nLIVE holdings (from fills) in the sim's 15 worst names at session 07-01 open, vs sim weight:")
acct_eq = 1_010_912.0  # live equity at close 06-30 (label 07-01)
for _, r in dec.head(15).iterrows():
    s = sym(r["iid"])
    lq = live_qty.get(s, 0.0)
    df = bar(r["iid"])
    px = df.loc[d_base, "close"] if df is not None and d_base in df.index else float("nan")
    lw = lq * px / acct_eq if px == px else float("nan")
    print(f"  {s:6} sim_w={r['w']:+.4f} bar_ret={r['bar_ret']:+7.1%} sim_contrib={r['contrib']*100:+6.2f}%"
          f"  live_qty={lq:+10.1f} live_w={lw:+.4f}")

# ---- aligned stats over the recon window ----
sim = pq.read_table(AF / "artifacts/walkforward/equity_live_fwd/equity.parquet").to_pandas()
sim["date"] = pd.to_datetime(sim["ts"], unit="ms").dt.date
sim = sim.set_index("date")["equity"]
ph = json.load(open(AF / "artifacts/diag/alpaca_equity_portfolio_history.json"))
live = pd.Series({dt.datetime.fromtimestamp(t, dt.UTC).date(): e
                  for t, e in zip(ph["timestamp"], ph["equity"]) if e},)
live = live[live.index >= dt.date(2026, 6, 26)]
sim_w = sim[sim.index >= dt.date(2026, 6, 29)]
# unify: label sets differ on holiday boundaries (sim 07-06 == live 07-03 == session 07-02;
# sim 07-13 == live 07-11 == session 07-10). Map both to a common trading-session sequence:
# each label = close of the PREVIOUS session; consecutive labels in each series are consecutive
# sessions, so align positionally from a verified common anchor label 06-30 (= close of 06-29).
sim_v = sim_w[sim_w.index >= dt.date(2026, 6, 29)].tolist()
sim_d = sim_w[sim_w.index >= dt.date(2026, 6, 29)].index.tolist()
liv_v = live.tolist()
liv_d = live.index.tolist()
i_s = sim_d.index(dt.date(2026, 6, 29))   # sim label 06-29 = close of session 06-26
i_l = liv_d.index(dt.date(2026, 6, 27))   # live label 06-27 (Sat 00:00 UTC) = close of session 06-26
n = min(len(sim_v) - i_s, len(liv_v) - i_l)
print(f"\nPOSITIONALLY ALIGNED (anchor label 06-29 = close of session 06-26, {n} common marks):")
print(f"{'sim_label':>11}{'live_label':>12}{'sim_ret%':>9}{'live_ret%':>10}{'diff_bps':>9}")
diffs = []
for k in range(1, n):
    sr = sim_v[i_s + k] / sim_v[i_s + k - 1] - 1
    lr = liv_v[i_l + k] / liv_v[i_l + k - 1] - 1
    diffs.append((lr - sr) * 1e4)
    print(f"{str(sim_d[i_s+k]):>11}{str(liv_d[i_l+k]):>12}{sr*100:>8.2f}%{lr*100:>9.2f}%{(lr-sr)*1e4:>9.0f}")
ds = pd.Series(diffs)
cum_sim = sim_v[i_s + n - 1] / sim_v[i_s] - 1
cum_liv = liv_v[i_l + n - 1] / liv_v[i_l] - 1
print(f"\ncumulative over the {n-1} aligned sessions: sim {cum_sim*100:+.2f}%  live {cum_liv*100:+.2f}%  "
      f"gap {(cum_liv-cum_sim)*1e4:+.0f} bps (positive = live beat sim)")
print(f"daily diff: mean {ds.mean():+.1f} bps  mean|.| {ds.abs().mean():.1f} bps  median|.| {ds.abs().median():.1f} bps  "
      f"ann.TE {ds.std()*(252**0.5)/100:.1f}%")
sr = pd.Series([sim_v[i_s+k]/sim_v[i_s+k-1]-1 for k in range(1, n)])
lr = pd.Series([liv_v[i_l+k]/liv_v[i_l+k-1]-1 for k in range(1, n)])
print(f"daily return correlation: {sr.corr(lr):.3f}")
print(f"last 6 sessions |diff|: {[round(abs(x),1) for x in diffs[-6:]]} bps")
