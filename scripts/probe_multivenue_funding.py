#!/usr/bin/env python3
"""PROBE — CANDIDATE 3: multi-venue funding AGGREGATION as a better carry SIGNAL.
PRE-REGISTERED 2026-07-19, written BEFORE any A/B number was computed.

QUESTION. The LIVE crypto-carry sleeve trades carry_fund_21 built from BINANCE-only
funding. Does aggregating funding across venues (Binance + Bybit, + Hyperliquid from
2023-05) into the SAME trailing-carry signal improve the sleeve — i.e. is cross-venue
funding a less noisy estimate of the true basis the sleeve harvests? Execution stays
on Binance in BOTH arms (funding PnL is always credited from Binance rates); ONLY the
signal changes. Secondary: is BEST-VENUE funding harvesting worth anything net of the
4 taker fee legs of a two-venue arb (expect NO, per the critic).

THIS IS A RESEARCH SCREEN (self-contained replica of the sleeve's construction, not
the engine WalkForwardRunner). Per the ledger rules it does NOT append to
var/experiments.jsonl; this docstring + the result JSON are the disclosure. A full
engine walk-forward trial is queued ONLY if the pre-registered promote rule fires.

DATA (all owned/backfilled before this spec was finalized; no peeking at A/B output):
  binance ..... data/lake/funding (available_at = ts_funding + 300 s, stored PIT).
  bybit ....... data/research/multivenue_funding/bybit/*.parquet (2021-04.., 8 h).
  hyperliquid . data/research/multivenue_funding/hyperliquid/*.parquet (2023-05..,
                1 h cadence — the honest 8h/1h alignment is defined below).
  okx ......... data/research/multivenue_funding/okx/*.parquet — server DEPTH-CAPPED
                at ~3 months (verified) => EXCLUDED from the A/B panel; used ONLY in
                the cross-venue spread snapshot.
  prices ...... data/lake/ohlcv (1 h bars, close + quote_volume), Binance.
  universe .... the 58 perps that entered the blessed crypto_carry_wk walk-forward
                (artifacts/walkforward/crypto_carry_wk/walkforward.json).

PUBLICATION-LAG CONVENTION (symmetric, conservative): a settlement at ts is usable at
decision time t iff ts + 300 s <= t, for EVERY venue in BOTH arms (mirrors the lake's
stored available_at lag; backfilled venues get the same +300 s).

INTERVAL ALIGNMENT (honest 8h/1h): per venue x instrument, each settlement's rate is
annualized by 8760 / gap_h where gap_h = hours since that venue's previous settlement
(clipped to [0.9, 12] h; first settlement dropped). A venue's carry estimate at t is
the mean ANNUALIZED rate over the trailing 7 CALENDAR days, valid only if the venue
published >= 60% of its expected settlements in that window (expected = 168 h /
median gap). Hourly Hyperliquid thus contributes ~168 points to the same 7-day
horizon that gives an 8 h venue ~21 — same window, no cadence distortion.

ARMS (identical universe, construction, costs, funding credit — signal is the ONLY
difference):
  A  binance_21s .. blessed-replica carry_fund_21: -(mean of last 21 raw Binance
                    rates) * 8760 / median(gap of those 21). Control.
  A7 binance_7d ... -(trailing 7-day mean annualized Binance rate). Windowing
                    control: isolates calendar-window effects from venue breadth.
  B  agg_eq ....... -(equal-weight mean over qualifying venues of the trailing
                    7-day mean annualized rate). Primary treatment. Falls back to
                    Binance-only where other venues don't list/qualify (keeps the
                    universe identical across arms). OI-weighting was pre-registered
                    as an alternative but is DROPPED: historical cross-venue OI is
                    not freely backfillable and Binance fapi is unreachable from this
                    network even for a snapshot — disclosed, not silently skipped.

SLEEVE REPLICA (mirrors the blessed crypto_carry_wk config; simplifications
disclosed): hourly grid; rebalance every 168 h at epoch-anchored stamps
(ts % 604 800 000 ms == 0, i.e. Thursday 00:00 UTC — the blessed epoch anchor);
universe re-selected at the first rebalance stamp of each UTC month as the PIT
top-20 of the 58 by trailing 30-day summed quote_volume (>= 30 d history; no
entry-16/exit-26 hysteresis — disclosed simplification, identical in both arms);
rank allocator replica: long top-k / short bottom-k of the signal with
k = min(10, n_eligible // 4) (= 5 at n = 20), inverse-vol weights (trailing 720 h
hourly-return std, annualized), union-normalized to gross 0.5 (half of gross_max 1.0),
clipped at w_max 0.15, renormalized capped — the engine's RankInverseVol path;
eligibility = in universe AND arm-A signal exists AND priced at t (arm-A eligibility
applied to ALL arms so the cross-sections are identical).
  Fills/leakage: weights decided at close t fill at close t+1; first earned return
is close t+1 -> t+2 (held = target.shift(2) on the hourly grid; no same-bar fills).
  Costs (committed, configs/base.yaml): taker 5.0 + half-spread 2.5 + latency 2.0
= 9.5 bp one-way on turnover, charged on the fill bar.
  Funding credit: position held during the bar ending at a Binance settlement pays
-w * rate (longs pay positive funding) — BOTH arms settle on BINANCE rates because
execution stays on Binance.
  Overlay: purged walk-forward vol-target on daily-resampled net returns (train 252 d
/ test 63 d / embargo 7 d, mirroring the blessed leg cadence; the strategy has no
other fitted parameter, so stitched OOS Sharpe/DSR are effectively pure-OOS).

METRICS. Blessed machinery only: alphaforge.analytics.metrics.summarize (net Sharpe,
vol, maxDD, 365 d/yr) on the OOS equity curve + alphaforge.validation.dsr
.dsr_from_returns. n_trials for deflation = 4 (A, A7, B, and the spread-harvest
screen — everything this probe evaluates). Paired test: weekly-block bootstrap
(2000 draws) of mean(daily B - daily A). Subperiods reported: full span,
pre-2023-05 (2-venue era), post-2023-05 (3-venue era).

SPREAD ANALYSIS (secondary, descriptive):
  deep panel (Binance vs Bybit 2021-04.., + HL where present): distribution of the
  annualized 7-day-mean funding spread per instrument (median / p75 / p90 / p95 of
  |spread|), cross-venue correlation of annualized funding, and sign-persistence of
  the cheaper-venue identity at the 8 h horizon.
  snapshot (last ~90 d, + OKX): mean best-venue-minus-Binance annualized carry pickup
  and the breakeven holding period vs 4 taker legs (4 x 7.5 bp = 30 bp round trip);
  verdict = harvestable only if median pickup x realistic hold >> 30 bp.

PRE-REGISTERED DECISION RULE (locked before computing):
  PROMOTE to a full engine walk-forward trial iff ALL of
    (1) Sharpe(B) - Sharpe(A) >= +0.10 on the full-span OOS curve,
    (2) block-bootstrap P(mean daily B-A > 0) >= 0.90,
    (3) Sharpe(B) - Sharpe(A7) >= +0.05 (venue information beyond windowing).
  Anything else = HONEST NULL (a full success; no tuning, no variant search beyond
  the four pre-registered evaluations above).

Usage:  uv run python scripts/probe_multivenue_funding.py
Artifacts -> artifacts/sweep/multivenue_funding/
"""
# ruff: noqa: E501
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LAKE = _ROOT / "data" / "lake"
MV = _ROOT / "data" / "research" / "multivenue_funding"
OUT = _ROOT / "artifacts" / "sweep" / "multivenue_funding"
OUT.mkdir(parents=True, exist_ok=True)

WEEK_MS = 168 * 3600 * 1000
LAG_MS = 300_000                      # +5 min publication lag, every venue, both arms
ONE_WAY_BPS = 5.0 + 2.5 + 2.0         # taker + half-spread + latency (configs/base.yaml)
W_MAX = 0.15
GROSS_TARGET = 0.5                    # engine rank book: half of gross_max 1.0
VOL_LOOKBACK_H = 720
VOL_TARGET_ANN = 0.15
UNIVERSE_N = 20
MIN_HISTORY_D = 30
WINDOW_D = 7                          # trailing carry window (calendar days)
MIN_COVERAGE = 0.60                   # venue must publish >=60% of expected settlements
N_TRIALS_DSR = 4
HOURS_PER_YEAR = 8760.0

START = pd.Timestamp("2021-05-01")


def sleeve_symbols() -> list[str]:
    wf = json.loads((_ROOT / "artifacts/walkforward/crypto_carry_wk/walkforward.json").read_text())
    return [i.split(":")[-1] for i in wf["config"]["instrument_ids"]]


# ------------------------------------------------------------------ data loading
def load_ohlcv(sym: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(LAKE / f"ohlcv/instrument_id=BINANCE:PERP:{sym}/**/*.parquet"), recursive=True))
    if not fs:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f, columns=["ts_open", "close", "quote_volume"]) for f in fs])
    df["ts"] = pd.to_datetime(df["ts_open"]).dt.tz_localize(None)
    df = df.sort_values("ts").drop_duplicates("ts", keep="last")
    return df[df["ts"] >= START - pd.Timedelta(days=45)][["ts", "close", "quote_volume"]]


def load_binance_funding(sym: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(LAKE / f"funding/instrument_id=BINANCE:PERP:{sym}/**/*.parquet"), recursive=True))
    if not fs:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f, columns=["ts_funding", "rate"]) for f in fs])
    df["ts_funding"] = pd.to_datetime(df["ts_funding"]).dt.tz_localize(None)
    df = df.sort_values("ts_funding").drop_duplicates("ts_funding", keep="last")
    return df[df["ts_funding"] >= START - pd.Timedelta(days=21)].reset_index(drop=True)


def load_venue_funding(venue: str, sym: str) -> pd.DataFrame:
    fp = MV / venue / f"{sym}.parquet"
    if not fp.exists():
        return pd.DataFrame()
    df = pd.read_parquet(fp)
    if df.empty:
        return df
    df["ts_funding"] = pd.to_datetime(df["ts_funding"], unit="ms")
    return df.sort_values("ts_funding").drop_duplicates("ts_funding", keep="last")[["ts_funding", "rate"]].reset_index(drop=True)


# ------------------------------------------------------------- signal machinery
def annualized_settlements(f: pd.DataFrame) -> pd.DataFrame:
    """Per-settlement annualized rate: rate * 8760 / gap_h (gap clipped [0.9, 12])."""
    if f.empty or len(f) < 2:
        return pd.DataFrame(columns=["ts_funding", "rate", "ann", "gap_h"])
    g = f.copy()
    g["gap_h"] = g["ts_funding"].diff().dt.total_seconds() / 3600.0
    g = g.dropna(subset=["gap_h"])
    g = g[(g["gap_h"] >= 0.9) & (g["gap_h"] <= 12.0)]
    g["ann"] = g["rate"] * (HOURS_PER_YEAR / g["gap_h"])
    return g[["ts_funding", "rate", "ann", "gap_h"]].reset_index(drop=True)


def signal_at_stamps(f: pd.DataFrame, stamps: pd.DatetimeIndex, mode: str) -> pd.Series:
    """Carry signal (positive = long earns) at each rebalance stamp, PIT.

    mode='21s' : blessed replica, -(mean last 21 raw rates) * 8760/median(gap of 21)
    mode='7d'  : -(mean annualized rate over trailing 7 calendar days), coverage-gated
    """
    out = pd.Series(np.nan, index=stamps)
    if f.empty:
        return out
    a = annualized_settlements(f)
    if a.empty:
        return out
    avail = a["ts_funding"] + pd.Timedelta(milliseconds=LAG_MS)
    ts = a["ts_funding"].to_numpy()
    for t in stamps:
        m = avail <= t
        if mode == "21s":
            idx = np.flatnonzero(m.to_numpy())
            if len(idx) < 21:
                continue
            last = a.iloc[idx[-21:]]
            interval = float(np.median(last["gap_h"]))
            out[t] = -float(last["rate"].mean()) * (HOURS_PER_YEAR / interval)
        else:
            lo = t - pd.Timedelta(days=WINDOW_D)
            mm = m.to_numpy() & (ts > np.datetime64(lo))
            if not mm.any():
                continue
            w = a.loc[mm]
            expected = 168.0 / float(np.median(w["gap_h"]))
            if len(w) < MIN_COVERAGE * expected:
                continue
            out[t] = -float(w["ann"].mean())
    return out


# ------------------------------------------------------------ portfolio replica
def rank_book(sig: pd.Series, vol_ann: pd.Series) -> pd.Series | None:
    """Engine RankInverseVol replica: top-k/bottom-k, inv-vol, gross 0.5, cap 0.15."""
    s = sig.dropna()
    v = vol_ann.reindex(s.index)
    s = s[v.notna() & (v > 0)]
    v = v[s.index]
    n = len(s)
    if n < 2:
        return None
    k = max(1, min(10, n // 4))
    order = s.sort_values(ascending=False, kind="stable").index
    w = pd.Series(0.0, index=s.index)
    w[order[:k]] = 1.0 / v[order[:k]]
    w[order[-k:]] = -1.0 / v[order[-k:]]
    gross = w.abs().sum()
    if gross == 0:
        return None
    w *= GROSS_TARGET / gross
    w = w.clip(-W_MAX, W_MAX)
    gc, ma = w.abs().sum(), w.abs().max()
    if gc > 0 and ma > 0:
        w *= min(GROSS_TARGET / gc, W_MAX / ma)
    return w


def run_arm(name: str, sig_stamps: pd.DataFrame, ret: pd.DataFrame, vol_ann: pd.DataFrame,
            fund_flow: pd.DataFrame, members: pd.DataFrame, stamps: pd.DatetimeIndex,
            elig_mask: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Hourly net return series for one arm. elig_mask (stamps x syms) is shared."""
    grid = ret.index
    target = pd.DataFrame(0.0, index=stamps, columns=ret.columns)
    turnover_at = pd.Series(0.0, index=stamps)
    prev = pd.Series(0.0, index=ret.columns)
    n_reb, breadth = 0, []
    for t in stamps:
        elig = elig_mask.loc[t]
        elig_syms = elig[elig].index
        if len(elig_syms) < 6:
            target.loc[t] = prev  # hold
            continue
        w = rank_book(sig_stamps.loc[t, elig_syms], vol_ann.loc[t, elig_syms])
        if w is None:
            target.loc[t] = prev
            continue
        full = pd.Series(0.0, index=ret.columns)
        full[w.index] = w.values
        target.loc[t] = full
        turnover_at[t] = float((full - prev).abs().sum())
        prev = full
        n_reb += 1
        breadth.append(len(w[w != 0]))
    # expand weekly targets to the hourly grid, then leak-lag by 2 bars (fill at t+1)
    daily_w = target.reindex(grid, method="ffill").fillna(0.0)
    held = daily_w.shift(2).fillna(0.0)
    gross_ret = (held * ret.fillna(0.0)).sum(axis=1)
    funding_pnl = (held * fund_flow.reindex(grid).fillna(0.0)).sum(axis=1)
    cost = turnover_at.reindex(grid).fillna(0.0).shift(1).fillna(0.0) * (ONE_WAY_BPS * 1e-4)
    net = gross_ret + funding_pnl - cost
    stats = {"n_rebalances": n_reb, "avg_breadth": float(np.mean(breadth)) if breadth else 0.0,
             "avg_weekly_turnover": float(turnover_at[turnover_at > 0].mean()) if (turnover_at > 0).any() else 0.0,
             "funding_share_of_pnl": float(funding_pnl.sum() / net.sum()) if net.sum() != 0 else float("nan")}
    return net, stats


def purged_wf_voltarget(net_d: pd.Series, train=252, test=63, embargo=7) -> pd.Series:
    r = net_d.to_numpy(float)
    n = len(r)
    idx = net_d.index
    oos = pd.Series(dtype=float)
    start = 0
    while start + train + embargo + test <= n:
        tr = r[start:start + train]
        te_lo = start + train + embargo
        te = r[te_lo:te_lo + test]
        sd = np.std(tr, ddof=1)
        kk = float(np.clip((VOL_TARGET_ANN / (sd * np.sqrt(365.0))) if sd > 0 else 0.0, 0.0, 3.0))
        oos = pd.concat([oos, pd.Series(te * kk, index=idx[te_lo:te_lo + test])])
        start += test
    return oos


def equity_ms(net: pd.Series, init: float = 100_000.0) -> pd.Series:
    eq = init * (1.0 + net).cumprod()
    ms = pd.DatetimeIndex(eq.index).to_numpy(dtype="datetime64[ms]").astype("int64")
    return pd.Series(eq.to_numpy(float), index=pd.Index(ms, name="ts"), name="equity")


def block_bootstrap_pvalue(diff_d: pd.Series, n_draws: int = 2000, block_d: int = 7, seed: int = 7) -> float:
    """P(mean daily diff > 0) under weekly-block resampling."""
    x = diff_d.dropna().to_numpy(float)
    if len(x) < 60:
        return float("nan")
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(x) / block_d))
    starts = rng.integers(0, max(1, len(x) - block_d), size=(n_draws, nb))
    means = np.empty(n_draws)
    for i in range(n_draws):
        seg = np.concatenate([x[s:s + block_d] for s in starts[i]])[: len(x)]
        means[i] = seg.mean()
    return float((means > 0).mean())


# ---------------------------------------------------------------------- driver
def main() -> int:
    from alphaforge.analytics.metrics import DAYS_PER_YEAR, daily_returns, summarize
    from alphaforge.validation.dsr import dsr_from_returns

    syms = sleeve_symbols()
    print(f"loading {len(syms)} sleeve perps ...")
    px, qv, fund_bn, fund_by, fund_hl = {}, {}, {}, {}, {}
    for s in syms:
        o = load_ohlcv(s)
        if o.empty:
            continue
        px[s] = pd.Series(o["close"].to_numpy(float), index=o["ts"])
        qv[s] = pd.Series(o["quote_volume"].to_numpy(float), index=o["ts"])
        fund_bn[s] = load_binance_funding(s)
        fund_by[s] = load_venue_funding("bybit", s)
        fund_hl[s] = load_venue_funding("hyperliquid", s)
    syms = sorted(px.keys())
    print(f"  priced: {len(syms)} | bybit non-empty: {sum(1 for s in syms if len(fund_by[s]))} | hl non-empty: {sum(1 for s in syms if len(fund_hl[s]))}")

    grid = pd.date_range(START, max(p.index.max() for p in px.values()), freq="1h")
    close = pd.DataFrame({s: px[s].reindex(grid) for s in syms})
    ret = close.pct_change(fill_method=None)
    ret = ret.where(ret.abs() < 0.5)  # guard absurd gap prints
    stamps = pd.DatetimeIndex([t for t in grid if int(t.value // 1_000_000) % WEEK_MS == 0])
    stamps = stamps[stamps >= START + pd.Timedelta(days=MIN_HISTORY_D)]
    print(f"  grid: {len(grid)} h | rebalance stamps: {len(stamps)} (epoch-anchored Thu 00:00 UTC)")

    # trailing vol (annualized) at stamps
    vol_h = ret.rolling(VOL_LOOKBACK_H, min_periods=VOL_LOOKBACK_H // 2).std()
    vol_ann = (vol_h * np.sqrt(HOURS_PER_YEAR)).reindex(stamps)

    # PIT monthly top-20 by trailing 30d quote volume
    qvdf = pd.DataFrame({s: qv[s].reindex(grid) for s in syms})
    # bar labels are OPEN times: shift(1) so the trailing sum uses only bars fully
    # completed by the decision stamp (no same-bar volume in the ranking)
    qv30 = qvdf.rolling(24 * 30, min_periods=24 * 25).sum().shift(1)
    members = pd.DataFrame(False, index=stamps, columns=syms)
    cur: list[str] = []
    seen_month = None
    for t in stamps:
        mkey = (t.year, t.month)
        if mkey != seen_month:
            seen_month = mkey
            row = qv30.loc[:t].iloc[-1].dropna()
            cur = list(row.sort_values(ascending=False).head(UNIVERSE_N).index)
        members.loc[t, cur] = True

    # signals at stamps
    print("building signals (A blessed 21s, A7 window, B multi-venue aggregate) ...")
    sigA = pd.DataFrame({s: signal_at_stamps(fund_bn[s], stamps, "21s") for s in syms})
    sigA7 = pd.DataFrame({s: signal_at_stamps(fund_bn[s], stamps, "7d") for s in syms})
    sigBy = pd.DataFrame({s: signal_at_stamps(fund_by[s], stamps, "7d") for s in syms})
    sigHl = pd.DataFrame({s: signal_at_stamps(fund_hl[s], stamps, "7d") for s in syms})
    sigB = pd.concat([sigA7, sigBy, sigHl]).groupby(level=0).mean()  # equal-weight over venues with data
    sigB = sigB.reindex(index=stamps, columns=syms)
    n_venues = sigA7.notna().astype(int) + sigBy.notna().astype(int) + sigHl.notna().astype(int)

    # shared eligibility: universe member AND arm-A signal AND priced at stamp
    priced = close.reindex(stamps).notna()
    elig = members & sigA.notna() & priced

    # Binance funding flow per hourly bar (rate settling exactly at bar close)
    print("building funding-flow matrix ...")
    fund_flow = pd.DataFrame(0.0, index=grid, columns=syms)
    for s in syms:
        f = fund_bn[s]
        if f.empty:
            continue
        ts = f["ts_funding"].round("h")
        flow = pd.Series(-f["rate"].to_numpy(float), index=ts).groupby(level=0).sum()
        flow = flow[flow.index.isin(grid)]
        fund_flow.loc[flow.index, s] = flow.to_numpy()

    # run arms
    arms = {"A_binance_21s": sigA, "A7_binance_7d": sigA7, "B_agg_eq": sigB}
    nets, arm_stats = {}, {}
    for name, sg in arms.items():
        print(f"running arm {name} ...")
        nets[name], arm_stats[name] = run_arm(name, sg, ret, vol_ann, fund_flow, members, stamps, elig)

    # metrics: daily resample -> purged WF vol target -> blessed summarize/DSR
    result_arms = {}
    daily = {}
    for name, net in nets.items():
        nd = (1.0 + net).resample("1D").prod() - 1.0
        nd = nd[nd.index >= stamps[0]]
        daily[name] = nd
        oos = purged_wf_voltarget(nd)
        eq = equity_ms(oos)
        summ = summarize(eq)
        dr = daily_returns(eq)
        dsr_f = dsr_from_returns(dr, 2, 1.0, DAYS_PER_YEAR)
        dsr_h = dsr_from_returns(dr, N_TRIALS_DSR, 1.0, DAYS_PER_YEAR)
        summ_full = summarize(equity_ms(nd))
        result_arms[name] = {
            "sharpe_oos": round(float(summ.sharpe), 3),
            "sharpe_fullsample_no_overlay": round(float(summ_full.sharpe), 3),
            "dsr_fresh": round(float(dsr_f.dsr), 3),
            "dsr_deflated_4trials": round(float(dsr_h.dsr), 3),
            "psr": round(float(dsr_f.psr), 3),
            "vol_ann": round(float(summ.vol_ann), 3),
            "max_dd": round(float(summ.max_dd), 3),
            "cagr": round(float(summ.cagr), 3),
            "n_oos_days": int(len(dr)),
            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in arm_stats[name].items()},
        }

    # paired deltas (full-sample daily, no overlay: overlay is Sharpe-invariant & shared)
    dA, dA7, dB = daily["A_binance_21s"], daily["A7_binance_7d"], daily["B_agg_eq"]
    j = pd.concat([dA.rename("A"), dA7.rename("A7"), dB.rename("B")], axis=1).dropna()
    diff_BA = j["B"] - j["A"]
    hl_era = j.index >= "2023-05-12"
    def _sh(x: pd.Series) -> float:
        return float(x.mean() / x.std(ddof=1) * np.sqrt(365.0)) if x.std(ddof=1) > 0 else float("nan")
    delta = {
        "sharpe_A_full": _sh(j["A"]), "sharpe_A7_full": _sh(j["A7"]), "sharpe_B_full": _sh(j["B"]),
        "sharpe_delta_B_minus_A": _sh(j["B"]) - _sh(j["A"]),
        "sharpe_delta_B_minus_A7": _sh(j["B"]) - _sh(j["A7"]),
        "corr_A_B": float(j["A"].corr(j["B"])),
        "bootstrap_P_meandiff_gt0": block_bootstrap_pvalue(diff_BA),
        "pre_hl_era": {"days": int((~hl_era).sum()), "sharpe_A": _sh(j.loc[~hl_era, "A"]), "sharpe_B": _sh(j.loc[~hl_era, "B"])},
        "hl_era": {"days": int(hl_era.sum()), "sharpe_A": _sh(j.loc[hl_era, "A"]), "sharpe_B": _sh(j.loc[hl_era, "B"])},
        "avg_n_venues_in_B_signal": float(n_venues[n_venues > 0].mean().mean()),
    }
    delta = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in delta.items()}
    for kk in ("pre_hl_era", "hl_era"):
        delta[kk] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in delta[kk].items()}

    # -------------------------------------------------- spread analyses
    print("spread analysis ...")
    # deep panel: Binance vs Bybit 7d-mean annualized at stamps
    sprd = (sigA7 - sigBy).abs()          # note: signals are -funding; |diff| identical
    sprd = sprd.where(sigA7.notna() & sigBy.notna())
    flat = sprd.stack().dropna()
    both = sigA7.notna() & sigBy.notna()
    # cheaper-venue persistence: venue whose funding is LOWER for a long (higher carry)
    cheaper = (sigA7 > sigBy).where(both)
    switches = (cheaper != cheaper.shift(1)).where(both & both.shift(1)).stack().dropna()
    corr_bn_by = pd.concat([sigA7.stack().rename("bn"), sigBy.stack().rename("by")], axis=1).dropna()
    deep = {
        "n_obs_instrument_weeks": int(len(flat)),
        "abs_spread_ann_median": round(float(flat.median()), 4),
        "abs_spread_ann_p75": round(float(flat.quantile(0.75)), 4),
        "abs_spread_ann_p90": round(float(flat.quantile(0.90)), 4),
        "abs_spread_ann_p95": round(float(flat.quantile(0.95)), 4),
        "corr_binance_bybit_ann_funding": round(float(corr_bn_by["bn"].corr(corr_bn_by["by"])), 4),
        "cheaper_venue_weekly_switch_rate": round(float(switches.mean()), 4),
    }
    # snapshot (last 90d incl. OKX): best-venue pickup vs Binance at 8h settlements
    snap_rows = []
    t_hi = grid.max()
    t_lo = t_hi - pd.Timedelta(days=90)
    for s in syms:
        vens = {"binance": fund_bn[s], "bybit": fund_by[s], "okx": load_venue_funding("okx", s), "hyperliquid": fund_hl[s]}
        anns = {}
        for v, f in vens.items():
            a = annualized_settlements(f)
            if a.empty:
                continue
            a = a[(a["ts_funding"] >= t_lo) & (a["ts_funding"] <= t_hi)]
            if len(a) < 10:
                continue
            anns[v] = float(a["ann"].mean())
        if "binance" not in anns or len(anns) < 2:
            continue
        # for a SHORT perp (collecting positive funding) best venue = max funding;
        # measure |best - binance| pickup for the side you'd actually run per name
        best_abs = max(anns.values(), key=abs)
        snap_rows.append({"symbol": s, "n_venues": len(anns), **{f"ann_{v}": round(x, 5) for v, x in anns.items()},
                          "max_minus_min_ann": round(max(anns.values()) - min(anns.values()), 5),
                          "best_abs_minus_binance_abs_ann": round(abs(best_abs) - abs(anns["binance"]), 5)})
    snap_df = pd.DataFrame(snap_rows)
    rt_cost = 4 * (5.0 + 2.5) * 1e-4  # 4 taker legs of a two-venue arb = 30 bp round trip
    med_gap = float(snap_df["max_minus_min_ann"].median()) if len(snap_df) else float("nan")
    snapshot = {
        "window": f"{t_lo.date()}..{t_hi.date()}",
        "n_symbols": int(len(snap_df)),
        "median_max_minus_min_ann": round(med_gap, 4) if med_gap == med_gap else None,
        "median_best_pickup_vs_binance_ann": round(float(snap_df["best_abs_minus_binance_abs_ann"].median()), 4) if len(snap_df) else None,
        "four_leg_roundtrip_cost": rt_cost,
        "breakeven_hold_days_at_median_gap": round(rt_cost / med_gap * 365.0, 1) if med_gap and med_gap > 0 else None,
    }

    # -------------------------------------------------- verdict (pre-registered rule)
    d_sh_BA = result_arms["B_agg_eq"]["sharpe_oos"] - result_arms["A_binance_21s"]["sharpe_oos"]
    d_sh_BA7 = result_arms["B_agg_eq"]["sharpe_oos"] - result_arms["A7_binance_7d"]["sharpe_oos"]
    p_boot = delta["bootstrap_P_meandiff_gt0"]
    promote = bool(d_sh_BA >= 0.10 and (p_boot == p_boot and p_boot >= 0.90) and d_sh_BA7 >= 0.05)
    verdict = "PROMOTE_TO_FULL_WF" if promote else "NULL"

    result = {
        "probe": "multivenue_funding_aggregation_candidate3",
        "date": "2026-07-19",
        "ledger_disclosure": "RESEARCH SCREEN (self-contained sleeve replica, 3 arms + spread screen = 4 pre-registered evaluations); NOT appended to var/experiments.jsonl per ledger rules; full engine WF only on PROMOTE.",
        "okx_data_finding": "OKX public funding-rate-history is depth-capped at ~3 months => excluded from the A/B panel, used only in the spread snapshot.",
        "arms": result_arms,
        "paired_delta": delta,
        "spread_deep_binance_bybit": deep,
        "spread_snapshot_90d_all_venues": snapshot,
        "decision_rule": "PROMOTE iff dSharpe(B-A)>=0.10 AND bootP>=0.90 AND dSharpe(B-A7)>=0.05",
        "verdict": verdict,
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2))
    pd.DataFrame(daily).to_parquet(OUT / "ab_daily_returns.parquet")
    if len(snap_df):
        snap_df.to_parquet(OUT / "spread_snapshot.parquet")
    sprd.to_parquet(OUT / "spread_deep_weekly_abs.parquet")

    print("\n================ CANDIDATE 3 — MULTI-VENUE FUNDING AGGREGATION ================")
    print(json.dumps(result, indent=2))
    print("artifacts:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
