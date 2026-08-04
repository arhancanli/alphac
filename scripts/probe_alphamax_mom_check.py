"""READ-ONLY diagnostic probe (Task 2 signal-health audit).

Independently recomputes 12-1 momentum (ln(C*_{t-21}/C*_{t-252}), split-adjusted closes)
straight from the lake parquet files for the cross-section active at AlphaMax's last
rebalance decision (2026-07-01), then reports the percentile rank of the live book's
longs and shorts. Longs should rank HIGH, shorts LOW, else the signal path is broken.

Writes nothing except stdout + a CSV under artifacts/diag/.
"""

from __future__ import annotations

import glob
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/arhancanli/alphaforge")
LAKE = ROOT / "data" / "lake"
DECISION = pd.Timestamp("2026-07-01", tz="UTC")  # last big rebalance decision date
LOOKBACK, SKIP = 252, 21

# ---------------------------------------------------------------- book (last ts)
pos = pd.read_parquet(
    ROOT / "artifacts/walkforward/equity_live_fwd/legs/leg_01/positions.parquet"
)
last = pos[pos.ts == pos.ts.max()].copy()
longs = last[last.weight > 0].sort_values("weight", ascending=False)
shorts = last[last.weight < 0].sort_values("weight")

# ---------------------------------------------------------------- cross-section at DECISION
mfiles = glob.glob(str(LAKE / "universe_membership" / "**" / "*.parquet"), recursive=True)
mem = pd.concat([pd.read_parquet(f) for f in mfiles], ignore_index=True)
active = mem[
    (mem.effective_from <= DECISION)
    & (mem.effective_to.isna() | (mem.effective_to > DECISION))
].instrument_id.unique()
print(f"cross-section active @ {DECISION.date()}: {len(active)} members "
      f"({sum(i.startswith('BINANCE') for i in active)} BINANCE perps)")


def splits_factor_series(iid: str) -> list[tuple[pd.Timestamp, float]]:
    out: list[tuple[pd.Timestamp, float]] = []
    d = LAKE / "corporate_actions" / f"instrument_id={iid}"
    if not d.exists():
        return out
    for f in glob.glob(str(d / "**" / "*.parquet"), recursive=True):
        ca = pd.read_parquet(f)
        sp = ca[(ca.action_type == "split") & (ca.ratio != 1.0)]
        for _, r in sp.iterrows():
            out.append((r.ex_date, float(r.ratio)))
    return out


def momentum(iid: str) -> float:
    d = LAKE / "ohlcv_1d" / f"instrument_id={iid}"
    if not d.exists():
        return math.nan
    # only need ~15 months of sessions: read year partitions 2025 + 2026
    frames = []
    for y in (2025, 2026):
        f = d / f"year={y}" / "data.parquet"
        if f.exists():
            frames.append(pd.read_parquet(f, columns=["ts_open", "close"]))
    if not frames:
        return math.nan
    bars = pd.concat(frames).sort_values("ts_open")
    bars = bars[bars.ts_open <= DECISION]
    if len(bars) < LOOKBACK + 1:
        return math.nan
    close = bars.close.to_numpy("float64").copy()
    ts_utc = pd.DatetimeIndex(bars.ts_open)
    if ts_utc.tz is None:
        ts_utc = ts_utc.tz_localize("UTC")
    for ex_date, ratio in splits_factor_series(iid):
        ex = pd.Timestamp(ex_date)
        ex = ex.tz_localize("UTC") if ex.tzinfo is None else ex.tz_convert("UTC")
        if ratio > 0:
            close[np.asarray(ts_utc < ex)] /= ratio
    c_recent = close[-(SKIP + 1)]   # t-21 sessions
    c_old = close[-(LOOKBACK + 1)]  # t-252 sessions
    if c_recent <= 0 or c_old <= 0:
        return math.nan
    return math.log(c_recent / c_old)


rows = []
for iid in active:
    rows.append((iid, momentum(iid)))
mom = pd.DataFrame(rows, columns=["instrument_id", "mom"]).dropna()
mom["pct"] = mom.mom.rank(pct=True) * 100.0
print(f"momentum computed for {len(mom)} / {len(active)} members "
      f"(rest lack {LOOKBACK + 1} sessions by {DECISION.date()})")

book = last.merge(mom[["instrument_id", "pct", "mom"]], on="instrument_id", how="left")


def report(side: pd.DataFrame, label: str, n: int = 10) -> None:
    top = side.reindex(side.weight.abs().sort_values(ascending=False).index).head(n)
    print(f"\n--- top {n} {label} by |weight| (percentile of 12-1 momentum, 100=highest) ---")
    for _, r in top.iterrows():
        p = f"{r.pct:5.1f}" if pd.notna(r.pct) else "  n/a"
        m = f"{r['mom']:+.3f}" if pd.notna(r["mom"]) else "  n/a"
        print(f"  {r.instrument_id:<22} w={r.weight:+.4f}  mom={m}  pct={p}")
    have = side.dropna(subset=["pct"])
    wavg = float(np.average(have.pct, weights=have.weight.abs())) if len(have) else float("nan")
    print(f"  ALL {label}: n={len(side)}  matched={len(have)}  "
          f"median pct={have.pct.median():.1f}  |w|-weighted mean pct={wavg:.1f}")


report(book[book.weight > 0], "LONGS")
report(book[book.weight < 0], "SHORTS")

# where do the active BINANCE perps sit in the cross-section today?
perps = mom[mom.instrument_id.str.startswith("BINANCE")]
if len(perps):
    print("\n--- BINANCE perps inside the equity cross-section ---")
    print(perps.sort_values("pct")[["instrument_id", "mom", "pct"]].to_string(index=False))

outdir = ROOT / "artifacts" / "diag"
outdir.mkdir(parents=True, exist_ok=True)
book.to_csv(outdir / "alphamax_mom_check_20260718.csv", index=False)
print(f"\nwrote {outdir / 'alphamax_mom_check_20260718.csv'}")
