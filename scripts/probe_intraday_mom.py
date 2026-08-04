#!/usr/bin/env python3
"""PROBE — TRACK B / STEP 3: JFE market intraday momentum replication (research-only screen).

Replicates Gao-Han-Li-Zhou (2018 JFE, "Market intraday momentum") and successors:
the FIRST half-hour return predicts the LAST half-hour return. Free local data
(Alpaca IEX 1-min lake built in STEP 1: data/research/intraday_probe/lake/
alpaca_1min_full), blessed comparability machinery (alphaforge.analytics.metrics
.summarize + alphaforge.validation.dsr.dsr_from_returns), committed ETF cost
schedule (configs/managed_futures.yaml: 1bp commission + 3bp half-spread + 2bp
latency = 6bp ONE-WAY). NOTHING in src/, existing scripts, configs, or launchd
jobs is touched.

=============================== PRE-REGISTRATION ===============================
Locked BEFORE looking at any result. No thresholds, no parameter tuning, no
variant added after seeing numbers.

Symbols ......... SPY, QQQ (primary); IWM, TLT (secondary — lower IEX coverage,
                  reported with day counts so thinness is visible).
Signal variants . BOTH documented forms of the first-half-hour return r1:
                  (a) first30_only ....... r1 = c(09:59 bar)/o(09:30 bar) - 1
                  (b) overnight_first30 .. r1 = c(09:59 bar)/prev session close - 1
                      (the original JFE definition; prev session must be <= 4
                      calendar days back, else the day is dropped).
Target .......... r13 = c(15:59 bar)/c(15:29 bar) - 1 (the paper's regression
                  object; descriptive only, never traded on directly).
Strategy ........ position = sign(r1), long/short the LAST half-hour only.
                  ENTRY-FILL HONESTY: you cannot fill AT 15:30 on a mark that IS
                  the 15:30 price -> entry = OPEN of the first bar starting in
                  [15:31, 15:35) ET (a price at/after 15:31:00; ~1-2 min of the
                  window is forgone, honestly).
                  EXIT: close of the last bar starting in [15:55, 16:00) ET —
                  the IEX proxy for the official closing print (an MOC order
                  submitted before the 15:50 cutoff earns the auction close;
                  the IEX last-bar close differs from it by ~1bp, disclosed
                  below). No same-bar fills anywhere: the signal is fixed at
                  10:00, entry is 15:31+, exit is ~16:00.
Costs ........... committed schedule 6bp one-way = 12bp round-trip per traded
                  day (HEADLINE). Sensitivity rows (disclosed, NOT headline):
                  1bp one-way (SPY/QQQ-realistic microstructure) and gross.
Bar-mark windows  (fixed): o0930 = open of first bar in [09:30,09:33);
                  c0959 = close of last bar in [09:55,10:00); c1529 = close of
                  last bar in [15:25,15:30); entry = open of first bar in
                  [15:31,15:35); exit = close of last bar in [15:55,16:00);
                  session close = close of last regular bar. Half-days (last
                  regular bar starts before 15:45 ET) are dropped as trade days
                  (no 15:30-16:00 window) but still supply the prev close.
                  Alpaca bars are stamped at bar START (verified in STEP 1).
Subperiods ...... pre-registered decay table:
                  * paper_window (1993-2013) ... NOT coverable locally (lake
                    starts 2020-07-27) -> DEFERRED to the QC cloud bundle
                    (qc_bundle/research_intraday_probe.py CELL 2), reported as
                    unavailable, never proxied.
                  * postpub_2019_2022 .......... 2019-01-01..2022-12-31, locally
                    TRUNCATED to 2020-07-27 start (disclosed).
                  * recent_2023_2026 ........... 2023-01-01..end of lake.
                  * full_local ................. 2020-07-27..end of lake.
Statistics ...... per (symbol x variant x period): n days, OLS beta of
                  r13 ~ const + r1 with Newey-West HAC t-stat (5 lags, matching
                  the QC bundle), R^2, Spearman IC, hit rate
                  (= mean[sign(r1)*r13 > 0] over days with r1 != 0);
                  strategy mean bps/day gross / net@6bp / net@1bp and annualized
                  Sharpe over TRADED days only, HONEST convention sqrt(252)
                  (one bet per trading day; the book is in the market ~29
                  min/day — return-on-capital is tiny and stated). For the full
                  period also: blessed summarize() Sharpe (A=365 daily-resample
                  convention, comparable to the live sleeves but inflated
                  ~sqrt(365/252)=1.20x for a 252-day equity calendar, labeled)
                  and dsr_from_returns at n_trials=2 (fresh) and n_trials=8
                  (= 2 variants x 4 symbols actually evaluated here), var=1.0,
                  periods=252.
Robustness ...... entry-shift sensitivity: same strategy with entry = open of
                  first bar in [15:32,15:36) — measures mark-noise fragility;
                  never used for selection.
IEX-noise honesty STEP-1 measurement: IEX vs official close-to-close daily
                  return diff median 0.5-1.2bp abs (SPY), ~1bp (QQQ). The same
                  absolute mark noise applies to 30-min returns whose
                  documented gross mean is only ~3-5bp/day: noise does not BIAS
                  the strategy mean (marks are signal-independent) but it
                  attenuates beta/R^2 and widens the Sharpe CI. Quantified via
                  the entry-shift row.
Ledger .......... research-only screen, NO walk-forward gauntlet run -> NO
                  append to var/experiments.jsonl (zoo_screen protocol);
                  disclosed in the report. Ledger stays N=102.
================================================================================

Usage:  uv run python scripts/probe_intraday_mom.py
Writes: data/research/intraday_probe/mom/{mom_result.json, panel_<SYM>.parquet}
"""
# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LAKE = _ROOT / "data" / "research" / "intraday_probe" / "lake" / "alpaca_1min_full"
OUT = _ROOT / "data" / "research" / "intraday_probe" / "mom"
OUT.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["SPY", "QQQ", "IWM", "TLT"]
VARIANTS = ["first30_only", "overnight_first30"]
ONE_WAY_BPS_COMMITTED = 6.0   # configs/managed_futures.yaml: 1 + 3 + 2
ONE_WAY_BPS_REALISTIC = 1.0   # SPY/QQQ microstructure sensitivity (disclosed, not headline)
NW_LAGS = 5
TRADING_DAYS = 252.0
INIT_CASH = 50_000.0
MAX_OVERNIGHT_GAP_DAYS = 4
PERIODS = {
    "paper_window_1993_2013": (None, None),  # sentinel: unavailable locally
    "postpub_2019_2022": ("2019-01-01", "2022-12-31"),
    "recent_2023_2026": ("2023-01-01", "2026-12-31"),
    "full_local": ("2020-07-27", "2026-12-31"),
}


# ---------------------------------------------------------------------------
# panel construction
# ---------------------------------------------------------------------------

def load_minute(sym: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(LAKE / f"{sym}_*.parquet")))
    if not fs:
        raise FileNotFoundError(f"no lake files for {sym}")
    df = pd.concat([pd.read_parquet(f, columns=["t", "open", "close"]) for f in fs])
    df = df.sort_values("t").drop_duplicates("t")
    et = df["t"].dt.tz_convert("America/New_York")
    df["day"] = et.dt.date
    df["hm"] = et.dt.hour * 60 + et.dt.minute
    # regular session, bars stamped at START: [09:30, 16:00) ET
    return df[(df["hm"] >= 570) & (df["hm"] < 960)].reset_index(drop=True)


def _mark(df: pd.DataFrame, lo: int, hi: int, col: str, which: str) -> pd.Series:
    m = df[(df["hm"] >= lo) & (df["hm"] < hi)]
    g = m.groupby("day")[col]
    return g.first() if which == "first" else g.last()


def build_panel(sym: str) -> pd.DataFrame:
    df = load_minute(sym)
    p = pd.DataFrame({
        "o0930": _mark(df, 570, 573, "open", "first"),
        "c0959": _mark(df, 595, 600, "close", "last"),
        "c1529": _mark(df, 925, 930, "close", "last"),
        "entry1531": _mark(df, 931, 935, "open", "first"),
        "entry1532": _mark(df, 932, 936, "open", "first"),   # entry-shift robustness
        "c1559": _mark(df, 955, 960, "close", "last"),
        "sess_close": df.groupby("day")["close"].last(),
        "last_hm": df.groupby("day")["hm"].last(),
        "n_bars": df.groupby("day")["close"].size(),
    })
    p.index = pd.to_datetime(p.index)
    p = p.sort_index()
    p["prev_close"] = p["sess_close"].shift(1)
    p["prev_gap_days"] = (p.index.to_series().diff().dt.days)
    p["half_day"] = p["last_hm"] < 945  # last regular bar before 15:45 ET
    # signals (fixed at ~10:00)
    p["r1_first30_only"] = p["c0959"] / p["o0930"] - 1.0
    p["r1_overnight_first30"] = np.where(
        p["prev_gap_days"] <= MAX_OVERNIGHT_GAP_DAYS,
        p["c0959"] / p["prev_close"] - 1.0, np.nan)
    # regression target (descriptive)
    p["r13"] = np.where(~p["half_day"], p["c1559"] / p["c1529"] - 1.0, np.nan)
    # honest tradeable last-half-hour returns (entry 15:31+ open, exit ~16:00 close)
    p["r_trade"] = np.where(~p["half_day"], p["c1559"] / p["entry1531"] - 1.0, np.nan)
    p["r_trade_shift"] = np.where(~p["half_day"], p["c1559"] / p["entry1532"] - 1.0, np.nan)
    return p


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------

def ols_nw(x: np.ndarray, y: np.ndarray, lags: int = NW_LAGS) -> dict:
    """OLS y = a + b x with Newey-West (Bartlett) HAC t-stat on b."""
    n = len(x)
    if n < 30:
        return {"n": n, "beta": np.nan, "t_nw": np.nan, "r2": np.nan}
    xm = x - x.mean()
    ym = y - y.mean()
    sxx = float(np.sum(xm * xm))
    if sxx <= 0:
        return {"n": n, "beta": np.nan, "t_nw": np.nan, "r2": np.nan}
    beta = float(np.sum(xm * ym) / sxx)
    resid = ym - beta * xm
    u = xm * resid
    s = float(np.sum(u * u))
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        s += 2.0 * w * float(np.sum(u[lag:] * u[:-lag]))
    var_b = s / (sxx * sxx)
    t = beta / math.sqrt(var_b) if var_b > 0 else np.nan
    ss_tot = float(np.sum(ym * ym))
    r2 = 1.0 - float(np.sum(resid * resid)) / ss_tot if ss_tot > 0 else np.nan
    return {"n": n, "beta": beta, "t_nw": t, "r2": r2}


def sharpe252(r: np.ndarray) -> float:
    if len(r) < 30 or np.std(r, ddof=1) == 0:
        return float("nan")
    return float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(TRADING_DAYS))


def eval_cell(p: pd.DataFrame, variant: str, lo: str, hi: str) -> dict:
    """All pre-registered stats for one symbol x variant x period."""
    from scipy.stats import spearmanr

    d = p.loc[lo:hi]
    sig = d[f"r1_{variant}"]
    # --- regression / association block (r13, the paper's object) ---
    reg_df = pd.DataFrame({"x": sig, "y": d["r13"]}).dropna()
    reg = ols_nw(reg_df["x"].to_numpy(float), reg_df["y"].to_numpy(float))
    ic = float(spearmanr(reg_df["x"], reg_df["y"]).statistic) if len(reg_df) >= 30 else float("nan")
    nz = reg_df[reg_df["x"] != 0]
    hit = float((np.sign(nz["x"]) * nz["y"] > 0).mean()) if len(nz) >= 30 else float("nan")
    # --- honest strategy block (entry 15:31+, exit ~close) ---
    st = pd.DataFrame({"sig": sig, "rt": d["r_trade"], "rts": d["r_trade_shift"]}).dropna(subset=["sig", "rt"])
    st = st[st["sig"] != 0]
    pos = np.sign(st["sig"].to_numpy(float))
    gross = pos * st["rt"].to_numpy(float)
    net6 = gross - 2 * ONE_WAY_BPS_COMMITTED * 1e-4
    net1 = gross - 2 * ONE_WAY_BPS_REALISTIC * 1e-4
    sh = st.dropna(subset=["rts"])
    gross_shift = np.sign(sh["sig"].to_numpy(float)) * sh["rts"].to_numpy(float)
    return {
        "n_reg": reg["n"], "beta": _r(reg["beta"], 4), "t_nw5": _r(reg["t_nw"], 2),
        "r2": _r(reg["r2"], 4), "spearman_ic": _r(ic, 3), "hit_rate": _r(hit, 3),
        "n_traded": int(len(st)),
        "gross_mean_bps": _r(float(np.mean(gross)) * 1e4, 2) if len(st) else None,
        "net_mean_bps_6bp": _r(float(np.mean(net6)) * 1e4, 2) if len(st) else None,
        "net_mean_bps_1bp": _r(float(np.mean(net1)) * 1e4, 2) if len(st) else None,
        "sharpe252_gross": _r(sharpe252(gross), 2),
        "sharpe252_net_6bp": _r(sharpe252(net6), 2),
        "sharpe252_net_1bp": _r(sharpe252(net1), 2),
        "entryshift_gross_mean_bps": _r(float(np.mean(gross_shift)) * 1e4, 2) if len(sh) else None,
        "_net6_series": pd.Series(net6, index=st.index),
    }


def _r(v, k):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), k)


def blessed_block(net6: pd.Series, n_variants_total: int) -> dict:
    """Blessed summarize() + DSR on the committed-cost net daily series (full period)."""
    from alphaforge.analytics.metrics import summarize
    from alphaforge.validation.dsr import dsr_from_returns

    if len(net6) < 60:
        return {"note": "too few traded days for blessed block"}
    eq = INIT_CASH * (1.0 + net6).cumprod()
    ms = pd.DatetimeIndex(eq.index).to_numpy(dtype="datetime64[ms]").astype("int64")
    eq_ms = pd.Series(eq.to_numpy(float), index=pd.Index(ms, name="ts"), name="equity")
    out: dict = {}
    try:
        summ = summarize(eq_ms)
        out["sharpe_blessed_A365"] = _r(float(summ.sharpe), 2)
        out["max_dd"] = _r(float(summ.max_dd), 4)
        out["note_blessed"] = "A=365 daily-resample convention (live-sleeve comparable; ~1.20x the honest 252 number)"
    except Exception as e:  # noqa: BLE001
        out["sharpe_blessed_A365"] = None
        out["note_blessed"] = f"summarize failed: {str(e)[:80]}"
    try:
        fresh = dsr_from_returns(net6, 2, 1.0, TRADING_DAYS)
        defl = dsr_from_returns(net6, max(2, n_variants_total), 1.0, TRADING_DAYS)
        out["psr"] = _r(float(fresh.psr), 3)
        out["dsr_fresh_trial"] = _r(float(fresh.dsr), 3)
        out[f"dsr_deflated_{n_variants_total}configs"] = _r(float(defl.dsr), 3)
        out["skew"] = _r(float(fresh.skew), 2)
        out["kurtosis_nonexcess"] = _r(float(fresh.kurtosis), 1)
    except Exception as e:  # noqa: BLE001
        out["dsr_fresh_trial"] = None
        out["note_dsr"] = f"dsr failed: {str(e)[:80]}"
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    n_configs = len(SYMBOLS) * len(VARIANTS)  # 8 — honest deflation count for this screen
    result: dict = {
        "probe": "TRACK_B_STEP3_jfe_intraday_momentum",
        "paper": "Gao-Han-Li-Zhou 2018 JFE 'Market intraday momentum' (r1 -> r13)",
        "data": "Alpaca IEX 1-min lake 2020-07-27+ (data/research/intraday_probe/lake/alpaca_1min_full)",
        "costs_headline": f"{ONE_WAY_BPS_COMMITTED}bp one-way committed (configs/managed_futures.yaml) = {2*ONE_WAY_BPS_COMMITTED}bp round-trip/day",
        "costs_sensitivity": f"{ONE_WAY_BPS_REALISTIC}bp one-way (SPY/QQQ microstructure, disclosed NOT headline) + gross",
        "fill_honesty": "signal fixed 10:00; entry = open of first bar in [15:31,15:35) ET; exit = close of last bar in [15:55,16:00) ET (IEX proxy for the auction close, ~1bp mark noise); no same-bar fills",
        "annualization": "honest sqrt(252) on one-bet-per-day returns over TRADED days; in-market ~29 min/day",
        "paper_window_1993_2013": "NOT COVERABLE with free local data (lake starts 2020-07-27) — deferred to QC cloud bundle (qc_bundle/research_intraday_probe.py CELL 2); the local answer covers post-publication decay only",
        "ledger": "research-only screen, no WF gauntlet -> no var/experiments.jsonl append (zoo_screen protocol); ledger stays N=102",
        "n_configs_evaluated": n_configs,
        "symbols": {},
    }
    for sym in SYMBOLS:
        print(f"building panel {sym} ...")
        p = build_panel(sym)
        p.to_parquet(OUT / f"panel_{sym}.parquet")
        n_half = int(p["half_day"].sum())
        span = f"{p.index.min().date()}..{p.index.max().date()}"
        sym_out: dict = {
            "span": span, "n_sessions": int(len(p)), "n_half_days_dropped": n_half,
            "marks_coverage_pct": _r(100.0 * float(p[["o0930", "c0959", "c1529", "entry1531", "c1559"]].dropna().shape[0]) / max(1, len(p)), 1),
            "variants": {},
        }
        for variant in VARIANTS:
            v_out: dict = {}
            for pname, (lo, hi) in PERIODS.items():
                if lo is None:
                    v_out[pname] = "UNAVAILABLE locally — deferred to QC bundle"
                    continue
                cell = eval_cell(p, variant, lo, hi)
                net6 = cell.pop("_net6_series")
                if pname == "full_local":
                    cell["blessed"] = blessed_block(net6, n_configs)
                v_out[pname] = cell
            sym_out["variants"][variant] = v_out
        result["symbols"][sym] = sym_out

    (OUT / "mom_result.json").write_text(json.dumps(result, indent=2))

    # ---------------- printed decay table ----------------
    print("\n========== JFE INTRADAY MOMENTUM — REPLICATION (free IEX lake, 2020-07+) ==========")
    print(f"costs headline: {2*ONE_WAY_BPS_COMMITTED:.0f}bp round-trip/day (committed) | sensitivity {2*ONE_WAY_BPS_REALISTIC:.0f}bp | gross")
    hdr = f"{'sym':4s} {'variant':18s} {'period':22s} {'n':>5s} {'beta':>8s} {'t_NW5':>6s} {'IC':>6s} {'hit':>6s} {'gross':>7s} {'net6bp':>7s} {'SR_g':>6s} {'SR_n6':>6s} {'SR_n1':>6s}"
    print(hdr)
    print("-" * len(hdr))
    for sym, s in result["symbols"].items():
        for variant, v in s["variants"].items():
            for pname, c in v.items():
                if isinstance(c, str):
                    print(f"{sym:4s} {variant:18s} {pname:22s}   -- {c}")
                    continue
                print(f"{sym:4s} {variant:18s} {pname:22s} {c['n_traded']:5d} "
                      f"{_f(c['beta'],8,4)} {_f(c['t_nw5'],6,2)} {_f(c['spearman_ic'],6,3)} {_f(c['hit_rate'],6,3)} "
                      f"{_f(c['gross_mean_bps'],7,2)} {_f(c['net_mean_bps_6bp'],7,2)} "
                      f"{_f(c['sharpe252_gross'],6,2)} {_f(c['sharpe252_net_6bp'],6,2)} {_f(c['sharpe252_net_1bp'],6,2)}")
        print("-" * len(hdr))
    print(f"artifacts: {OUT}")
    print("ledger: screen only, NO experiments.jsonl append (N stays 102)")
    return 0


def _f(v, w, k):
    return f"{v:{w}.{k}f}" if isinstance(v, (int, float)) and v is not None else " " * (w - 2) + "--"


if __name__ == "__main__":
    raise SystemExit(main())
