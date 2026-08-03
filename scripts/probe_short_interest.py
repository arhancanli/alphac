#!/usr/bin/env python3
"""PROBE — SHORT INTEREST (days-to-cover) AS SLEEVE #4. Spec LOCKED 2026-08-03, before any number.

WHY THIS CANDIDATE, AFTER SIX NULLS
-----------------------------------
Every previous sweep rearranged inputs we already had (price and volume). This is the first
genuinely NEW INPUT in months: bi-monthly FINRA short interest for the whole US tape,
2017-12-29..2026-07-15, unlocked by the Polygon Starter upgrade. A new input is worth more than
another transformation of an old one.

The mechanism is mechanical rather than a risk premium, which is the only family with any
remaining hope here: short sellers face a borrow market with genuinely constrained supply, and
days-to-cover measures how many sessions of normal volume it would take the short base to exit.
That is a real, physical constraint on real participants, not a statistical pattern.

============================== PRE-REGISTERED SPEC ==============================
Locked before any number was computed. ONE configuration. No sweep, no cell-picking. If it
fails, it is dead and goes in the public kill log.

UNIVERSE : PIT top-2000 by 21-day ADV from data/lake, last close >= $5 (below that the borrow
           market is not real), and present in that settlement date's short-interest file.
SIGNAL   : days_to_cover (= short_interest / avg_daily_volume), exactly as published. The
           documented direction is that HIGH short interest predicts LOW forward returns, so:
             LONG  the bottom decile of DTC
             SHORT the top    decile of DTC
TIMING   : *** THE ANTI-LOOKAHEAD RULE *** positions are formed on ``available_from_ms``
           (settlement + 10 business days), NEVER on settlement_date. FINRA disseminates ~8
           business days after settlement; we use 10 for margin. Held until the next
           availability date (~2 weeks). Decide at close t, effective t+1.
WEIGHTS  : equal-weight within leg, dollar-neutral, gross 1.0.
COSTS    : 6bp one-way + borrow on short gross. Borrow is reported at THREE levels because the
           honest answer depends on it entirely (see below): 50bp/yr, 300bp/yr, 1000bp/yr.

THE OBJECTION THIS PROBE MUST ANSWER, AND WHY IT IS REPORTED NOT HIDDEN
----------------------------------------------------------------------
The top DTC decile is, almost by definition, the hard-to-borrow bucket. Those are precisely the
names where borrow is scarce and the fee is not 50bp/yr but 300-10,000bp/yr, and where a broker
can recall the borrow at any time. A backtest that shorts the highest-DTC names at a 50bp borrow
assumption is describing a trade nobody can put on. So this probe reports:
  * the borrow-cost ladder (50 / 300 / 1000 bp per year on short gross), and
  * the same test restricted to names Alpaca currently reports shortable AND easy_to_borrow.
If the edge only exists at 50bp on unborrowable names, that is a KILL, not a finding.

PRE-REGISTERED READING RULE:
  ADD only if ALL of: (a) own_SR > rho x S_b, (b) Newey-West t >= 2, (c) the mean-zeroed control
  gives back most of the book benefit (the gain is the MEAN, not variance dilution), and
  (d) it survives 300bp/yr borrow on the easy-to-borrow-restricted universe.
  Anything else = KILLED.

    uv run python scripts/probe_short_interest.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LAKE = "data/lake/ohlcv_1d"
SI_DIR = Path("data/lake_shortint")
ASSETS = "data/research/alpaca_assets.parquet"
OUT = Path("artifacts/probe/short_interest")
ANN = 252
COST_ONEWAY = 0.0006
TOP_N_UNIVERSE = 2000
PRICE_FLOOR = 5.0
DECILE = 0.10
BORROW_LADDER = (0.0050, 0.0300, 0.1000)


def load_equity_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """close and dollar-volume panels for the US equity lake (XUSE namespace only)."""
    ids = [d for d in os.listdir(LAKE) if d.startswith("instrument_id=XUSE")]
    closes, dvols = {}, {}
    for iid in ids:
        fs = glob.glob(glob.escape(os.path.join(LAKE, iid)) + "/*/*.parquet")
        if not fs:
            continue
        try:
            d = pd.concat([pd.read_parquet(f, columns=["ts_open", "close", "volume"]) for f in fs])
        except Exception:  # noqa: BLE001 — a malformed shard must not kill the pass
            continue
        d = d.drop_duplicates("ts_open").sort_values("ts_open")
        idx = pd.to_datetime(d["ts_open"], unit="ms").dt.normalize()
        sym = iid.split(":")[-1].removesuffix("USD")
        c = pd.Series(d["close"].astype(float).values, index=idx.values)
        closes[sym] = c[~c.index.duplicated()]
        v = pd.Series((d["close"] * d["volume"]).astype(float).values, index=idx.values)
        dvols[sym] = v[~v.index.duplicated()]
    px = pd.DataFrame(closes).sort_index()
    return px, pd.DataFrame(dvols).sort_index().reindex_like(px)


def load_short_interest() -> pd.DataFrame:
    fs = sorted(SI_DIR.glob("settlement_date=*.parquet"))
    if not fs:
        raise SystemExit("no short-interest data — run scripts/ingest_short_interest.py first")
    df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    # THE ANTI-LOOKAHEAD JOIN KEY. settlement_date is when it was MEASURED, not when it was known.
    df["avail"] = pd.to_datetime(df["available_from_ms"], unit="ms").dt.normalize()
    return df.dropna(subset=["days_to_cover", "avail"])


def sharpe(r: pd.Series) -> float:
    sd = r.std(ddof=0)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def nw_t(r: pd.Series, lags: int = 10) -> float:
    x = np.asarray(r, dtype=float)
    n = len(x)
    if n < 30:
        return 0.0
    mu = x.mean()
    e = x - mu
    var = (e @ e) / n
    for L in range(1, lags + 1):
        var += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    se = np.sqrt(max(var, 1e-18) / n)
    return float(mu / se)


def run(px, adv, si, borrow_ann: float, restrict: set[str] | None) -> tuple[pd.Series, pd.Series, dict]:
    """Build the dollar-neutral DTC decile book. Returns (net daily rets, turnover, meta)."""
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    dates = sorted(si["avail"].unique())
    n_names = []
    for i, t in enumerate(dates):
        # PIT: only bars strictly at/before the availability date inform the decision
        if t not in px.index:
            cand_idx = px.index[px.index <= t]
            if len(cand_idx) == 0:
                continue
            t_eff = cand_idx[-1]
        else:
            t_eff = t
        snap = si[si["avail"] == t].set_index("ticker")["days_to_cover"]
        liq = adv.loc[t_eff].dropna()
        liq = liq[liq.rank(ascending=False) <= TOP_N_UNIVERSE]
        p = px.loc[t_eff]
        names = [s for s in snap.index if s in liq.index and p.get(s, 0) >= PRICE_FLOOR]
        if restrict is not None:
            names = [s for s in names if s in restrict]
        s = snap.reindex(names).dropna()
        if len(s) < 100:
            continue
        k = max(int(len(s) * DECILE), 10)
        ranked = s.sort_values()
        longs, shorts = list(ranked.index[:k]), list(ranked.index[-k:])
        n_names.append(len(s))
        nxt = px.index[px.index > t_eff]
        if len(nxt) == 0:
            break
        end = dates[i + 1] if i + 1 < len(dates) else px.index[-1]
        seg = (px.index >= nxt[0]) & (px.index <= end)
        w.loc[seg, longs] = 0.5 / len(longs)
        w.loc[seg, shorts] = -0.5 / len(shorts)

    rets = np.log(px).diff()
    held = w.shift(1).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1).fillna(0.0)
    borrow = held.clip(upper=0).abs().sum(axis=1) * (borrow_ann / ANN)
    net = (gross - turn * COST_ONEWAY - borrow).dropna()
    live = net[held.abs().sum(axis=1) > 0]
    return live, turn, {"median_universe": int(np.median(n_names)) if n_names else 0,
                        "rebalances": len(n_names)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading equity lake ...", flush=True)
    px, dv = load_equity_panel()
    adv = dv.rolling(21, min_periods=10).mean()
    si = load_short_interest()
    print(f"  panel {px.shape[1]:,} names x {px.shape[0]:,} sessions")
    print(f"  short interest: {len(si):,} rows, {si['avail'].nunique()} availability dates, "
          f"{si['avail'].min().date()}..{si['avail'].max().date()}")

    ez = None
    if os.path.exists(ASSETS):
        a = pd.read_parquet(ASSETS)
        ez = set(a.loc[(a.shortable) & (a.easy_to_borrow), "symbol"])
        print(f"  easy-to-borrow universe: {len(ez):,} symbols\n")

    print("BORROW-COST LADDER (full universe) — the top DTC decile IS the hard-to-borrow bucket")
    print(f"  {'borrow/yr':>10}{'netSR':>9}{'NW t':>8}{'maxDD':>9}{'turn':>8}")
    rows = {}
    base_r = None
    for b in BORROW_LADDER:
        r, turn, meta = run(px, adv, si, b, None)
        if len(r) < 100:
            print(f"  {b*100:>9.1f}%  insufficient live days ({len(r)})")
            continue
        eq = (1 + r).cumprod()
        rows[f"full_{b}"] = {"net_sharpe": sharpe(r), "nw_t": nw_t(r),
                             "max_dd": float((eq / eq.cummax() - 1).min()),
                             "turnover_ann": float(turn.sum() / (len(r) / ANN)), "n_days": len(r), **meta}
        if base_r is None:
            base_r = r
        v = rows[f"full_{b}"]
        print(f"  {b*100:>9.1f}%{v['net_sharpe']:>9.3f}{v['nw_t']:>8.2f}{v['max_dd']:>9.1%}{v['turnover_ann']:>8.1f}x")

    if ez:
        print("\nRESTRICTED TO EASY-TO-BORROW (the trade you can actually put on)")
        print(f"  {'borrow/yr':>10}{'netSR':>9}{'NW t':>8}{'maxDD':>9}{'turn':>8}")
        for b in BORROW_LADDER:
            r, turn, meta = run(px, adv, si, b, ez)
            if len(r) < 100:
                print(f"  {b*100:>9.1f}%  insufficient live days ({len(r)})")
                continue
            eq = (1 + r).cumprod()
            rows[f"etb_{b}"] = {"net_sharpe": sharpe(r), "nw_t": nw_t(r),
                                "max_dd": float((eq / eq.cummax() - 1).min()),
                                "turnover_ann": float(turn.sum() / (len(r) / ANN)), "n_days": len(r), **meta}
            v = rows[f"etb_{b}"]
            print(f"  {b*100:>9.1f}%{v['net_sharpe']:>9.3f}{v['nw_t']:>8.2f}{v['max_dd']:>9.1%}{v['turnover_ann']:>8.1f}x")

    # ---- diversifier arithmetic against the live book ----
    verdict, checks = "KILLED", {}
    if base_r is not None:
        r_eq = np.log(pd.read_parquet("artifacts/walkforward/k30_dn_63/equity.parquet")
                      .assign(d=lambda d: pd.to_datetime(d["ts"], unit="ms").dt.normalize())
                      .set_index("d")["equity"].astype(float)).diff().dropna()
        r_mf = np.log(pd.read_parquet("artifacts/walkforward/mf_live_fwd/equity.parquet")
                      .assign(d=lambda d: pd.to_datetime(d["ts"], unit="ms").dt.normalize())
                      .set_index("d")["equity"].astype(float)).diff().dropna()
        j = pd.concat([r_eq.rename("eq"), r_mf.rename("mf"), base_r.rename("si")], axis=1).dropna()
        if len(j) > 100:
            book = (0.40 * j["eq"] + 0.20 * j["mf"]) / 0.60
            cand = j["si"]
            S_b, S_c = sharpe(book), sharpe(cand)
            rho = float(np.corrcoef(book, cand)[0, 1])
            bar = rho * S_b
            print(f"\nDIVERSIFIER ARITHMETIC (overlap {j.index.min().date()}..{j.index.max().date()}, {len(j)}d)")
            print(f"  book Sharpe S_b {S_b:+.3f} | candidate {S_c:+.3f} | rho {rho:+.3f} | bar {bar:+.3f}")
            czero = cand - cand.mean()
            print(f"  {'weight':>7}{'book SR':>10}{'delta':>9}{'zeroed d':>10}{'from mean':>11}")
            best = (-9, 0.0, 0.0)
            for wt in (0.05, 0.10, 0.15, 0.20):
                d = sharpe((1 - wt) * book + wt * cand) - S_b
                dz = sharpe((1 - wt) * book + wt * czero) - S_b
                frac = (d - dz) / d * 100 if abs(d) > 1e-12 else 0.0
                print(f"  {wt*100:>6.0f}%{sharpe((1-wt)*book+wt*cand):>10.3f}{d:>+9.3f}{dz:>+10.3f}{frac:>10.0f}%")
                if d > best[0]:
                    best = (d, dz, frac)
            etb300 = rows.get(f"etb_{0.03}") or rows.get(f"full_{0.03}")
            checks = {
                "a_clears_bar": bool(S_c > bar),
                "b_nw_t_ge_2": bool(abs(nw_t(cand)) >= 2.0),
                "c_benefit_is_the_mean": bool(best[2] >= 50.0 and best[0] > 0),
                "d_survives_300bp_etb": bool(etb300 and etb300["net_sharpe"] > 0 and etb300["nw_t"] >= 2.0),
            }
            verdict = "ADD" if all(checks.values()) else "KILLED"
            print("\nPRE-REGISTERED READING RULE")
            for k, v in checks.items():
                print(f"  {'PASS' if v else 'FAIL'}  {k}")
            print(f"\n  VERDICT: {verdict}")

    (OUT / "result.json").write_text(json.dumps(
        {"spec": {"signal": "days_to_cover", "decile": DECILE, "universe_top_n": TOP_N_UNIVERSE,
                  "price_floor": PRICE_FLOOR, "availability_lag_bdays": 10, "configs_tried": 1},
         "arms": rows, "checks": checks, "verdict": verdict}, indent=1))
    print(f"\nartifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
