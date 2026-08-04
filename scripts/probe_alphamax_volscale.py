"""PROBE: crash-protected / volatility-scaled momentum overlay on the ALPHAMAX sleeve.

Research question (2026-07-11): does Barroso & Santa-Clara (2015) constant-vol
scaling -- or the Daniel & Moskowitz (2016) variance-scaled / dynamic variants --
improve the 12-1 momentum sleeve NET of costs, and how much of any improvement
is genuinely NEW versus a relabeling of the book-level vol_target overlay
(configs/base.yaml vol_target_ann=0.15, portfolio/overlay.py) that BOTH
baseline artifacts already ran under?

Baselines (frozen artifacts, read-only):
  * artifacts/walkforward/k30_dn_63     -- canonical 2023+ Polygon sleeve (var/ ledger)
  * artifacts/walkforward/prereg_momentum -- deep-history 2005-2026 Sharadar (var_sharadar/ ledger)

PRE-REGISTERED overlay configs (locked before any overlay result was computed;
every config evaluated is recorded on the profile's experiments ledger):
  V1 bs_cvol_126  (BOTH baselines)  w_raw = clip(sigma_tgt / sigma_hat, 0.5, 1.5)
                  sigma_hat = sqrt(365 * mean(r^2, last 126 obs)) (zero-mean, BS convention;
                  365-annualization matches the repo's headline basis), sigma_tgt = 0.12.
                  Checkpoint every 21 obs; re-lever only if |w_new/w_cur - 1| > 0.20.
  V2 dm_var_126   (BOTH baselines)  w_raw = clip((sigma_tgt / sigma_hat)^2, 0.5, 1.5)
                  (DM's 1/sigma^2 scaling), same cadence/band as V1.
  V3 dm_dyn       (prereg only)     DM2016 dynamic: expanding monthly regression of the
                  sleeve's monthly return on I_B * sigma2_m (bear indicator x market
                  variance), warmup 36 months (cvol weight until warm), weight
                  w = clip(mu_hat / sigma_hat^2, normalized by the expanding median of
                  past positive raw values, 0.0, 1.5), re-levered monthly. Market proxy:
                  SPY total-return closes from data/lake_mf (dividend back-adjusted;
                  window RATIOS are true total returns, PIT-safe). I_B = trailing
                  504-session SPY total return < 0; sigma2_m = var(SPY daily rets, 126 obs).

Timing (PIT): the scale decided from data through the close of day t is effective
for day t+1's return -- never same-bar. (The next-open partial-day mix is second-
order at monthly banded cadence and is noted, not modeled.)

Incremental costs charged (the baselines are already net; the overlay only adds):
  * re-lever trade: |dw| * gross_mean * 6bp  (1bp commission + 3bp half-spread +
    2bp latency per side of notional traded, per configs/equity.yaml; sqrt-impact
    at $100k on liquid names is <1bp and noted, not modeled)
  * short-borrow delta: (w-1) * gross_mean/2 * 50bp/yr, accrued per trading day.

HONESTY DIAGNOSTICS (not trials): (a) alpha of the scaled sleeve regressed on
{unscaled sleeve, sleeve re-scaled by a mirror of the ENGINE's own book-level
vol-target rule (EWMA-240 realized, 0.15 target, s<=1.5)} -- if alpha ~ 0 the
overlay is relabeled book vol-targeting; (b) correlation of the overlay scale
with the book-style scale and of sleeve vol with market vol; (c) crash-episode
table; (d) I_B firing history.

Usage:
  uv run python scripts/probe_alphamax_volscale.py            # run + log trials
  uv run python scripts/probe_alphamax_volscale.py --no-log   # dry run (no ledger writes)

Outputs: artifacts/probe_volscale/report.txt + report.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.analytics.metrics import daily_returns, sharpe
from alphaforge.validation.dsr import dsr_from_returns
from alphaforge.validation.experiments import ExperimentLog

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "artifacts" / "probe_volscale"

ANN = 365.0  # the repo's headline annualization basis (matches k30_dn_63's 0.907)

# --- pre-registered overlay parameters (locked 2026-07-11 before any result) ---
VOL_WINDOW = 126          # trailing obs for realized vol (BS2015 / DM2016 OOS spec)
SIGMA_TARGET = 0.12       # annualized (ANN basis), the BS2015 choice
W_CLIP = (0.5, 1.5)       # leverage clip (paper realized ~[0.53, 2.18]; mandate-conservative)
CHECK_EVERY = 21          # re-lever checkpoint cadence (obs) ~ monthly
BAND = 0.20               # re-lever only if |w_new/w_cur - 1| > BAND
DYN_WARMUP_MONTHS = 36    # dm_dyn expanding-regression warmup (cvol weight until warm)
DYN_CLIP = (0.0, 1.5)     # dm_dyn weight clip (no shorting momentum)
BEAR_LOOKBACK = 504       # sessions ~ 24 months for the DM bear indicator
COST_PER_SIDE = 6e-4      # 1bp commission + 3bp half-spread + 2bp latency (equity.yaml)
BORROW_ANN = 50e-4        # 50bp/yr GC borrow on the short leg
TRADING_DAYS = 252.0      # borrow accrual grid (rate charged over a trading year)

BASELINES = {
    "k30_dn_63": {
        "artifact": "artifacts/walkforward/k30_dn_63",
        "ledger": "var/experiments.jsonl",
        "gross_mean": 0.691189,   # from the artifact's summary.txt
        "variants": ["bs_cvol_126", "dm_var_126"],
    },
    "prereg_momentum": {
        "artifact": "artifacts/walkforward/prereg_momentum",
        "ledger": "var_sharadar/experiments.jsonl",
        "gross_mean": 0.450322,   # from the artifact's summary.txt
        "variants": ["bs_cvol_126", "dm_var_126", "dm_dyn"],
    },
}

EPISODES = {
    # label: (start, end) -- crash windows for the episode table (calendar dates, UTC)
    "GFC crash+rebound 2008-09": ("2008-09-01", "2009-12-31"),
    "COVID crash 2020-02/04": ("2020-02-15", "2020-04-30"),
    "Vaccine rotation 2020-11": ("2020-11-01", "2020-11-30"),
    "2022 bear": ("2022-01-01", "2022-12-31"),
    "2025-03 momentum trough": ("2024-03-01", "2025-03-31"),
}


# --------------------------------------------------------------------------- helpers
def load_equity_returns(artifact_dir: Path) -> pd.Series:
    """Daily net returns of a frozen walk-forward artifact (repo headline basis)."""
    df = pd.read_parquet(artifact_dir / "equity.parquet")
    eq = pd.Series(df["equity"].to_numpy(), index=df["ts"].to_numpy())
    return daily_returns(eq)  # index = epoch-ms of UTC day start


def load_spy() -> pd.DataFrame:
    """SPY dividend-back-adjusted closes from the managed-futures ETF lake (read-only)."""
    files = sorted(
        glob.glob(str(REPO / "data/lake_mf/ohlcv_1d/instrument_id=XUSE:CASH:SPYUSD/year=*/*.parquet"))
    )
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("ts_open")
    out = pd.DataFrame(
        {
            "close": df["close"].to_numpy(dtype=np.float64),
        },
        index=pd.DatetimeIndex(df["ts_open"]).tz_convert("UTC"),
    )
    out["ret"] = out["close"].pct_change()
    return out


def realized_vol_ann(rets: np.ndarray, window: int) -> np.ndarray:
    """sqrt(ANN * rolling mean of r^2) -- BS zero-mean convention; NaN until warm."""
    r2 = pd.Series(rets**2).rolling(window, min_periods=window).mean().to_numpy()
    return np.sqrt(ANN * r2)


def max_drawdown(rets: np.ndarray) -> float:
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    return float(np.max(1.0 - eq / peak))


def worst_month(rets: pd.Series) -> float:
    dt = pd.to_datetime(rets.index, unit="ms", utc=True)
    monthly = (1.0 + pd.Series(rets.to_numpy(), index=dt)).groupby(
        [dt.year, dt.month]
    ).prod() - 1.0
    return float(monthly.min())


def skew_kurt(rets: np.ndarray) -> tuple[float, float]:
    from scipy.stats import kurtosis as _kurt
    from scipy.stats import skew as _skew

    return float(_skew(rets, bias=True)), float(_kurt(rets, fisher=False, bias=True))


def nw_tstat(y: np.ndarray, X: np.ndarray, lags: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """OLS betas + Newey-West t-stats (Bartlett kernel). X includes the constant."""
    n, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    u = y - X @ beta
    xu = X * u[:, None]
    S = xu.T @ xu
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        gamma = xu[lag:].T @ xu[:-lag]
        S += w * (gamma + gamma.T)
    cov = xtx_inv @ S @ xtx_inv
    se = np.sqrt(np.diag(cov))
    return beta, beta / se


def metrics_block(rets: pd.Series) -> dict:
    v = rets.to_numpy(dtype=np.float64)
    sk, ku = skew_kurt(v)
    yrs = len(v) / TRADING_DAYS
    total = float(np.prod(1.0 + v))
    return {
        "n_obs": int(len(v)),
        "sharpe_ann365": float(sharpe(rets, ANN)),
        "sharpe_ann252": float(sharpe(rets, TRADING_DAYS)),
        "vol_ann365": float(np.std(v, ddof=1) * math.sqrt(ANN)),
        "max_dd": max_drawdown(v),
        "worst_day": float(np.min(v)),
        "worst_month": worst_month(rets),
        "skew": sk,
        "kurtosis": ku,
        "total_return": total - 1.0,
        "cagr": total ** (1.0 / yrs) - 1.0 if yrs > 0 else float("nan"),
    }


# --------------------------------------------------------------------------- overlays
def apply_scale_path(
    rets: pd.Series, w_eff: np.ndarray, gross_mean: float
) -> tuple[pd.Series, dict]:
    """Scaled NET returns: w*r minus re-lever trade costs minus short-borrow delta."""
    r = rets.to_numpy(dtype=np.float64)
    dw = np.abs(np.diff(w_eff, prepend=w_eff[0]))
    relever_cost = dw * gross_mean * COST_PER_SIDE
    borrow_delta = (w_eff - 1.0) * (gross_mean / 2.0) * (BORROW_ANN / TRADING_DAYS)
    net = w_eff * r - relever_cost - borrow_delta
    diag = {
        "w_mean": float(np.mean(w_eff)),
        "w_min": float(np.min(w_eff)),
        "w_max": float(np.max(w_eff)),
        "n_relevers": int(np.sum(dw > 0)),
        "added_turnover_notional_frac_per_yr": float(
            np.sum(dw * gross_mean) / (len(r) / TRADING_DAYS)
        ),
        "total_relever_cost_frac": float(np.sum(relever_cost)),
        "total_borrow_delta_frac": float(np.sum(borrow_delta)),
    }
    return pd.Series(net, index=rets.index, name="ret"), diag


def weights_banded(w_raw: np.ndarray) -> np.ndarray:
    """Checkpoint-every-21-obs, 20%-band re-levering; scale effective NEXT day.

    w_raw[i] uses data through day i. The effective weight for day i is decided
    at the most recent accepted checkpoint STRICTLY BEFORE i (PIT: no same-bar).
    Warmup (w_raw NaN) keeps w=1.
    """
    n = len(w_raw)
    w_eff = np.ones(n)
    w_cur = 1.0
    last_check = -CHECK_EVERY  # allow a checkpoint at the first warm obs
    for i in range(n - 1):
        if np.isfinite(w_raw[i]) and (i - last_check) >= CHECK_EVERY:
            last_check = i
            if abs(w_raw[i] / w_cur - 1.0) > BAND:
                w_cur = float(w_raw[i])
        w_eff[i + 1] = w_cur
    w_eff[0] = 1.0
    return w_eff


def overlay_cvol(rets: pd.Series) -> np.ndarray:
    v = rets.to_numpy(dtype=np.float64)
    sig = realized_vol_ann(v, VOL_WINDOW)
    w_raw = np.clip(SIGMA_TARGET / sig, W_CLIP[0], W_CLIP[1])
    return weights_banded(w_raw)


def overlay_var(rets: pd.Series) -> np.ndarray:
    v = rets.to_numpy(dtype=np.float64)
    sig = realized_vol_ann(v, VOL_WINDOW)
    w_raw = np.clip((SIGMA_TARGET / sig) ** 2, W_CLIP[0], W_CLIP[1])
    return weights_banded(w_raw)


def overlay_dyn(rets: pd.Series, spy: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """DM2016 dynamic weight, monthly re-lever, expanding regression, PIT normalizer."""
    v = rets.to_numpy(dtype=np.float64)
    dt = pd.to_datetime(rets.index, unit="ms", utc=True)
    sig2 = (realized_vol_ann(v, VOL_WINDOW) ** 2) / ANN  # per-day sleeve variance

    # market state aligned as-of each sleeve day (last SPY obs <= sleeve day)
    spy_close = spy["close"]
    spy_ret = spy["ret"].dropna()
    ib_series = (spy_close / spy_close.shift(BEAR_LOOKBACK) - 1.0) < 0.0
    ib_ok = spy_close.shift(BEAR_LOOKBACK).notna()
    var_m = spy_ret.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).var()

    ib_asof = pd.Series(np.where(ib_ok, ib_series, np.nan), index=spy_close.index).reindex(
        dt, method="ffill"
    ).to_numpy()
    varm_asof = var_m.reindex(dt, method="ffill").to_numpy()

    # month-end checkpoint indices on the sleeve grid
    ym = dt.year * 100 + dt.month
    is_month_end = np.append(ym[:-1] != ym[1:], True)
    month_ends = np.where(is_month_end)[0]

    # monthly sleeve returns + x = I_B*sigma2_m at PRIOR month end
    n = len(v)
    w_eff = np.ones(n)
    w_cur = 1.0
    cvol_raw = np.clip(SIGMA_TARGET / np.sqrt(sig2 * ANN), W_CLIP[0], W_CLIP[1])
    ys: list[float] = []  # monthly sleeve returns
    xs: list[float] = []  # I_B*var_m at the prior month end
    raw_hist: list[float] = []
    prev_end = -1
    prev_x = np.nan
    ib_fire_dates: list[str] = []
    used_dynamic = 0
    for me in month_ends:
        mret = float(np.prod(1.0 + v[prev_end + 1 : me + 1]) - 1.0)
        if np.isfinite(prev_x):
            ys.append(mret)
            xs.append(prev_x)
        ib_now = ib_asof[me]
        varm_now = varm_asof[me]
        x_now = (
            float(ib_now) * float(varm_now)
            if np.isfinite(ib_now) and np.isfinite(varm_now)
            else np.nan
        )
        if np.isfinite(ib_now) and ib_now > 0:
            ib_fire_dates.append(str(dt[me].date()))
        # decide next month's weight
        w_new = w_cur
        if len(ys) >= DYN_WARMUP_MONTHS and np.isfinite(x_now) and np.isfinite(sig2[me]) and sig2[me] > 0:
            X = np.column_stack([np.ones(len(ys)), np.asarray(xs)])
            yv = np.asarray(ys)
            try:
                beta = np.linalg.lstsq(X, yv, rcond=None)[0]
                mu = float(beta[0] + beta[1] * x_now)
                raw = mu / float(sig2[me])
                pos_hist = [max(h, 0.0) for h in raw_hist if np.isfinite(h)]
                norm = float(np.median(pos_hist)) if pos_hist else np.nan
                raw_hist.append(raw)
                if np.isfinite(norm) and norm > 1e-12:
                    w_new = float(np.clip(raw / norm, DYN_CLIP[0], DYN_CLIP[1]))
                    used_dynamic += 1
                elif np.isfinite(cvol_raw[me]):
                    w_new = float(cvol_raw[me])
            except np.linalg.LinAlgError:
                pass
        elif np.isfinite(cvol_raw[me]):
            w_new = float(cvol_raw[me])  # cvol fallback until the regression is warm
        if me + 1 < n:
            w_eff[me + 1 :] = w_new  # holds until the next checkpoint overwrites
        w_cur = w_new
        prev_end = me
        prev_x = x_now
    diag = {
        "n_months": int(len(month_ends)),
        "n_dynamic_months": used_dynamic,
        "ib_fire_month_ends": ib_fire_dates,
    }
    return w_eff, diag


# --------------------------------------------------------------------------- redundancy
def book_style_scale(rets: pd.Series) -> np.ndarray:
    """Mirror of the ENGINE's book-level vol_target realized leg (overlay.py):
    EWMA std halflife 240 obs, annualized (ANN), s = min(0.15/sigma, 1.5), effective
    next day. (The engine's ex-ante covariance leg and gross re-clip are not
    reconstructible from the return series; noted in the report.)"""
    v = rets.to_numpy(dtype=np.float64)
    ewm_sd = pd.Series(v).ewm(halflife=240, min_periods=60).std().to_numpy() * math.sqrt(ANN)
    s = np.minimum(0.15 / np.maximum(ewm_sd, 1e-12), 1.5)
    s = np.where(np.isfinite(ewm_sd), s, 1.0)
    s_eff = np.ones_like(s)
    s_eff[1:] = s[:-1]  # next-day effective
    return s_eff


def redundancy_tests(rets: pd.Series, scaled: pd.Series, w_eff: np.ndarray, spy: pd.DataFrame) -> dict:
    r = rets.to_numpy(dtype=np.float64)
    rs = scaled.to_numpy(dtype=np.float64)
    s_book = book_style_scale(rets)
    r_book2 = s_book * r  # the book rule applied a SECOND time on top of the artifact

    # (1) alpha of scaled on {unscaled} alone
    X1 = np.column_stack([np.ones(len(r)), r])
    b1, t1 = nw_tstat(rs, X1)
    # (2) alpha of scaled on {unscaled, book-style re-scaled}
    X2 = np.column_stack([np.ones(len(r)), r, r_book2])
    b2, t2 = nw_tstat(rs, X2)

    # scale correlations
    mask = np.isfinite(w_eff) & np.isfinite(s_book)
    corr_scales = float(np.corrcoef(w_eff[mask], s_book[mask])[0, 1])

    # sleeve-vol vs market-vol relabeling check
    dt = pd.to_datetime(rets.index, unit="ms", utc=True)
    sig_sleeve = realized_vol_ann(r, VOL_WINDOW)
    spy_ret = spy["ret"].dropna()
    sig_mkt = (
        spy_ret.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * math.sqrt(ANN)
    ).reindex(dt, method="ffill").to_numpy()
    m2 = np.isfinite(sig_sleeve) & np.isfinite(sig_mkt)
    corr_vols = float(np.corrcoef(sig_sleeve[m2], sig_mkt[m2])[0, 1]) if m2.sum() > 10 else float("nan")

    return {
        "alpha_on_unscaled_ann_bps": float(b1[0] * TRADING_DAYS * 1e4),
        "alpha_on_unscaled_nw_t": float(t1[0]),
        "beta_on_unscaled": float(b1[1]),
        "alpha_on_unscaled_plus_bookstyle_ann_bps": float(b2[0] * TRADING_DAYS * 1e4),
        "alpha_on_unscaled_plus_bookstyle_nw_t": float(t2[0]),
        "corr_overlay_scale_vs_bookstyle_scale": corr_scales,
        "corr_sleeve_vol_vs_market_vol_126d": corr_vols,
    }


def episode_table(rets: pd.Series, variants: dict[str, pd.Series]) -> dict:
    dt = pd.to_datetime(rets.index, unit="ms", utc=True)
    out = {}
    for label, (a, b) in EPISODES.items():
        m = (dt >= pd.Timestamp(a, tz="UTC")) & (dt <= pd.Timestamp(b, tz="UTC"))
        if m.sum() < 5:
            continue
        row = {"baseline": float(np.prod(1.0 + rets.to_numpy()[m]) - 1.0)}
        for name, s in variants.items():
            row[name] = float(np.prod(1.0 + s.to_numpy()[m]) - 1.0)
        out[label] = row
    return out


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-log", action="store_true", help="do not append trials to the ledgers")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spy = load_spy()
    now_ms = int(time.time() * 1000)
    report: dict = {"probe": "alphamax_volscale", "now_ms": now_ms, "preregistered": {
        "vol_window": VOL_WINDOW, "sigma_target": SIGMA_TARGET, "w_clip": W_CLIP,
        "check_every": CHECK_EVERY, "band": BAND, "dyn_warmup_months": DYN_WARMUP_MONTHS,
        "dyn_clip": DYN_CLIP, "bear_lookback": BEAR_LOOKBACK,
        "cost_per_side": COST_PER_SIDE, "borrow_ann": BORROW_ANN,
    }, "baselines": {}}
    trials_logged = 0
    lines: list[str] = []

    def say(s: str) -> None:
        lines.append(s)
        print(s)

    for bname, spec in BASELINES.items():
        art = REPO / spec["artifact"]
        rets = load_equity_returns(art)
        ledger = ExperimentLog(REPO / spec["ledger"])
        base_m = metrics_block(rets)
        say(f"\n=== BASELINE {bname} ({spec['artifact']}) ===")
        say(json.dumps(base_m, indent=1))

        variants_rets: dict[str, pd.Series] = {}
        bres: dict = {"baseline_metrics": base_m, "variants": {}}

        for vname in spec["variants"]:
            if vname == "bs_cvol_126":
                w_eff = overlay_cvol(rets)
                vdiag_extra: dict = {}
            elif vname == "dm_var_126":
                w_eff = overlay_var(rets)
                vdiag_extra = {}
            elif vname == "dm_dyn":
                w_eff, vdiag_extra = overlay_dyn(rets, spy)
            else:
                raise ValueError(vname)
            scaled, wdiag = apply_scale_path(rets, w_eff, spec["gross_mean"])
            vm = metrics_block(scaled)
            red = redundancy_tests(rets, scaled, w_eff, spy)
            variants_rets[vname] = scaled

            # ---- ledger (the trial) + DSR at post-record N ----
            cfg = {
                "probe": "alphamax_volscale",
                "baseline_artifact": spec["artifact"],
                "overlay": vname,
                "params": {
                    "vol_window": VOL_WINDOW, "sigma_target": SIGMA_TARGET,
                    "w_clip": list(W_CLIP), "check_every": CHECK_EVERY, "band": BAND,
                    **({"dyn_warmup_months": DYN_WARMUP_MONTHS, "dyn_clip": list(DYN_CLIP),
                        "bear_lookback": BEAR_LOOKBACK} if vname == "dm_dyn" else {}),
                },
            }
            v = scaled.to_numpy(dtype=np.float64)
            sk, ku = skew_kurt(v)
            sr_pp = float(sharpe(scaled, 1.0))
            if not args.no_log:
                ledger.record(
                    cfg,
                    sharpe_ann=float(sharpe(scaled, ANN)),
                    sharpe_per_period=sr_pp,
                    n_obs=len(v),
                    skew=sk,
                    kurtosis=ku,
                    now_ms=now_ms,
                )
                trials_logged += 1
            n_trials = ledger.n_trials()
            var_sr = ledger.trial_sharpe_variance()
            dsr_v = dsr_from_returns(scaled, max(2, n_trials), var_sr, ANN)
            dsr_b = dsr_from_returns(rets, max(2, n_trials), var_sr, ANN)

            bres["variants"][vname] = {
                "metrics": vm,
                "weights": wdiag | vdiag_extra,
                "dsr": {"dsr": float(dsr_v.dsr), "psr": float(dsr_v.psr),
                        "n_trials": int(n_trials), "sr_trials_variance": float(var_sr)},
                "baseline_dsr_at_same_N": {"dsr": float(dsr_b.dsr), "psr": float(dsr_b.psr)},
                "redundancy": red,
                "config_hash_logged": None if args.no_log else True,
            }
            say(f"\n--- {bname} / {vname} ---")
            say(json.dumps(vm, indent=1))
            say("weights: " + json.dumps(wdiag | vdiag_extra))
            say(f"DSR(scaled)={dsr_v.dsr:.4f}  DSR(baseline@sameN)={dsr_b.dsr:.4f}  N={n_trials}")
            say("redundancy: " + json.dumps(red, indent=1))

        bres["episodes"] = episode_table(rets, variants_rets)
        say("\nepisodes: " + json.dumps(bres["episodes"], indent=1))
        report["baselines"][bname] = bres

    report["trials_logged"] = trials_logged
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=1))
    (OUT_DIR / "report.txt").write_text("\n".join(lines))
    say(f"\ntrials logged this run: {trials_logged}")
    say(f"report -> {OUT_DIR}")


if __name__ == "__main__":
    main()
