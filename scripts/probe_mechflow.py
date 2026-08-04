#!/usr/bin/env python3
"""MECHANICAL-FLOW FREE PROBE — forced, price-insensitive rebalancing flows on DAILY data we own.

The lead: some flows are driven by a MECHANICAL CONSTRAINT (a calendar boundary, a fixed-weight
mandate) rather than a view on price, so any predictability they create is orthogonal to the usual
risk-premium factors. This probe tests the variants that are genuinely testable on the daily lakes
already on disk (data/lake_mf: 17 macro ETFs, 2001-2026, Yahoo total-return adjusted), NET of the
committed equity/ETF cost model, with PIT discipline and a deflated (multiple-testing) Sharpe.

Variants
--------
A. TURN-OF-MONTH (TOM) calendar flow — long an equity index ETF only across the month-boundary
   window (last L trading days + first F trading days), flat (cash @ 0) otherwise. The forced flow
   is systematic month-start cash deployment (salary/pension/401k contributions, fund inflows).
B. 60/40 REBALANCING flow — at each month/quarter boundary, fixed-weight funds sell the asset that
   outperformed and buy the laggard to restore target weights (a price-INSENSITIVE forced trade).
   Signal: over a trailing lookback, is equity(SPY) ahead of bonds(TLT)? If so pensions will
   SELL equity / BUY bonds into the boundary -> take that same side (long TLT / short SPY) across
   the last K trading days of the period. This is the purest mechanical-constraint variant.
C. LEVERAGED-ETF rebalance-flow PROXY (daily) — constant-leverage ETFs must trade ~ (L^2-L)*NAV*r
   in the SAME direction as today's underlying move, into the close, every day. The TRUE signal is
   intraday (last 30-60 min) and scales with LETF AUM; we own NEITHER intraday bars NOR an AUM
   series, and the LETFs themselves have only ~2 weeks of live-feed history in our lakes. So the
   only free-testable shadow is: does a large same-day move in an underlying with a big LETF complex
   (QQQ/SPY/IWM/TLT) predict next-day continuation/reversal? Reported HONESTLY as a weak daily proxy.

Discipline (matches scripts/mf_gauntlet.py):
- Decide at close(t-1) / hold over day t / measure OPEN(t)->OPEN(t+1) return. No same-bar fill, no
  look-ahead: every signal (calendar membership, trailing relative momentum) uses info <= close(t-1).
- Costs ALWAYS included: committed ETF model = 1bp commission + 3bp half-spread + 2bp latency per
  side (=6bp one-way price+fee), 50bp/yr short borrow accrued per holding day. Impact ~0 at research
  size for these liquid majors (see capacity note).
- Deflated Sharpe (Bailey/Lopez de Prado) over EVERY configuration tried, via the repo's
  alphaforge.validation.dsr. An honest NULL is a full success.
"""
# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.validation.dsr import dsr_from_returns  # noqa: E402

LAKE = Path("data/lake_mf/ohlcv_1d")
OUT = Path("artifacts/sweep/mechflow_probe")

# Committed ETF friction (configs/managed_futures.yaml costs:) -----------------------------------
COMMISSION_BPS = 1.0
HALF_SPREAD_BPS = 3.0
LATENCY_BPS = 2.0
ONEWAY_BPS = COMMISSION_BPS + HALF_SPREAD_BPS + LATENCY_BPS  # 6 bps per side, of notional traded
BORROW_BPS_ANNUAL = 50.0
PPY = 252.0  # equity/ETF trading-day count for annualization (DSR itself is per-period)


def load_etf(ticker: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(LAKE / f"instrument_id=XUSE:CASH:{ticker}USD" / "**" / "*.parquet"), recursive=True))
    if not fs:
        raise FileNotFoundError(ticker)
    df = pd.concat([pd.read_parquet(f) for f in fs]).sort_values("ts_open")
    df = df[["ts_open", "open", "close"]].dropna()
    df["d"] = pd.to_datetime(df["ts_open"]).dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates("d").set_index("d")
    return df[["open", "close"]].astype(float)


def calendar_flags(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Trading-day-of-month (1=first) and reverse (1=last), plus quarter-end reverse index.

    Pure calendar -> knowable arbitrarily far in advance; no look-ahead."""
    df = pd.DataFrame(index=index)
    ym = index.to_period("M")
    df["tdom"] = pd.Series(index, index=index).groupby(ym).cumcount() + 1  # 1..n within month
    df["rtdom"] = pd.Series(index, index=index).groupby(ym).cumcount(ascending=False) + 1  # 1=last
    yq = index.to_period("Q")
    df["rtdoq"] = pd.Series(index, index=index).groupby(yq).cumcount(ascending=False) + 1  # 1=last of quarter
    df["month"] = index.month
    return df


def per_period_sr(returns: np.ndarray) -> float:
    r = returns[np.isfinite(returns)]
    if r.size < 2:
        return float("nan")
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r) / sd) if sd > 0 else float("nan")


def summarize(daily: pd.Series, label: str, exposure: float | None = None,
              trades_per_yr: float | None = None) -> dict:
    r = daily.to_numpy(dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    sr_pp = per_period_sr(r)
    sr_ann = sr_pp * np.sqrt(PPY)
    vol_ann = float(np.std(r, ddof=1) * np.sqrt(PPY))
    mean_ann = float(np.mean(r) * PPY)
    curve = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(curve)
    max_dd = float((curve / peak - 1.0).min())
    sk = float(pd.Series(r).skew())
    return {
        "label": label, "n_obs": int(n), "sr_ann": round(sr_ann, 3),
        "sr_per_period": sr_pp, "vol_ann": round(vol_ann, 4), "ret_ann": round(mean_ann, 4),
        "max_dd": round(max_dd, 4), "skew": round(sk, 3),
        "exposure": None if exposure is None else round(exposure, 3),
        "trades_per_yr": None if trades_per_yr is None else round(trades_per_yr, 1),
    }


# ------------------------------------------------------------------------------------- Variant A
def variant_a_tom(px: dict, cal: pd.DataFrame, asset: str, L: int, F: int) -> tuple[pd.Series, dict]:
    """Long `asset` over the TOM window (last L + first F trading days), else flat (cash@0)."""
    o = px[asset]["open"]
    r_oo = (o.shift(-1) / o - 1.0).rename("r")  # hold over day t: open(t)->open(t+1)
    member = ((cal["rtdom"] <= L) | (cal["tdom"] <= F)).astype(float)  # membership of day t, calendar-known
    pos = member.reindex(r_oo.index).fillna(0.0)  # weight held over day t (decided at close t-1)
    turn = pos.diff().abs().fillna(pos.abs())  # |pos_t - pos_{t-1}|, traded at open t
    cost = turn * (ONEWAY_BPS * 1e-4)
    strat = (pos * r_oo - cost).dropna()
    expo = float((pos.reindex(strat.index) != 0).mean())
    tpy = float(turn.reindex(strat.index).gt(0).sum() / (len(strat) / PPY))
    s = summarize(strat, f"A_TOM_{asset}_L{L}F{F}", expo, tpy)
    return strat, s


# ------------------------------------------------------------------------------------- Variant B
def variant_b_rebal(px: dict, cal: pd.DataFrame, lookback: int, K: int, boundary: str,
                    eq: str = "SPY", bd: str = "TLT") -> tuple[pd.Series, dict]:
    """Fade the trailing relative winner into the last K days of month/quarter (pension rebalance flow).

    If equity outperformed bonds over `lookback` (equity is overweight) -> funds SELL equity / BUY
    bonds to restore weights -> take that side: LONG bond, SHORT equity across the window."""
    oe, ob = px[eq]["open"], px[bd]["open"]
    idx = oe.index.intersection(ob.index)
    oe, ob = oe.reindex(idx), ob.reindex(idx)
    re = (oe.shift(-1) / oe - 1.0)  # equity day-t return
    rb = (ob.shift(-1) / ob - 1.0)  # bond day-t return
    # trailing relative momentum measured to close(t-1): cum return over prior `lookback` days,
    # using close prices, lagged one day so the signal for day t uses only info <= t-1.
    ce, cb = px[eq]["close"].reindex(idx), px[bd]["close"].reindex(idx)
    mom_e = ce.pct_change(lookback)
    mom_b = cb.pct_change(lookback)
    rel = (mom_e - mom_b).shift(1)  # >0 => equity ahead => pensions sell equity / buy bond
    rcol = "rtdom" if boundary == "month" else "rtdoq"
    in_win = (cal[rcol].reindex(idx) <= K)
    side = -np.sign(rel).where(in_win, 0.0).fillna(0.0)  # +1 => long equity/short bond ; -1 => opposite
    # side is the equity weight; bond weight is the opposite (dollar-neutral pair, 0.5 gross each leg)
    w_eq = 0.5 * side
    w_bd = -0.5 * side
    turn = (w_eq.diff().abs().fillna(w_eq.abs()) + w_bd.diff().abs().fillna(w_bd.abs()))
    cost = turn * (ONEWAY_BPS * 1e-4)
    # short borrow: 50bp/yr accrued per day on whichever leg is short
    short_notional = np.maximum(-w_eq, 0.0) + np.maximum(-w_bd, 0.0)
    borrow = short_notional * (BORROW_BPS_ANNUAL * 1e-4 / 365.0)
    strat = (w_eq * re + w_bd * rb - cost - borrow).dropna()
    expo = float((side.reindex(strat.index) != 0).mean())
    tpy = float(turn.reindex(strat.index).gt(0).sum() / (len(strat) / PPY))
    s = summarize(strat, f"B_REBAL_{boundary}_lb{lookback}_K{K}", expo, tpy)
    return strat, s


# ------------------------------------------------------------------------------------- Variant C
def variant_c_letf_proxy(px: dict, asset: str, thresh_sigma: float, direction: int) -> tuple[pd.Series, dict, float]:
    """Daily LETF-flow PROXY: after a >thresh_sigma same-day move, take next-day position = direction*sign(move).

    direction=+1 tests CONTINUATION (ride the forced flow), -1 tests REVERSAL (fade the overshoot).
    Signal at close(t-1); hold over day t (open->open). Weak proxy — true signal is intraday+AUM.
    Also returns the next-day IC (corr of signed move_{t-1} with r_oo_t)."""
    c = px[asset]["close"]
    o = px[asset]["open"]
    r_cc = c.pct_change()  # close-to-close daily return (the LETF rebalancing driver)
    vol = r_cc.rolling(63).std()
    sig_raw = np.sign(r_cc) * (r_cc.abs() > thresh_sigma * vol)  # +/-1 on big days, else 0; as of close t
    sig = (direction * sig_raw).shift(1)  # position for day t decided at close t-1
    r_oo = (o.shift(-1) / o - 1.0)
    pos = sig.reindex(r_oo.index).fillna(0.0)
    turn = pos.diff().abs().fillna(pos.abs())
    cost = turn * (ONEWAY_BPS * 1e-4)
    # borrow when short
    borrow = np.maximum(-pos, 0.0) * (BORROW_BPS_ANNUAL * 1e-4 / 365.0)
    strat = (pos * r_oo - cost - borrow).dropna()
    # IC: signed magnitude of yesterday's move vs today's oo return (continuation sign)
    xz = (r_cc / vol).shift(1)
    j = pd.concat([xz.rename("x"), r_oo.rename("y")], axis=1).dropna()
    ic = float(np.corrcoef(j["x"], j["y"])[0, 1]) if len(j) > 50 else float("nan")
    expo = float((pos.reindex(strat.index) != 0).mean())
    tpy = float(turn.reindex(strat.index).gt(0).sum() / (len(strat) / PPY))
    s = summarize(strat, f"C_LETF_{asset}_thr{thresh_sigma}_dir{direction:+d}", expo, tpy)
    return strat, s, ic


def subperiod_sr(daily: pd.Series) -> dict:
    out = {}
    for lo, hi in [("2001", "2010"), ("2010", "2018"), ("2018", "2027")]:
        seg = daily[(daily.index >= lo) & (daily.index < hi)].to_numpy(dtype=float)
        seg = seg[np.isfinite(seg)]
        out[f"{lo}-{hi}"] = round(per_period_sr(seg) * np.sqrt(PPY), 3) if seg.size > 30 else None
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tickers = ["SPY", "QQQ", "IWM", "TLT", "IEF", "SHY"]
    px = {t: load_etf(t) for t in tickers}
    # common calendar from SPY (longest equity history)
    cal = calendar_flags(px["SPY"].index)

    trials: list[dict] = []
    series: dict[str, pd.Series] = {}

    # --- Variant A: TOM long-only equity ------------------------------------------------------
    a_windows = [(1, 3), (1, 4), (0, 3), (1, 2), (2, 3)]
    for asset in ["SPY", "QQQ", "IWM"]:
        for (L, F) in a_windows:
            st, s = variant_a_tom(px, cal, asset, L, F)
            trials.append(s); series[s["label"]] = st

    # --- Variant B: 60/40 rebalancing reversal -------------------------------------------------
    for boundary in ["month", "quarter"]:
        for lb in [21, 63]:
            for K in [1, 3, 5]:
                st, s = variant_b_rebal(px, cal, lb, K, boundary)
                trials.append(s); series[s["label"]] = st

    # --- Variant C: LETF daily-flow proxy ------------------------------------------------------
    c_ics: list[dict] = []
    for asset in ["QQQ", "SPY", "IWM", "TLT"]:
        for thr in [1.5, 2.0]:
            for direction in (+1, -1):
                st, s, ic = variant_c_letf_proxy(px, asset, thr, direction)
                trials.append(s); series[s["label"]] = st
                if direction == +1:
                    c_ics.append({"asset": asset, "thresh": thr, "next_day_IC": round(ic, 4)})

    # --- benchmark: buy&hold SPY (open->open, net of one entry) --------------------------------
    o = px["SPY"]["open"]
    bh = (o.shift(-1) / o - 1.0).dropna()
    bh_s = summarize(bh, "BENCH_SPY_buyhold", 1.0, 0.0)

    # --- deflated Sharpe over EVERY configuration tried ----------------------------------------
    sr_list = [t["sr_per_period"] for t in trials if t["sr_per_period"] == t["sr_per_period"]]
    n_trials = len(sr_list)
    sr_var = float(np.var(np.array(sr_list), ddof=1)) if n_trials > 1 else 0.0
    # rank trials by annualized Sharpe; deflate each variant's champion honestly
    for t in trials:
        t["subperiod_sr"] = subperiod_sr(series[t["label"]])
    trials_sorted = sorted(trials, key=lambda x: (x["sr_ann"] if x["sr_ann"] == x["sr_ann"] else -9), reverse=True)

    def deflate(label: str) -> dict:
        rep = dsr_from_returns(series[label], n_trials=max(n_trials, 2), sr_trials_variance=sr_var, periods_per_year=PPY)
        return {"psr": round(rep.psr, 4), "dsr": round(rep.dsr, 4),
                "expected_max_sr_ann": round(rep.expected_max_sr * np.sqrt(PPY), 3)}

    # champion overall + champion per variant family
    champ_overall = trials_sorted[0]["label"]
    fam = {}
    for pfx in ["A_", "B_", "C_"]:
        cand = [t for t in trials_sorted if t["label"].startswith(pfx)]
        if cand:
            fam[pfx] = cand[0]["label"]

    deflated = {"n_trials": n_trials, "sr_trials_variance": round(sr_var, 6),
                "champion_overall": {**next(t for t in trials if t["label"] == champ_overall), **deflate(champ_overall)}}
    for pfx, lab in fam.items():
        deflated[f"champion_{pfx.rstrip('_')}"] = {**next(t for t in trials if t["label"] == lab), **deflate(lab)}

    report = {
        "probe": "mechanical-flow (turn-of-month / 60-40 rebalancing / LETF daily proxy)",
        "data": {"lake": str(LAKE), "tickers": tickers,
                 "span": f"{px['SPY'].index.min().date()}..{px['SPY'].index.max().date()}",
                 "note": "LETFs (TQQQ/SPXL/...) have only ~2wk live-feed history on disk; true intraday LETF-rebalance signal NOT free-testable."},
        "cost_model": {"oneway_bps": ONEWAY_BPS, "commission_bps": COMMISSION_BPS,
                       "half_spread_bps": HALF_SPREAD_BPS, "latency_bps": LATENCY_BPS,
                       "borrow_bps_annual": BORROW_BPS_ANNUAL, "impact": "~0 at research size (liquid majors)"},
        "benchmark": bh_s,
        "letf_proxy_next_day_IC": c_ics,
        "deflated": deflated,
        "all_trials": trials_sorted,
    }
    (OUT / "mechflow_report.json").write_text(json.dumps(report, indent=2, default=str))

    # console summary ---------------------------------------------------------------------------
    print("\n================ MECHANICAL-FLOW FREE PROBE ================")
    print(f"  data        : {tickers}  {report['data']['span']}")
    print(f"  costs       : {ONEWAY_BPS:.0f}bp one-way + {BORROW_BPS_ANNUAL:.0f}bp/yr borrow  (impact ~0, liquid)")
    print(f"  benchmark   : buy&hold SPY  Sharpe {bh_s['sr_ann']}  vol {bh_s['vol_ann']}")
    print(f"  n_trials    : {n_trials}   sr_trials_var {sr_var:.5f}")
    print("  --- champions (NET of cost), deflated over all trials ---")
    for key in ["champion_overall", "champion_A", "champion_B", "champion_C"]:
        c = deflated.get(key)
        if not c:
            continue
        print(f"  {key:18s}: {c['label']:26s} Sharpe {c['sr_ann']:+.2f}  DSR {c['dsr']:.3f}  PSR {c['psr']:.3f}"
              f"  expo {c['exposure']}  t/yr {c['trades_per_yr']}  skew {c['skew']}  maxDD {c['max_dd']}")
        print(f"                       subperiod SR {c['subperiod_sr']}")
    print("  --- LETF daily-proxy next-day IC (weak; true signal is intraday+AUM) ---")
    for d in c_ics:
        print(f"     {d['asset']:4s} thr{d['thresh']}: IC {d['next_day_IC']:+.4f}")
    print(f"  artifacts   : {OUT}/mechflow_report.json")
    print("  gate        : deploy needs DSR>=0.95 net of costs. An honest NULL is the deliverable.")
    print("============================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
