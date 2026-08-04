#!/usr/bin/env python3
"""READ-ONLY diagnostic: AlphaMax live-vs-sim reconciliation.

Pulls (GET only, never submits/cancels/modifies):
  * Alpaca equity paper account: order history since 2026-06-26, portfolio history, positions
  * var/trading_equity.sqlite equity_curve (read-only URI)
  * artifacts/walkforward/equity_live_fwd/equity.parquet (sim forward curve)

Writes scratch outputs to artifacts/diag/ only.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import httpx
import pandas as pd
import pyarrow.parquet as pq

AF = Path(__file__).resolve().parent.parent
OUT = AF / "artifacts" / "diag"
OUT.mkdir(parents=True, exist_ok=True)

ENV_PATH = Path.home() / ".config" / "alphaforge" / "alpaca_equity.env"
env = {}
for line in ENV_PATH.read_text().splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

BASE = env.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
HDRS = {"APCA-API-KEY-ID": env["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]}
assert "paper" in BASE, f"refusing non-paper base URL {BASE}"

client = httpx.Client(headers=HDRS, timeout=30.0)

# ---- account ----
acct = client.get(f"{BASE}/v2/account").json()
print(f"ACCOUNT: equity={acct['equity']} cash={acct['cash']} long_mv={acct['long_market_value']} "
      f"short_mv={acct['short_market_value']} status={acct['status']} created={acct.get('created_at')}")

# ---- portfolio history (authoritative daily marks) ----
ph = client.get(f"{BASE}/v2/account/portfolio/history",
                params={"period": "1A", "timeframe": "1D"}).json()
ph_rows = [(t, e) for t, e in zip(ph["timestamp"], ph["equity"]) if e is not None]
print(f"\nPORTFOLIO HISTORY ({len(ph_rows)} daily marks):")
for t, e in ph_rows:
    print(f"  {dt.datetime.utcfromtimestamp(t).date()}  {e:,.2f}")

# ---- full order history since 2026-06-26 (paginated, ascending) ----
orders = []
after = "2026-06-25T00:00:00Z"
while True:
    r = client.get(f"{BASE}/v2/orders",
                   params={"status": "all", "limit": 500, "direction": "asc", "after": after})
    batch = r.json()
    if not isinstance(batch, list):
        print("ORDERS ERROR:", batch)
        break
    if not batch:
        break
    orders.extend(batch)
    after = batch[-1]["submitted_at"]
    if len(batch) < 500:
        break
print(f"\nTOTAL ORDERS since 2026-06-26: {len(orders)}")

# dedupe on id (pagination overlap)
seen, uniq = set(), []
for o in orders:
    if o["id"] not in seen:
        seen.add(o["id"])
        uniq.append(o)
orders = uniq
print(f"unique orders: {len(orders)}")

# per-day (ET submit date) status breakdown + fill economics
day_stat = defaultdict(lambda: defaultdict(int))
day_qty = defaultdict(lambda: [0.0, 0.0])           # [ordered_notional, filled_notional]
slip_bps_w = defaultdict(lambda: [0.0, 0.0])        # [sum(|slip_bps|*notional)... signed], weight
day_slip = defaultdict(lambda: [0.0, 0.0])          # [signed slip cost $ vs limit, filled notional]
fill_delay = []
for o in orders:
    sub = dt.datetime.fromisoformat(o["submitted_at"].replace("Z", "+00:00"))
    d = str((sub - dt.timedelta(hours=4)).date())   # rough ET date
    st = o["status"]
    day_stat[d][st] += 1
    q = float(o["qty"] or 0)
    fq = float(o["filled_qty"] or 0)
    lp = float(o["limit_price"]) if o.get("limit_price") else None
    fp = float(o["filled_avg_price"]) if o.get("filled_avg_price") else None
    ref = lp or fp or 0.0
    day_qty[d][0] += q * ref
    if fp:
        day_qty[d][1] += fq * fp
        if lp:
            # signed execution cost vs the limit reference: buy filled below limit = saving
            sgn = 1.0 if o["side"] == "buy" else -1.0
            cost = sgn * (fp - lp) * fq
            day_slip[d][0] += cost
            day_slip[d][1] += fq * fp
    if o.get("filled_at"):
        fat = dt.datetime.fromisoformat(o["filled_at"].replace("Z", "+00:00"))
        fill_delay.append((fat - sub).total_seconds() / 3600.0)

print("\nPER-DAY ORDER OUTCOMES (ET submit date):")
print(f"{'date':12}{'filled':>8}{'canceled':>10}{'expired':>9}{'rejected':>10}{'other':>7}"
      f"{'ordered$':>14}{'filled$':>14}{'fill%':>7}{'slip$vs-lim':>12}")
for d in sorted(day_stat):
    s = day_stat[d]
    filled = s.get("filled", 0) + s.get("partially_filled", 0)
    canceled = s.get("canceled", 0)
    expired = s.get("expired", 0)
    rejected = s.get("rejected", 0)
    other = sum(v for k, v in s.items() if k not in ("filled", "partially_filled", "canceled", "expired", "rejected"))
    onot, fnot = day_qty[d]
    pct = 100.0 * fnot / onot if onot else 0.0
    print(f"{d:12}{filled:>8}{canceled:>10}{expired:>9}{rejected:>10}{other:>7}"
          f"{onot:>14,.0f}{fnot:>14,.0f}{pct:>6.1f}%{day_slip[d][0]:>12,.0f}")

if fill_delay:
    fd = pd.Series(fill_delay)
    print(f"\nfill delay hours: mean {fd.mean():.2f}  median {fd.median():.2f}  p90 {fd.quantile(0.9):.2f}  max {fd.max():.2f}")

# partial fills
partials = [o for o in orders if o["status"] == "partially_filled" or
            (o["status"] == "canceled" and float(o["filled_qty"] or 0) > 0)]
print(f"partial/canceled-with-fill orders: {len(partials)}")

# ---- current positions ----
pos = client.get(f"{BASE}/v2/positions").json()
lv = sum(float(p["market_value"]) for p in pos if float(p["market_value"]) > 0)
sv = sum(float(p["market_value"]) for p in pos if float(p["market_value"]) < 0)
print(f"\nPOSITIONS: {len(pos)} open | long ${lv:,.0f} short ${sv:,.0f} gross ${lv - sv:,.0f} "
      f"net ${lv + sv:,.0f} (equity ${float(acct['equity']):,.0f} -> gross {(lv - sv)/float(acct['equity']):.2f}x)")

# save raw for further analysis
(OUT / "alpaca_equity_orders.json").write_text(json.dumps(orders))
(OUT / "alpaca_equity_portfolio_history.json").write_text(json.dumps(ph))
(OUT / "alpaca_equity_positions.json").write_text(json.dumps(pos))

# ---- reconciliation: live vs sim daily returns ----
sim = pq.read_table(AF / "artifacts/walkforward/equity_live_fwd/equity.parquet").to_pandas()
sim["date"] = pd.to_datetime(sim["ts"], unit="ms").dt.date
sim = sim.set_index("date")["equity"]

con = sqlite3.connect(f"file:{AF}/var/trading_equity.sqlite?mode=ro", uri=True)
live_rows = con.execute("SELECT ts, equity_quote FROM equity_curve ORDER BY ts").fetchall()
con.close()
# Alpaca 1D portfolio-history marks land at 00:00 UTC keyed to the SESSION date? verify against ph
ldb = pd.Series({dt.datetime.utcfromtimestamp(t / 1000).date(): e for t, e in live_rows
                 if t % 86400000 == 0})
# broker's own portfolio history as the authoritative live curve
lph = pd.Series({dt.datetime.utcfromtimestamp(t).date(): e for t, e in ph_rows})

start = dt.date(2026, 6, 26)
sim_w = sim[sim.index >= start]
lph_w = lph[lph.index >= start]
print("\nDAY-BY-DAY (sim date vs broker portfolio-history date, raw — alignment checked next):")
print(f"{'date':12}{'sim_eq':>12}{'sim_ret%':>9}{'live_eq':>12}{'live_ret%':>10}{'diff_bps':>9}")
sim_r = sim_w.pct_change()
lph_r = lph_w.pct_change()
alld = sorted(set(sim_w.index) | set(lph_w.index))
for d in alld:
    se = sim_w.get(d, float("nan"))
    le = lph_w.get(d, float("nan"))
    sr = sim_r.get(d, float("nan"))
    lr = lph_r.get(d, float("nan"))
    diff = (lr - sr) * 1e4 if pd.notna(lr) and pd.notna(sr) else float("nan")
    print(f"{str(d):12}{se:>12,.0f}{sr*100:>8.2f}%{le:>12,.0f}{lr*100:>9.2f}%{diff:>9.0f}")

print("\nDB daily marks (midnight rows) for cross-check:")
for d, e in ldb[ldb.index >= start].items():
    print(f"  {d}  {e:,.2f}")
client.close()
