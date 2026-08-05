#!/usr/bin/env python3
"""PROBE — IS ALPHAMAX EXECUTABLE AT SMALL CAPITAL? Spec LOCKED 2026-08-03.

WHY THIS EXISTS (not a K-grid re-run — a different question)
------------------------------------------------------------
The construction study already swept weighting x breadth and found a FLAT surface (White
Reality Check p=0.315) — that asked "which K maximises Sharpe?" and the answer was "none,
keep K=100". This asks something else entirely: "at $10k-$100k of real capital, which
constructions can be PHYSICALLY EXECUTED at all?" — a constraint question, not a search.

The measured problem: the live construction (K=100/side, gross ~0.30x) at $10k deploys
~$2,975 across 177 names = ~$17 per position. At $17 a position a $30 stock is ONE share,
so whole-share rounding alone is +/-100% of intended weight. Separately, 49% of the live
short book trades under $17/share, where Alpaca's $5.00/share short maintenance floor costs
~57% of the position's market value.

So the question is NOT "is a concentrated book better" (the grid says no). It is: "if small
capital FORCES concentration, how much edge does that forcing cost?" A cost is expected and
acceptable; the point is to measure it honestly BEFORE real money, not after.

============================== PRE-REGISTERED SPEC ==============================
Locked before any number was computed. One pass, no search-and-pick.

UNIVERSE : the live equity lake (data/lake), PIT top-2000 by dollar volume, as the live
           sleeve uses. Plus, for the FILTERED arms, two tradability constraints that the
           research path does NOT currently model (can_short is hardcoded True at ingest):
             - price floor: last close >= $17 on the SHORT leg only (the $5/share short
               maintenance floor exceeds 30% of market value below ~$17). Longs unaffected.
             - borrow filter: short leg restricted to names Alpaca reports shortable AND
               easy_to_borrow (data/research/alpaca_assets.parquet, fetched 2026-08-02).
               This is a CURRENT snapshot applied to history — an acknowledged approximation
               (see CAVEATS), disclosed rather than hidden.
SIGNAL   : unchanged. 12-1 momentum, identical to live. NOTHING about the alpha is touched.
ARMS     : BASE   K=100/side, no filters      (the live construction)
           F100   K=100/side, + filters
           F50    K=50/side,  + filters
           F30    K=30/side,  + filters
           F20    K=20/side,  + filters
WEIGHTS  : inverse-vol, dollar-neutral, gross 1.0 (arms compared at equal gross so the
           comparison is about breadth/filters, not leverage).
TIMING   : monthly reform, decide at close t, effective t+1. Committed costs: 6bp one-way
           + 50bp/yr borrow on short gross.
REPORTED : net Sharpe, ann vol, maxDD, turnover, AND the executability table (position size
           and whole-share rounding error at $10k / $25k / $50k / $100k).

PRE-REGISTERED READING RULE (so this cannot be spun):
  * This probe CANNOT be used to claim a concentrated book is BETTER. The grid already
    settled that. Any Sharpe improvement here is to be treated as noise unless it exceeds
    the grid's own bootstrap noise band, which it almost certainly will not.
  * Its ONLY legitimate output is the COST of forced concentration + the executability
    table, i.e. "what does small capital cost us, and what is the smallest account that can
    run this book honestly."

    uv run python scripts/probe_alphamax_smallaccount.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
from lib.px_adjust import adjusted_log_returns

LAKE = "data/lake/ohlcv_1d"
ASSETS = "data/research/alpaca_assets.parquet"
OUT = Path("artifacts/probe/alphamax_smallaccount")
START = "2015-01-01"          # deep enough for multi-regime, short enough to load quickly
PRICE_FLOOR_SHORT = 17.0
COST_ONEWAY = 0.0006
BORROW_ANN = 0.0050
TOP_N_UNIVERSE = 2000
ARMS = [("BASE", 100, False), ("F100", 100, True), ("F50", 50, True), ("F30", 30, True), ("F20", 20, True)]


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """close and dollar-volume panels for the equity lake."""
    files = sorted(glob.glob(f"{LAKE}/instrument_id=*/**/*.parquet", recursive=True))
    ids = sorted({f.split("instrument_id=")[1].split("/")[0] for f in files})
    closes, dvols = {}, {}
    for iid in ids:
        ff = [f for f in files if f"instrument_id={iid}/" in f]
        try:
            d = pd.concat([pd.read_parquet(f, columns=["ts_open", "close", "volume"]) for f in ff])
        except Exception:  # noqa: BLE001 — a malformed shard must not kill the pass
            continue
        d = d.drop_duplicates("ts_open").sort_values("ts_open")
        idx = pd.to_datetime(d["ts_open"], unit="ms").dt.normalize()
        sym = iid.split(":")[-1].removesuffix("USD")
        c = pd.Series(d["close"].astype(float).values, index=idx.values)
        closes[sym] = c[~c.index.duplicated()]
        dv = pd.Series((d["close"] * d["volume"]).astype(float).values, index=idx.values)
        dvols[sym] = dv[~dv.index.duplicated()]
    px = pd.DataFrame(closes).sort_index()
    dv = pd.DataFrame(dvols).sort_index().reindex_like(px)
    px = px.loc[px.index >= pd.Timestamp(START)]
    return px, dv.loc[dv.index >= pd.Timestamp(START)]


def run_arm(px, dv, adv, mom, borrowable, k: int, filt: bool):
    m_ends = [g.index[-1] for _, g in px.groupby([px.index.year, px.index.month])]
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    # ADJUSTED (2026-08-05): raw closes made every split a fake -75% day, which inflated
    # the 63d vol estimate of exactly the mega-caps that dominate the inverse-vol weights.
    vol = adjusted_log_returns(px).rolling(63, min_periods=40).std()
    for i, t in enumerate(m_ends[:-1]):
        sig = mom.loc[t].dropna()
        liq = adv.loc[t].reindex(sig.index)
        sig = sig[liq.rank(ascending=False) <= TOP_N_UNIVERSE]     # PIT top-2000 by ADV
        if len(sig) < 4 * k:
            continue
        v = vol.loc[t].reindex(sig.index)
        ranked = sig.sort_values(ascending=False)
        longs = ranked.index[:k]
        short_pool = ranked.index[::-1]
        if filt:  # borrow + price floor apply to the SHORT leg only
            p = px.loc[t]
            short_pool = [s for s in short_pool if borrowable.get(s, False) and p.get(s, 0) >= PRICE_FLOOR_SHORT]
        shorts = list(short_pool)[:k]
        if len(shorts) < k // 2:
            continue
        nxt = px.index[px.index > t]
        if len(nxt) == 0:
            break
        seg = (px.index >= nxt[0]) & (px.index <= m_ends[i + 1])
        for side, names, sgn in (("L", longs, 1.0), ("S", shorts, -1.0)):
            iv = (1.0 / v.reindex(names)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            if iv.sum() <= 0:
                continue
            w.loc[seg, list(names)] = sgn * 0.5 * (iv / iv.sum()).values
    rets = adjusted_log_returns(px)
    held = w.shift(1).fillna(0.0)
    gross_r = (held * rets).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1).fillna(0.0)
    borrow = held.clip(upper=0).abs().sum(axis=1) * (BORROW_ANN / 252.0)
    net = (gross_r - turn * COST_ONEWAY - borrow).dropna()
    live = net[held.abs().sum(axis=1) > 0]
    return live, turn, w


def stats(r: pd.Series, turn: pd.Series) -> dict:
    sd = r.std(ddof=0)
    eq = (1 + r).cumprod()
    return {
        "net_sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
        "ann_vol": float(sd * np.sqrt(252)),
        "max_dd": float((eq / eq.cummax() - 1).min()),
        "turnover_ann": float(turn.sum() / (len(r) / 252)) if len(r) else 0.0,
        "n_days": int(len(r)),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading lake ...", flush=True)
    px, dv = load_panel()
    print(f"  panel {px.shape[1]} names x {px.shape[0]} sessions ({px.index.min().date()}..{px.index.max().date()})")
    adv = dv.rolling(21, min_periods=10).mean()
    mom = np.log(px.shift(21) / px.shift(252))          # 12-1, PIT
    a = pd.read_parquet(ASSETS)
    borrowable = dict(zip(a.symbol, (a.shortable & a.easy_to_borrow).astype(bool), strict=False))
    print(f"  borrowable universe: {sum(borrowable.values()):,} of {len(borrowable):,} Alpaca symbols\n")

    rows = {}
    for name, k, filt in ARMS:
        r, turn, _ = run_arm(px, dv, adv, mom, borrowable, k, filt)
        if len(r) < 250:
            print(f"  {name}: insufficient live days ({len(r)})")
            continue
        rows[name] = stats(r, turn)
        s = rows[name]
        print(f"  {name:<5} K={k:>3} filt={str(filt):<5} netSR {s['net_sharpe']:+.3f}  "
              f"vol {s['ann_vol']:.3f}  maxDD {s['max_dd']:+.3f}  turn {s['turnover_ann']:.2f}x")

    print("\nEXECUTABILITY (gross 1.0x, position = equity/(2K); ~$300-500 is the practical floor)")
    print(f"  {'arm':<6}{'names':>7}" + "".join(f"{f'${e//1000}k':>10}" for e in (10_000, 25_000, 50_000, 100_000)))
    for name, k, _ in ARMS:
        if name not in rows:
            continue
        cells = "".join(f"{'$'+format(int(e/(2*k)),','):>10}" for e in (10_000, 25_000, 50_000, 100_000))
        print(f"  {name:<6}{2*k:>7}{cells}")

    base = rows.get("BASE", {}).get("net_sharpe")
    print("\nCOST OF FORCED CONCENTRATION (vs BASE, the live construction)")
    for name in ("F100", "F50", "F30", "F20"):
        if name in rows and base is not None:
            print(f"  {name:<5} dSharpe {rows[name]['net_sharpe'] - base:+.3f}")
    print("\nREADING RULE: this probe CANNOT claim concentration is better (the weighting x breadth")
    print("grid already returned a flat surface, White Reality Check p=0.315). Its only valid output")
    print("is the COST of forced concentration and the smallest account that can run the book.")

    import json
    (OUT / "result.json").write_text(json.dumps({"arms": rows, "price_floor_short": PRICE_FLOOR_SHORT}, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
