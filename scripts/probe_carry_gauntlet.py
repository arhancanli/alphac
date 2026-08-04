#!/usr/bin/env python3
"""PROBE — cross-sectional COMMODITY / CROSS-ASSET CARRY gauntlet (LEAD 1).

Self-contained, PIT, leak-free cross-sectional carry backtest on the REAL-futures
universe (data/lake_fut_real), run through the SAME deflated-Sharpe machinery the
sleeves use (alphaforge.analytics.metrics.summarize + alphaforge.validation.dsr) so
the number is directly comparable to the crypto / equity / managed-futures sleeves.

Why self-contained (not the WalkForwardRunner): the carry SIGNAL lives in a side
parquet (carry_termstructure.parquet: front/next contract marks) that the feature
engine / lake reader does not natively read, and there is no lake_fut_real profile.
Per the LEAD-1 brief this is the sanctioned fallback — but it imports the BLESSED
cost schedule (configs/managed_futures.yaml frictions), the BLESSED summarize() (net
Sharpe / vol / maxDD, DAYS_PER_YEAR annualization) and the BLESSED dsr_from_returns()
so it is honest and comparable. NOTHING in src/ or existing scripts is modified.

Signal .......... carry_i = (front_i - next_i) / next_i * 365 / gap_days   (raw marks)
                  front>next = backwardation = positive carry = LONG.
Return .......... close-to-close of the rebased continuous index (roll-adjusted),
                  data/lake_fut_real/ohlcv_1d (open==close: a daily mark).
Leak control .... signal at close t -> fill at NEXT bar (t+1 mark) -> weights are
                  shift(2) vs the close-to-close return they earn (no same-bar fill,
                  no look-ahead). Costs deducted on the fill bar.
Portfolio ....... monthly rebalance, cross-sectional z-score of carry, inverse-vol
                  tilt (63d trailing), demeaned (dollar/market-neutral), gross=1,
                  per-name cap. Deflated PURGED walk-forward vol-target overlay
                  (2y train / 6m test / 21d embargo) mirroring mf_gauntlet — note the
                  factor has NO fitted params, so Sharpe/DSR are effectively pure-OOS.
Costs ........... committed managed_futures schedule: commission 1 + half-spread 3 +
                  latency 2 = 6 bp one-way (impact ~0 at a capacity-respecting book).

Usage:  uv run python scripts/probe_carry_gauntlet.py
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

LAKE = _ROOT / "data" / "lake_fut_real"
LAKE_MF = _ROOT / "data" / "lake_mf"
OUT = _ROOT / "artifacts" / "sweep" / "carry_probe"
OUT.mkdir(parents=True, exist_ok=True)

# committed managed_futures frictions (configs/managed_futures.yaml)
ONE_WAY_BPS = 1.0 + 3.0 + 2.0  # commission + half_spread + latency = 6 bp
INIT_CASH = 50_000.0
VOL_TARGET_ANN = 0.15
NAME_CAP = 0.20          # per-name gross cap
MIN_BREADTH = 6          # need a real cross-section to rebalance
VOL_LOOKBACK = 63        # trailing days for inverse-vol + vol-target
STALE_MAX_DAYS = 7       # carry mark must be <= 7 calendar days old at rebalance


def _load_ohlcv(root: str, lake: Path = LAKE) -> pd.Series:
    fs = sorted(glob.glob(str(lake / f"ohlcv_1d/instrument_id=XUSE:CASH:{root}USD/**/*.parquet"), recursive=True))
    if not fs:
        return pd.Series(dtype=float)
    df = pd.concat([pd.read_parquet(f, columns=["ts_open", "close"]) for f in fs])
    df = df.sort_values("ts_open").drop_duplicates("ts_open")
    s = pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["ts_open"]).dt.tz_localize(None))
    return s[~s.index.duplicated(keep="last")]


def build_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (returns DxN, carry-signal DxN) aligned on a common daily grid."""
    carry = pd.read_parquet(LAKE / "carry_termstructure.parquet")
    carry["date"] = pd.to_datetime(carry["date"]).dt.tz_localize(None)
    v = carry.dropna(subset=["front", "next"]).copy()
    v = v[v["gap_days"] > 0]
    v["carry"] = (v["front"] - v["next"]) / v["next"] * 365.0 / v["gap_days"]
    # winsorize extreme carry marks (bad prints) at cross-sectional 1/99 per date later;
    # here clip absurd values (|annualized carry| > 5 = 500%/yr is a data error)
    v = v[v["carry"].abs() < 5.0]
    roots = sorted(v["root"].unique())

    px = {r: _load_ohlcv(r) for r in roots}
    px = {r: s for r, s in px.items() if len(s) > VOL_LOOKBACK + 5}
    roots = sorted(px.keys())
    all_dates = sorted(set().union(*[set(s.index) for s in px.values()]))
    grid = pd.DatetimeIndex(all_dates)

    ret = pd.DataFrame({r: px[r].reindex(grid).pct_change() for r in roots})
    # carry signal panel, forward-filled up to STALE_MAX_DAYS
    sig = pd.DataFrame(index=grid, columns=roots, dtype=float)
    for r in roots:
        cs = v[v["root"] == r].set_index("date")["carry"].sort_index()
        cs = cs[~cs.index.duplicated(keep="last")].reindex(grid)
        # forward-fill but only within STALE_MAX_DAYS
        ff = cs.ffill()
        last_valid = cs.notna().astype(int).replace(0, np.nan)
        age = (pd.Series(grid, index=grid) - pd.Series(grid, index=grid).where(cs.notna()).ffill()).dt.days
        sig[r] = ff.where(age <= STALE_MAX_DAYS)
    return ret, sig


def target_weights(sig_row: pd.Series, ret_hist: pd.DataFrame) -> pd.Series | None:
    """Cross-sectional carry weights on one rebalance date (PIT: ret_hist ends at t)."""
    s = sig_row.dropna()
    if len(s) < MIN_BREADTH:
        return None
    # trailing inverse vol (PIT)
    vol = ret_hist[s.index].tail(VOL_LOOKBACK).std()
    vol = vol.replace(0.0, np.nan)
    common = s.index.intersection(vol.dropna().index)
    if len(common) < MIN_BREADTH:
        return None
    s = s[common]
    vol = vol[common]
    # cross-sectional z-score of carry, winsorized
    z = (s - s.mean()) / (s.std(ddof=0) if s.std(ddof=0) > 0 else 1.0)
    z = z.clip(-3, 3)
    w = z / vol                    # inverse-vol tilt on the carry z-score
    w = w - w.mean()               # dollar / market neutral
    if w.abs().sum() == 0:
        return None
    w = w / w.abs().sum()          # gross = 1
    w = w.clip(-NAME_CAP, NAME_CAP)
    w = w - w.mean()
    if w.abs().sum() == 0:
        return None
    w = w / w.abs().sum()
    return w


def run_strategy(ret: pd.DataFrame, sig: pd.DataFrame, cfg: dict) -> pd.Series:
    """Return the net daily strategy return series (before vol-target leverage)."""
    global VOL_LOOKBACK, NAME_CAP
    VOL_LOOKBACK = cfg.get("vol_lookback", 63)
    NAME_CAP = cfg.get("name_cap", 0.20)
    # monthly rebalance = last trading day of each month
    grid = ret.index
    month_ends = pd.Series(grid, index=grid).groupby([grid.year, grid.month]).last().values
    month_ends = pd.DatetimeIndex(month_ends)

    daily_w = pd.DataFrame(0.0, index=grid, columns=ret.columns)
    reb_days = []
    prev_w = pd.Series(0.0, index=ret.columns)
    turnover_on = pd.Series(0.0, index=grid)
    for t in month_ends:
        hist = ret.loc[:t]
        w = target_weights(sig.loc[t], hist)
        if w is None:
            continue
        wfull = pd.Series(0.0, index=ret.columns)
        wfull[w.index] = w.values
        # apply from t forward (daily_w is the TARGET as of close t; leak-lag applied below)
        daily_w.loc[t:] = 0.0
        daily_w.loc[t:, wfull.index] = np.tile(wfull.values, (len(daily_w.loc[t:]), 1))
        reb_days.append(t)
        turnover_on[t] = float((wfull - prev_w).abs().sum())
        prev_w = wfull

    # LEAK CONTROL: weights decided at close t are held during returns starting t+2
    # (fill at next bar t+1, first earned close-to-close return is t+1 -> t+2).
    held = daily_w.shift(2).fillna(0.0)
    gross_ret = (held * ret).sum(axis=1)
    # costs on the fill bar (t+1): turnover * one-way bps
    cost = turnover_on.shift(1).fillna(0.0) * (ONE_WAY_BPS * 1e-4)
    net = gross_ret - cost
    # trim to the live cross-sectional era (first real rebalance onward)
    if reb_days:
        net = net.loc[reb_days[0]:]
    return net.dropna()


def purged_wf_voltarget(net: pd.Series, train=504, test=126, embargo=21) -> pd.Series:
    """Deflated PURGED walk-forward vol-target overlay (mirrors mf_gauntlet cadence).

    The carry factor has NO fitted parameters; the only 'fit' is the vol-target
    leverage estimated on TRAIN and applied OOS on TEST. Sharpe/DSR are invariant to
    this constant, so the stitched-OOS series is (by construction) pure out-of-sample.
    Returns the stitched OOS daily returns scaled to ~15% ann vol per fold.
    """
    r = net.to_numpy(float)
    n = len(r)
    idx = net.index
    oos = pd.Series(dtype=float)
    start = 0
    while start + train + embargo + test <= n:
        tr = r[start:start + train]
        te_lo = start + train + embargo
        te_hi = te_lo + test
        te = r[te_lo:te_hi]
        sd = np.std(tr, ddof=1)
        k = (VOL_TARGET_ANN / (sd * np.sqrt(365.0))) if sd > 0 else 0.0
        k = float(np.clip(k, 0.0, 3.0))
        seg = pd.Series(te * k, index=idx[te_lo:te_hi])
        oos = pd.concat([oos, seg])
        start += test
    return oos


def equity_from_returns(net: pd.Series, init: float = INIT_CASH) -> pd.Series:
    """Epoch-ms indexed equity curve for the blessed summarize()/dsr path."""
    eq = init * (1.0 + net).cumprod()
    ms_vals = pd.DatetimeIndex(eq.index).to_numpy(dtype="datetime64[ms]").astype("int64")
    return pd.Series(eq.to_numpy(float), index=pd.Index(ms_vals, name="ts"), name="equity")


def cscv_pbo(variant_rets: dict[str, pd.Series], s: int = 10) -> float:
    """Bailey-Lopez de Prado CSCV probability of backtest overfitting over a variant family."""
    from itertools import combinations
    df = pd.DataFrame(variant_rets).dropna()
    if df.shape[1] < 2 or len(df) < s * 4:
        return float("nan")
    groups = np.array_split(np.arange(len(df)), s)
    logits = []
    half = s // 2
    for combo in combinations(range(s), half):
        is_idx = np.concatenate([groups[i] for i in combo])
        oos_idx = np.concatenate([groups[i] for i in range(s) if i not in combo])
        is_sr = df.iloc[is_idx].mean() / df.iloc[is_idx].std(ddof=1)
        oos_sr = df.iloc[oos_idx].mean() / df.iloc[oos_idx].std(ddof=1)
        best = is_sr.idxmax()
        rank = oos_sr.rank().loc[best] / (len(oos_sr) + 1)  # relative OOS rank of IS-best
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(np.log(rank / (1 - rank)))
    logits = np.array(logits)
    return float((logits <= 0).mean())  # P(IS-best underperforms OOS median)


def main() -> int:
    from alphaforge.analytics.metrics import DAYS_PER_YEAR, daily_returns, summarize
    from alphaforge.validation.dsr import dsr_from_returns

    print("building panels (real-futures carry) ...")
    ret, sig = build_panels()
    # Cross-sectional 'next' marks only exist 2010-06..2016-06; post-2016 breadth collapses to
    # a single root (RTY), so there is no cross-section to trade. Clip to the real carry era —
    # this is also what prevents the last 2016 weights from bleeding forward as a stale position.
    ERA = (ret.index >= "2010-06-01") & (ret.index <= "2016-07-31")
    ret, sig = ret.loc[ERA], sig.loc[ERA]
    print(f"  roots={ret.shape[1]}  dates={ret.shape[0]}  span={ret.index.min().date()}..{ret.index.max().date()}")
    breadth = sig.notna().sum(axis=1)
    print(f"  carry breadth: median={int(breadth.median())} max={int(breadth.max())} dates>=6={(breadth>=6).sum()}")

    # ---- primary config + robustness family (for PBO / honest trial count) ----
    variants = {
        "base_vl63_cap20": {"vol_lookback": 63, "name_cap": 0.20},
        "vl21_cap20": {"vol_lookback": 21, "name_cap": 0.20},
        "vl126_cap20": {"vol_lookback": 126, "name_cap": 0.20},
        "vl63_cap15": {"vol_lookback": 63, "name_cap": 0.15},
        "vl63_cap30": {"vol_lookback": 63, "name_cap": 0.30},
        "vl252_cap20": {"vol_lookback": 252, "name_cap": 0.20},
    }
    net_by_variant = {name: run_strategy(ret, sig, cfg) for name, cfg in variants.items()}
    primary = net_by_variant["base_vl63_cap20"]

    # ---- headline metrics via BLESSED summarize() on the vol-targeted OOS curve ----
    oos = purged_wf_voltarget(primary)
    eq_oos = equity_from_returns(oos)
    summ = summarize(eq_oos)
    d_rets = daily_returns(eq_oos)
    skew = float(((d_rets - d_rets.mean()) ** 3).mean() / d_rets.std(ddof=0) ** 3)

    # DSR: comparable fresh-trial convention (n_trials floor=2, DEFAULT var=1.0),
    # AND honest deflation against the variant family actually evaluated.
    dsr_fresh = dsr_from_returns(d_rets, 2, 1.0, DAYS_PER_YEAR)
    dsr_honest = dsr_from_returns(d_rets, max(2, len(variants)), 1.0, DAYS_PER_YEAR)

    # also report full-sample (no vol-target) as the pure-OOS signal read
    eq_full = equity_from_returns(primary)
    summ_full = summarize(eq_full)

    # ---- correlations ----
    # SPY (overlaps 2010-2016)
    spy = _load_ohlcv("SPY", LAKE_MF).pct_change()
    j = pd.concat([primary.rename("c"), spy.rename("s")], axis=1).dropna()
    corr_spy = float(np.corrcoef(j["c"], j["s"])[0, 1]) if len(j) > 30 else float("nan")

    # crypto book — structurally NO time overlap (crypto data 2020+, carry 2010-2016)
    corr_crypto = float("nan")
    crypto_overlap = 0
    try:
        ce = pd.read_parquet(_ROOT / "artifacts/walkforward/crypto_carry_wk/equity.parquet")
        cd = pd.to_datetime(ce["ts"], unit="ms").dt.tz_localize(None)
        cret = pd.Series(np.log(ce["equity"].to_numpy(float)), index=cd).resample("1D").last().dropna().diff()
        jj = pd.concat([primary.rename("c"), cret.rename("k")], axis=1).dropna()
        crypto_overlap = len(jj)
        if crypto_overlap > 30:
            corr_crypto = float(np.corrcoef(jj["c"], jj["k"])[0, 1])
    except Exception as e:  # noqa: BLE001
        print(f"  (crypto corr: {str(e)[:60]})")

    # ---- risk-off / carry-crash convexity check (the load-bearing caveat) ----
    roff = j.copy()
    worst = roff.nsmallest(int(len(roff) * 0.05), "s")  # worst 5% SPY days
    carry_in_riskoff_ann = float(worst["c"].mean() * 252)
    carry_all_ann = float(roff["c"].mean() * 252)
    downcapture = float(worst["c"].mean() / worst["s"].mean()) if worst["s"].mean() != 0 else float("nan")
    worst_day = float(primary.min())

    # ---- PBO ----
    pbo = cscv_pbo({k: v for k, v in net_by_variant.items()})

    result = {
        "lead": "LEAD1_commodity_cross_asset_carry",
        "window": f"{primary.index.min().date()}..{primary.index.max().date()}",
        "n_oos_days": int(len(d_rets)),
        "roots_traded": int(ret.shape[1]),
        "net_sharpe": round(float(summ.sharpe), 3),
        "net_sharpe_no_voltarget_fullsample": round(float(summ_full.sharpe), 3),
        "dsr_fresh_trial": round(float(dsr_fresh.dsr), 3),
        "dsr_deflated_6variants": round(float(dsr_honest.dsr), 3),
        "psr": round(float(dsr_fresh.psr), 3),
        "ann_vol": round(float(summ.vol_ann), 3),
        "max_dd": round(float(summ.max_dd), 3),
        "sortino": round(float(summ.sortino), 3),
        "cagr": round(float(summ.cagr), 3),
        "skew": round(skew, 3),
        "kurtosis_nonexcess": round(float(dsr_fresh.kurtosis), 2),
        "corr_to_spy": round(corr_spy, 3),
        "corr_to_crypto_book": corr_crypto if not np.isnan(corr_crypto) else None,
        "crypto_overlap_days": crypto_overlap,
        "pbo_cscv": round(pbo, 3) if not np.isnan(pbo) else None,
        "carry_return_ann_all": round(carry_all_ann, 4),
        "carry_return_ann_in_spy_worst5pct": round(carry_in_riskoff_ann, 4),
        "spy_worst5pct_downcapture": round(downcapture, 3),
        "worst_single_day": round(worst_day, 4),
        "one_way_cost_bps": ONE_WAY_BPS,
        "variant_full_sample_sharpe": {k: round(float(summarize(equity_from_returns(v)).sharpe), 3) for k, v in net_by_variant.items()},
        "DATA_LIMIT": "cross-sectional 'next' contract mark only exists 2010-06..2016-06; post-2016 only 1 root (RTY) => signal cannot be extended live",
    }
    (OUT / "carry_probe_result.json").write_text(json.dumps(result, indent=2))
    oos.to_frame("ret").to_parquet(OUT / "oos_daily_returns.parquet")
    eq_oos.to_frame("equity").to_parquet(OUT / "equity.parquet")
    primary.to_frame("ret").to_parquet(OUT / "primary_daily_returns.parquet")

    print("\n================ COMMODITY / CROSS-ASSET CARRY — GAUNTLET ================")
    for k, val in result.items():
        if k in ("variant_full_sample_sharpe",):
            print(f"  {k:34s}: {val}")
        else:
            print(f"  {k:34s}: {val}")
    print("  artifacts                         :", OUT)
    print("=========================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
