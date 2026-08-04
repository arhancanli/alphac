#!/usr/bin/env python3
"""TASK 3 probe part 2 (READ-ONLY): split-adjusted factor attribution.

Fix found by part 1: ALIT 1-for-20 reverse split (ex 2026-07-01) marked raw by the forward
engine => phantom -4.84% day in the simulated curve. Here every return in the window is
corporate-action-adjusted from the lake's own corporate_actions table, all books recomputed,
and any remaining >50% daily move is flagged and cross-checked for an unrecorded action.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path("/Users/arhancanli/alphaforge")
LAKE = ROOT / "data" / "lake" / "ohlcv_1d"
CA = ROOT / "data" / "lake" / "corporate_actions"
LAKE_MF = ROOT / "data" / "lake_mf" / "ohlcv_1d"

FORMATION = dt.date(2026, 6, 26)
WIN_START = dt.date(2026, 6, 26)
WIN_END = dt.date(2026, 7, 17)


def read_closes(iid: str, years=(2025, 2026)) -> list[tuple[dt.date, float]]:
    out = {}
    for y in years:
        f = LAKE / f"instrument_id={iid}" / f"year={y}" / "data.parquet"
        if not f.exists():
            continue
        t = pq.ParquetFile(f).read(columns=["ts_open", "close"]).to_pydict()
        for ts, c in zip(t["ts_open"], t["close"]):
            if c is not None and float(c) > 0:
                out[ts.date()] = float(c)
    return sorted(out.items())


def read_splits(iid: str) -> dict[dt.date, float]:
    """{ex_date: ratio} splits for one instrument (ratio = new/old share count; price x 1/ratio)."""
    out = {}
    for y in (2025, 2026):
        f = CA / f"instrument_id={iid}" / f"year={y}" / "data.parquet"
        if not f.exists():
            continue
        t = pq.ParquetFile(f).read().to_pydict()
        n = len(t["action_type"])
        for i in range(n):
            if t["action_type"][i] == "split" and t["ratio"][i] is not None:
                out[t["ex_date"][i].date()] = float(t["ratio"][i])
    return out


def adj_returns(iid: str, closes: list[tuple[dt.date, float]], lo: dt.date, hi: dt.date,
                flags: list) -> dict[dt.date, float]:
    """Split-adjusted daily simple returns keyed by the later date, restricted to [lo, hi]."""
    splits = read_splits(iid)
    r = {}
    for j in range(1, len(closes)):
        d_prev, p_prev = closes[j - 1]
        d_now, p_now = closes[j]
        if not (lo <= d_now <= hi):
            continue
        # any split with ex_date in (d_prev, d_now] scales the raw price by 1/ratio
        mult = 1.0
        for ex, ratio in splits.items():
            if d_prev < ex <= d_now:
                mult *= ratio
        ret = p_now * mult / p_prev - 1.0
        if abs(ret) > 0.5:
            flags.append((iid, d_now, ret, mult != 1.0))
        r[d_now] = ret
    return r


def main() -> None:
    flags: list = []
    # ---- engine book ----
    t = pq.read_table(ROOT / "artifacts/walkforward/equity_live_fwd/legs/leg_01/positions.parquet").to_pydict()
    by_ts: dict[dt.date, dict[str, float]] = defaultdict(dict)
    for ts, iid, w in zip(t["ts"], t["instrument_id"], t["weight"]):
        d = dt.datetime.fromtimestamp(ts / 1000, dt.UTC).date()
        if abs(float(w)) > 1e-9:
            by_ts[d][iid] = float(w)
    eng_dates = sorted(d for d in by_ts if WIN_START <= d <= WIN_END)
    book_names = sorted({iid for d in eng_dates for iid in by_ts[d]})

    closes = {iid: read_closes(iid) for iid in book_names}
    cal = sorted({d for c in closes.values() for d, _ in c if WIN_START <= d <= WIN_END})
    ret = {iid: adj_returns(iid, c, cal[0], WIN_END, flags) for iid, c in closes.items() if c}

    def track(weights_by_date) -> tuple[dict, dict, dict]:
        daily, lng, sht = {}, {}, {}
        for i in range(1, len(eng_dates)):
            d_prev, d_now = eng_dates[i - 1], eng_dates[i]
            w = weights_by_date(d_prev)
            r = rl = rs = 0.0
            for iid, wi in w.items():
                ri = ret.get(iid, {}).get(d_now)
                if ri is None:
                    continue
                r += wi * ri
                if wi > 0:
                    rl += wi * ri
                else:
                    rs += wi * ri
            daily[d_now], lng[d_now], sht[d_now] = r, rl, rs
        return daily, lng, sht

    eng_daily, eng_l, eng_s = track(lambda d: by_ts[d])
    w0 = by_ts[dt.date(2026, 6, 26)]
    froz_daily, fro_l, fro_s = track(lambda d: w0)

    # ---- independent plain 12-1 books, split-adjusted tracking ----
    cfg = json.load(open(ROOT / "artifacts/walkforward/equity_live_fwd/walkforward.json"))["config"]
    uni_closes = {}
    for iid in cfg["instrument_ids"]:
        c = read_closes(iid)
        if c:
            uni_closes[iid] = c
    uni_ret = {iid: adj_returns(iid, c, cal[0], WIN_END, flags) for iid, c in uni_closes.items()}

    def build(k: int) -> dict[str, float]:
        moms = []
        for iid, series in uni_closes.items():
            dates = [d for d, _ in series]
            px = [p for _, p in series]
            idx = None
            for j in range(len(dates) - 1, -1, -1):
                if dates[j] <= FORMATION:
                    idx = j
                    break
            if idx is None or (FORMATION - dates[idx]).days > 7 or idx < 252:
                continue
            splits = read_splits(iid)  # adjust formation prices across any split BEFORE formation
            def adj(j):
                m = 1.0
                for ex, ratio in splits.items():
                    if dates[j] < ex <= dates[idx]:
                        m *= ratio  # bring old price onto the current basis? old*1/ratio... see below
                return px[j] / m  # price BEFORE a reverse split is 1/ratio too low in current basis
            p21, p252 = adj(idx - 21), adj(idx - 252)
            if p252 <= 0:
                continue
            mom = p21 / p252 - 1.0
            rets = [px[j] / px[j - 1] - 1.0 for j in range(idx - 62, idx + 1)]
            if len(rets) < 40:
                continue
            sig = float(np.std(rets, ddof=1)) * math.sqrt(252)
            if sig <= 0:
                continue
            moms.append((iid, mom, sig))
        moms.sort(key=lambda x: -x[1])
        w = {}
        for leg, sgn in ((moms[:k], 1.0), (moms[-k:], -1.0)):
            raw = {iid: sgn / s for iid, _, s in leg}
            g = sum(abs(v) for v in raw.values())
            for iid, v in raw.items():
                w[iid] = v / g * 0.25
        return w

    ind = {}
    for k in (30, 100):
        wk = build(k)
        daily = {}
        for i in range(1, len(cal)):
            d = cal[i]
            daily[d] = sum(wi * uni_ret.get(iid, {}).get(d, 0.0) for iid, wi in wk.items())
        ind[k] = daily

    # ---- SPY ----
    spy_f = LAKE_MF / "instrument_id=XUSE:CASH:SPYUSD" / "year=2026" / "data.parquet"
    tt = pq.ParquetFile(spy_f).read(columns=["ts_open", "close"]).to_pydict()
    spy_c = sorted((x.date(), float(c)) for x, c in zip(tt["ts_open"], tt["close"]))
    spy_ret = {spy_c[j][0]: spy_c[j][1] / spy_c[j - 1][1] - 1.0 for j in range(1, len(spy_c))
               if cal[0] < spy_c[j][0] <= WIN_END}

    # ---- realized ----
    con = sqlite3.connect(f"file:{ROOT/'var/trading_equity.sqlite'}?mode=ro", uri=True)
    rows = con.execute("SELECT ts, equity_quote FROM equity_curve ORDER BY ts").fetchall()
    con.close()
    marks = [(dt.datetime.fromtimestamp(ts / 1000, dt.UTC).date(), eq) for ts, eq in rows if ts % 86_400_000 == 0]
    sess = set(cal) | {dt.date(2026, 6, 25)}
    def prev_sess(d):
        c = d - dt.timedelta(days=1)
        while c not in sess and c > dt.date(2026, 6, 1):
            c -= dt.timedelta(days=1)
        return c
    real_close = {prev_sess(d): eq for d, eq in marks if d >= dt.date(2026, 6, 27)}
    rd = sorted(real_close)
    real_ret = {rd[i]: real_close[rd[i]] / real_close[rd[i - 1]] - 1.0 for i in range(1, len(rd))}

    # ---- report ----
    def fmt(x):
        return f"{x:+.3%}".rjust(9) if x is not None else "      ---"
    print("SPLIT-ADJUSTED daily returns:")
    print("  date        realized   eng-adj    (long      short)    frozen-adj  K30-adj   K100-adj   SPY")
    for d in cal[1:]:
        print(f"  {d}  {fmt(real_ret.get(d))}  {fmt(eng_daily.get(d))}  ({fmt(eng_l.get(d))} {fmt(eng_s.get(d))})  "
              f"{fmt(froz_daily.get(d))}  {fmt(ind[30].get(d))}  {fmt(ind[100].get(d))}  {fmt(spy_ret.get(d))}")

    def cum(dd):
        n = 1.0
        for d in cal[1:]:
            if d in dd:
                n *= 1 + dd[d]
        return n - 1
    print(f"\n  CLEAN cumulative 2026-06-26..{cal[-1]}:")
    print(f"    realized (Alpaca)        {cum(real_ret):+.4%}")
    print(f"    engine book, adj-marked  {cum(eng_daily):+.4%}   (long leg {cum(eng_l):+.4%} / short leg {cum(eng_s):+.4%} additive-ish)")
    print(f"    frozen 06-26 book, adj   {cum(froz_daily):+.4%}")
    print(f"    plain 12-1 K=30, adj     {cum(ind[30]):+.4%}")
    print(f"    plain 12-1 K=100, adj    {cum(ind[100]):+.4%}")
    sc = 1.0
    for d in cal[1:]:
        sc *= 1 + spy_ret.get(d, 0.0)
    print(f"    SPY                      {sc-1:+.4%}")

    both = [d for d in cal[1:] if d in real_ret and d in eng_daily]
    a = np.array([real_ret[d] for d in both]); b = np.array([eng_daily[d] for d in both])
    print(f"\n  corr(realized, eng-adj) = {np.corrcoef(a, b)[0,1]:+.3f} | mean daily gap {np.mean(a-b):+.4%} | "
          f"cum gap {np.prod(1+a)-np.prod(1+b):+.4%}")
    res = a - b
    print(f"  daily tracking residual std = {np.std(res, ddof=1):.4%}")

    # short-leg squeeze contribution: sum of adj contributions from names whose window ret > +20%
    print("\n  biggest single-name CLEAN detractors over the window (engine book, w x cum-ret):")
    tot = {}
    for i in range(1, len(eng_dates)):
        d_prev, d_now = eng_dates[i - 1], eng_dates[i]
        for iid, wi in by_ts[d_prev].items():
            ri = ret.get(iid, {}).get(d_now)
            if ri is not None:
                tot[iid] = tot.get(iid, 0.0) + wi * ri
    for iid, c in sorted(tot.items(), key=lambda x: x[1])[:12]:
        cr = 1.0
        for d in cal[1:]:
            cr *= 1 + ret.get(iid, {}).get(d, 0.0)
        w_last = by_ts[eng_dates[-1]].get(iid, 0.0)
        print(f"    {iid.split(':')[-1][:-3]:8s} contrib {c:+.4%}  (name cum {cr-1:+8.1%}, last w {w_last:+.4f})")

    print("\n  flagged >50% daily moves in window (name, date, adj-ret, had-split-adj):")
    seen = set()
    for iid, d, r, had in sorted(set(flags)):
        key = (iid, d)
        if key in seen:
            continue
        seen.add(key)
        print(f"    {iid.split(':')[-1][:-3]:8s} {d} {r:+10.1%} split-adjusted={had}")
EOF_MARKER_NOT_USED = None


if __name__ == "__main__":
    main()
