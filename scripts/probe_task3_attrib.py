#!/usr/bin/env python3
"""TASK 3 probe (READ-ONLY): factor attribution + statistical context for AlphaMax's live -5%.

Answers:
  1. What did the plain 12-1 momentum factor book itself do over the live window (2026-06-29..)?
  2. Market context: SPY, momentum-crash days, sleeve worst days, long/short leg decomposition.
  3. Is the realized drawdown statistically consistent with a 0.0-0.5 Sharpe / 10-13% vol strategy?
  4. Is the realized Alpaca curve tracking the engine's own book (marked independently from the lake)?

Writes nothing outside artifacts/diag/. Never modifies src/configs/DBs.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path("/Users/arhancanli/alphaforge")
LAKE = ROOT / "data" / "lake" / "ohlcv_1d"            # deployed lake (fresh)
LAKE_SHARADAR = ROOT / "data" / "lake_sharadar" / "ohlcv_1d"  # research lake (may be stale)
LAKE_MF = ROOT / "data" / "lake_mf" / "ohlcv_1d"
OUT = ROOT / "artifacts" / "diag"
OUT.mkdir(parents=True, exist_ok=True)

FORMATION = dt.date(2026, 6, 26)   # last session before the v2 go-live (2026-06-29)
WIN_START = dt.date(2026, 6, 26)   # track close-to-close from here
WIN_END = dt.date(2026, 7, 17)


def read_inst(lake: Path, iid: str, years: tuple[int, ...]) -> dict[dt.date, float]:
    """{date: close} for one instrument from a hive lake, robust to the schema-merge quirk."""
    out: dict[dt.date, float] = {}
    for y in years:
        f = lake / f"instrument_id={iid}" / f"year={y}" / "data.parquet"
        if not f.exists():
            fs = glob.glob(str(lake / f"instrument_id={iid}" / f"year={y}" / "*.parquet"))
            if not fs:
                continue
            f = Path(fs[0])
        t = pq.ParquetFile(f).read(columns=["ts_open", "close"]).to_pydict()
        for ts, c in zip(t["ts_open"], t["close"]):
            d = ts.date() if hasattr(ts, "date") else dt.datetime.fromtimestamp(ts / 1000, dt.UTC).date()
            if c is not None and float(c) > 0:
                out[d] = float(c)
    return out


def daily_from_closes(closes: dict[dt.date, float], dates: list[dt.date]) -> dict[dt.date, float]:
    """close-to-close simple returns keyed by the LATER date, forward-filling gaps."""
    r = {}
    prev = None
    for d in dates:
        c = closes.get(d)
        if c is None:
            continue
        if prev is not None:
            r[d] = c / prev - 1.0
        prev = c
    return r


def main() -> None:
    rep: dict = {}

    # ---------------- lake freshness ----------------
    aapl_sh = read_inst(LAKE_SHARADAR, "XUSE:CASH:AAPLUSD", (2026,))
    aapl_lk = read_inst(LAKE, "XUSE:CASH:AAPLUSD", (2026,))
    rep["lake_sharadar_last"] = str(max(aapl_sh)) if aapl_sh else None
    rep["lake_deployed_last"] = str(max(aapl_lk)) if aapl_lk else None
    print(f"lake_sharadar ends {rep['lake_sharadar_last']}  |  deployed data/lake ends {rep['lake_deployed_last']}")

    # ---------------- engine book (equity_live_fwd leg_01 positions) ----------------
    t = pq.read_table(ROOT / "artifacts/walkforward/equity_live_fwd/legs/leg_01/positions.parquet").to_pydict()
    by_ts: dict[dt.date, dict[str, float]] = defaultdict(dict)
    for ts, iid, w in zip(t["ts"], t["instrument_id"], t["weight"]):
        d = dt.datetime.fromtimestamp(ts / 1000, dt.UTC).date()
        if abs(float(w)) > 1e-9:
            by_ts[d][iid] = float(w)
    eng_dates = sorted(d for d in by_ts if WIN_START <= d <= WIN_END)
    book_names = sorted({iid for d in eng_dates for iid in by_ts[d]})
    print(f"engine book: {len(eng_dates)} dates {eng_dates[0]}..{eng_dates[-1]}, {len(book_names)} names")

    closes = {iid: read_inst(LAKE, iid, (2025, 2026)) for iid in book_names}
    missing = [iid for iid in book_names if not closes[iid]]
    if missing:
        print(f"  !! {len(missing)} book names missing from deployed lake: {[m.split(':')[-1] for m in missing]}")

    # trading calendar = union of dates seen in the book names' closes, restricted to window
    cal = sorted({d for c in closes.values() for d in c if WIN_START <= d <= WIN_END})
    print(f"lake sessions in window: {[str(d) for d in cal]}")

    # per-name daily returns
    name_ret: dict[str, dict[dt.date, float]] = {}
    for iid, c in closes.items():
        # include pre-window last close so the first window day has a return
        allc = dict(sorted(c.items()))
        dates_all = [d for d in allc if dt.date(2026, 5, 1) <= d <= WIN_END]
        name_ret[iid] = daily_from_closes({d: allc[d] for d in dates_all}, dates_all)

    # (A) engine-held book marked independently from the lake, daily, w from PREVIOUS engine date
    eng_daily: dict[dt.date, float] = {}
    eng_long: dict[dt.date, float] = {}
    eng_short: dict[dt.date, float] = {}
    for i in range(1, len(eng_dates)):
        d_prev, d_now = eng_dates[i - 1], eng_dates[i]
        w = by_ts[d_prev]
        r = rl = rs = 0.0
        for iid, wi in w.items():
            ri = name_ret.get(iid, {}).get(d_now)
            if ri is None:
                continue
            r += wi * ri
            if wi > 0:
                rl += wi * ri
            else:
                rs += wi * ri
        eng_daily[d_now] = r
        eng_long[d_now] = rl
        eng_short[d_now] = rs

    # (B) FROZEN factor book: the engine's 2026-06-26 weights held without any de-risk/rebalance
    w0 = by_ts[dt.date(2026, 6, 26)]
    froz_daily: dict[dt.date, float] = {}
    for i in range(1, len(eng_dates)):
        d_now = eng_dates[i]
        r = 0.0
        for iid, wi in w0.items():
            ri = name_ret.get(iid, {}).get(d_now)
            if ri is not None:
                r += wi * ri
        froz_daily[d_now] = r

    # ---------------- independent plain 12-1 book from the lake ----------------
    cfg = json.load(open(ROOT / "artifacts/walkforward/equity_live_fwd/walkforward.json"))["config"]
    universe = cfg["instrument_ids"]
    print(f"independent 12-1 build over {len(universe)} configured universe names ...")
    ind_closes: dict[str, list[tuple[dt.date, float]]] = {}
    for iid in universe:
        c = read_inst(LAKE, iid, (2025, 2026))
        if c:
            ind_closes[iid] = sorted(c.items())
    print(f"  {len(ind_closes)} names have lake data")

    # formation-date index per name; 12-1 momentum = P[t-21]/P[t-252]-1
    def build_leg_book(k: int) -> dict[str, float]:
        moms: list[tuple[str, float, float]] = []  # iid, mom, sigma63
        for iid, series in ind_closes.items():
            dates = [d for d, _ in series]
            px = [p for _, p in series]
            # locate formation session (must have traded within 5 sessions of formation)
            idx = None
            for j in range(len(dates) - 1, -1, -1):
                if dates[j] <= FORMATION:
                    idx = j
                    break
            if idx is None or (FORMATION - dates[idx]).days > 7 or idx < 252:
                continue
            p_t21, p_t252 = px[idx - 21], px[idx - 252]
            if p_t252 <= 0:
                continue
            mom = p_t21 / p_t252 - 1.0
            rets = [px[j] / px[j - 1] - 1.0 for j in range(idx - 62, idx + 1) if px[j - 1] > 0]
            if len(rets) < 40:
                continue
            sig = float(np.std(rets, ddof=1)) * math.sqrt(252)
            if sig <= 0:
                continue
            moms.append((iid, mom, sig))
        moms.sort(key=lambda x: -x[1])
        longs, shorts = moms[:k], moms[-k:]
        w: dict[str, float] = {}
        for leg, sgn in ((longs, 1.0), (shorts, -1.0)):
            raw = {iid: sgn / sig for iid, _, sig in leg}
            g = sum(abs(v) for v in raw.values())
            for iid, v in raw.items():
                w[iid] = v / g * 0.25  # per-leg gross 0.25 => total 0.5 (the recipe's half-gross)
        return w

    ind_results = {}
    for k in (30, 100):
        wk = build_leg_book(k)
        nav = 1.0
        daily = {}
        navs = {}
        for i in range(1, len(cal)):
            d = cal[i]
            r = 0.0
            for iid, wi in wk.items():
                sr = dict(ind_closes[iid])
                c_now, c_prev = sr.get(d), sr.get(cal[i - 1])
                if c_now and c_prev:
                    r += wi * (c_now / c_prev - 1.0)
            daily[d] = r
            nav *= 1.0 + r
            navs[d] = nav
        ind_results[k] = {"daily": daily, "cum": nav - 1.0}
        print(f"  plain 12-1 K={k}/side inverse-vol dn book, frozen at {FORMATION}: cum {nav-1.0:+.4%} through {cal[-1]}")

    # ---------------- SPY ----------------
    spy = read_inst(LAKE_MF, "XUSE:CASH:SPYUSD", (2025, 2026))
    spy_dates = sorted(d for d in spy if dt.date(2026, 5, 1) <= d <= WIN_END)
    spy_ret = daily_from_closes({d: spy[d] for d in spy_dates}, spy_dates)
    spy_win = [d for d in sorted(spy_ret) if d >= cal[1]]
    spy_cum = 1.0
    for d in spy_win:
        spy_cum *= 1 + spy_ret[d]
    print(f"SPY window cum ({spy_win[0]}..{spy_win[-1]}): {spy_cum-1.0:+.4%}")

    # ---------------- realized Alpaca curve ----------------
    con = sqlite3.connect(f"file:{ROOT/'var/trading_equity.sqlite'}?mode=ro", uri=True)
    rows = con.execute("SELECT ts, equity_quote FROM equity_curve ORDER BY ts").fetchall()
    con.close()
    daily_marks = [(dt.datetime.fromtimestamp(ts / 1000, dt.UTC).date(), eq)
                   for ts, eq in rows if ts % 86_400_000 == 0]
    # Alpaca 1D history stamps the CLOSE of trading day D at (D+1) 00:00 UTC -> shift back one session
    sessions_all = sorted({d for d in aapl_lk})  # deployed-lake 2026 sessions

    def prev_session(d: dt.date) -> dt.date:
        c = d - dt.timedelta(days=1)
        while c not in sessions_all and c > dt.date(2026, 1, 1):
            c -= dt.timedelta(days=1)
        return c

    real_close = {prev_session(d): eq for d, eq in daily_marks}
    real_dates = sorted(real_close)
    real_ret = {real_dates[i]: real_close[real_dates[i]] / real_close[real_dates[i - 1]] - 1.0
                for i in range(1, len(real_dates))}
    last_mark = rows[-1]
    print(f"realized: {real_close[real_dates[0]]:.0f} @{real_dates[0]} -> {real_close[real_dates[-1]]:.0f} @{real_dates[-1]} "
          f"({real_close[real_dates[-1]]/1e6-1:+.4%}); freshest intraday mark "
          f"{dt.datetime.fromtimestamp(last_mark[0]/1000, dt.UTC)} = {last_mark[1]:.0f} ({last_mark[1]/1e6-1:+.4%})")

    # ---------------- table + correlations ----------------
    print("\n  date        realized   engine-sim  eng-marked  frozen0626  ind K=30   ind K=100  SPY")
    simt = pq.read_table(ROOT / "artifacts/walkforward/equity_live_fwd/equity.parquet").to_pydict()
    sim_eq = {dt.datetime.fromtimestamp(ts / 1000, dt.UTC).date(): e for ts, e in zip(simt["ts"], simt["equity"])}
    sim_dates = sorted(d for d in sim_eq if WIN_START <= d <= WIN_END)
    sim_ret = {sim_dates[i]: sim_eq[sim_dates[i]] / sim_eq[sim_dates[i - 1]] - 1.0 for i in range(1, len(sim_dates))}

    def fmt(x):
        return f"{x:+.3%}".rjust(9) if x is not None else "      ---"

    for d in cal[1:]:
        print(f"  {d}  {fmt(real_ret.get(d))}  {fmt(sim_ret.get(d))}  {fmt(eng_daily.get(d))}  "
              f"{fmt(froz_daily.get(d))}  {fmt(ind_results[30]['daily'].get(d))}  "
              f"{fmt(ind_results[100]['daily'].get(d))}  {fmt(spy_ret.get(d))}")

    def cum(dd):
        n = 1.0
        for d in cal[1:]:
            if d in dd:
                n *= 1 + dd[d]
        return n - 1

    print(f"\n  cumulative over window: realized {cum(real_ret):+.4%} | engine-sim {cum(sim_ret):+.4%} | "
          f"eng-marked {cum(eng_daily):+.4%} | frozen {cum(froz_daily):+.4%} | "
          f"K30 {ind_results[30]['cum']:+.4%} | K100 {ind_results[100]['cum']:+.4%} | SPY {spy_cum-1:+.4%}")

    both = [d for d in cal[1:] if d in real_ret and d in eng_daily]
    a = np.array([real_ret[d] for d in both]); b = np.array([eng_daily[d] for d in both])
    s = np.array([spy_ret.get(d, 0.0) for d in both])
    f = np.array([froz_daily[d] for d in both])
    print(f"  corr(realized, engine-book-marked) = {np.corrcoef(a,b)[0,1]:+.3f} on {len(both)} days")
    print(f"  corr(realized, frozen-factor)      = {np.corrcoef(a,f)[0,1]:+.3f}")
    print(f"  corr(realized, SPY)                = {np.corrcoef(a,s)[0,1]:+.3f}")
    print(f"  corr(frozen-factor, SPY)           = {np.corrcoef(f,s)[0,1]:+.3f}")
    # tracking gap: realized minus what its own held book earned per the lake
    gap = float(np.prod(1 + a) - np.prod(1 + b))
    print(f"  tracking gap (realized cum - eng-marked cum, same days) = {gap:+.4%}")

    # worst realized days with context
    worst = sorted(both, key=lambda d: real_ret[d])[:4]
    print("\n  worst realized days:")
    for d in worst:
        print(f"    {d}: realized {real_ret[d]:+.3%} | book-marked {eng_daily.get(d,float('nan')):+.3%} "
              f"(long {eng_long.get(d,0):+.3%} / short {eng_short.get(d,0):+.3%}) | SPY {spy_ret.get(d,0):+.3%}")

    # ---------------- statistics ----------------
    rr = np.array([real_ret[d] for d in sorted(real_ret) if d >= dt.date(2026, 6, 29)])
    n = len(rr)
    vol_d = float(np.std(rr, ddof=1))
    vol_ann = vol_d * math.sqrt(252)
    cumr = float(np.prod(1 + rr) - 1)
    eqc = np.cumprod(1 + rr)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eqc]))
    mdd = float(np.max(1 - np.concatenate([[1.0], eqc]) / peak))
    print(f"\n  realized stats (n={n} trading days from go-live): cum {cumr:+.4%}, maxDD {mdd:.4%}, "
          f"daily vol {vol_d:.4%}, ann vol {vol_ann:.2%}")
    print(f"  worst day in sigma (own realized vol): {min(rr)/vol_d:+.2f}σ")
    for tgt in (0.10, 0.13, vol_ann):
        sd = tgt / math.sqrt(252)
        print(f"  at {tgt:.1%} ann vol: cum move = {cumr/(sd*math.sqrt(n)):+.2f}σ ; window sigma = {sd*math.sqrt(n):.3%}")

    rng = np.random.default_rng(7)
    n_mc = 200_000
    print(f"\n  Monte Carlo ({n_mc:,} paths, {n} days):")
    for ann_vol in (0.10, 0.13, round(vol_ann, 4)):
        sd = ann_vol / math.sqrt(252)
        for sharpe in (0.0, 0.25, 0.5):
            mu = sharpe * ann_vol / 252
            paths = rng.normal(mu, sd, size=(n_mc, n))
            eq = np.cumprod(1 + paths, axis=1)
            fin = eq[:, -1] - 1
            pk = np.maximum.accumulate(np.concatenate([np.ones((n_mc, 1)), eq], axis=1), axis=1)
            dd = np.max(1 - np.concatenate([np.ones((n_mc, 1)), eq], axis=1) / pk, axis=1)
            p_fin = float(np.mean(fin <= cumr))
            p_dd = float(np.mean(dd >= mdd))
            print(f"    vol {ann_vol:.1%} Sharpe {sharpe:.2f}: P(cum<= {cumr:.2%}) = {p_fin:.3%} ; P(maxDD>= {mdd:.2%}) = {p_dd:.3%}")

    # ---------------- other sleeves ----------------
    print("\n  other sleeves (live):")
    for name, db, base in (("crypto", "trading_crypto_perp.sqlite", 100000.0),
                           ("managed_futures", "trading_managed_futures.sqlite", 100000.0)):
        con = sqlite3.connect(f"file:{ROOT/'var'/db}?mode=ro", uri=True)
        rws = con.execute("SELECT ts, equity_quote FROM equity_curve WHERE equity_quote IS NOT NULL ORDER BY ts").fetchall()
        con.close()
        v = [e for _, e in rws]
        pk2 = -1e18
        mdd2 = 0.0
        for e in v:
            pk2 = max(pk2, e)
            mdd2 = max(mdd2, 1 - e / pk2)
        d0 = dt.datetime.fromtimestamp(rws[0][0] / 1000, dt.UTC).date()
        d1 = dt.datetime.fromtimestamp(rws[-1][0] / 1000, dt.UTC).date()
        print(f"    {name}: {v[0]:.0f} ({d0}) -> {v[-1]:.0f} ({d1}) = {v[-1]/base-1:+.3%}, maxDD {mdd2:.3%}")
    # ALPHAC book at published fixed weights 0.40 eq / 0.40 crypto / 0.20 trend (sleeve returns)
    eq_r = real_close[real_dates[-1]] / 1e6 - 1
    print(f"    book (0.4*eq {eq_r:+.3%} + 0.4*crypto + 0.2*trend) computed in report")

    json.dump({"note": "task3 attribution probe", "generated": str(dt.datetime.now(dt.UTC))},
              open(OUT / "task3_meta.json", "w"))


if __name__ == "__main__":
    main()
