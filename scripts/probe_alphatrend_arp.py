#!/usr/bin/env python3
"""PROBE — ALPHATREND CONSTRUCTION A/B: correlation-aware weighting + single-EMA baseline.

2026-07-12. MEASURE-ONLY (new file; imports read-only from src, modifies nothing, writes NO
ledger trials). AlphaTrend is the managed-futures TREND sleeve: TS price-trend across 17 ETFs,
built by TrendVolTarget = sign(blended trend)/sigma inverse-vol, gross-normalized, book vol-target.
Its honest ceiling is Sharpe ~ sqrt(N_eff), N_eff = N/(1+(N-1)*rhobar^2): the weakness is HIGH
cross-ETF correlation (SPY/QQQ/IWM/EEM/EFA all one equity-beta) + naive per-instrument vol-target
that double-counts that shared beta.

This is a SELF-CONTAINED CHEAP SCREEN on the sleeve's own construction (template:
probe_econtrend_book.py / probe_alphamax_volscale.py). It rebuilds the trend book on the 17-ETF
lake and runs three constructions through the SAME replica so replica-vs-engine differences cancel
in the A/B delta:

  BASELINE : sign(cs-demeaned equal blend of mf_trend_63/126/252) / sigma  -> gross-norm/clip.
             (Faithful to the live path: SignalService blends the 3 legs then cs_zscore-demeans;
             TrendVolTarget uses only the SIGN, inverse-vol; gross cap 1.0 binds so the 0.15 vol-
             target is inert and the book realizes ~5% vol. Verified vs the frozen artifact.)
  T1       : w_raw = C^(-1/2) @ ( sign(blend)/sigma ) -- whiten the vol-normalized forecast vector
             by the inverse-sqrt of the shrinkage (Ledoit-Wolf) 17-ETF CORRELATION matrix, THEN the
             existing gross-norm/clip + book vol-target. Down-weights correlated clusters (the
             common equity/bond beta) so the book is not 5x-long one factor. Baltas(2015)
             diversification-multiplier / risk-parity-with-correlations. Expected win = drawdown &
             skew (better realized diversification), NOT a Sharpe jump.
  T2       : single ~110d trend (mf_trend_110, same functional form) vs the 3-speed blend --
             Valeyre (arXiv 2504.10914) "one ~110d EMA is optimal, stacking lookbacks is illusory
             diversification + cherry-picking". Diagnostic: is one horizon enough on OUR 17 ETFs?

VOL-MATCHING (decisive for an honest DD/skew read): Sharpe & skew are scale-invariant; maxDD is
NOT. A construction that merely realizes lower vol at the gross cap gives a smaller maxDD you would
just lever back. So every variant's net return stream is scaled to a COMMON annual vol before the
maxDD/skew comparison -- then a maxDD improvement is a REAL path/tail improvement, not a vol
artifact. Pre-match realized vol (the diversification signature) is reported separately.

PIT + committed costs: weights decided through close t are effective t+1 (never same-bar). Costs =
6bp/side on rebalance turnover (1bp comm + 3bp half-spread + 2bp latency, managed_futures.yaml) +
50bp/yr borrow on the short leg, accrued daily. Piecewise-constant target weights (monthly
rebalance, no intra-month drift-trading) -- identical across variants, so the delta is clean.

Screen only. Every measured construction arm is union-registered before DSR. A full deflated WF is
the separate next stage, justified only if a treatment beats baseline here. Under a paused campaign,
unregistered arms fail preflight before market data is loaded.

    uv run python scripts/probe_alphatrend_arp.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaforge.core.time import now_ms  # noqa: E402
from alphaforge.portfolio.covariance import ledoit_wolf_cc  # read-only import  # noqa: E402
from alphaforge.validation.dsr import dsr_from_returns  # read-only import  # noqa: E402
from alphaforge.validation.experiments import ExperimentUnion  # noqa: E402
from alphaforge.validation.probe_ledger import record_probe_trial  # noqa: E402

LAKE = REPO / "data" / "lake_mf" / "ohlcv_1d"
OUT = REPO / "artifacts" / "sweep" / "alphatrend_arp"
LEDGER = REPO / "var" / "experiments.jsonl"

ANN = 252.0
# --- construction constants (match src: zoo._MF_TREND_* + managed_futures.yaml) ---
VOL_SPAN = 33            # zoo._MF_TREND_VOL_SPAN: EWMA sigma_hat span for the trend normalization
BLEND_LB = (63, 126, 252)  # zoo._MF_TREND_LOOKBACKS
T2_LB = 110              # Valeyre single-horizon ~110d
GROSS_MAX = 1.0          # managed_futures.yaml portfolio.gross_max
W_MAX = 0.34             # managed_futures.yaml portfolio.w_max
VOL_TARGET = 0.15        # portfolio.vol_target_ann
VOL_SCALE_MAX = 3.0      # portfolio.vol_scale_max
REBALANCE = 21           # signals.horizon_bars (monthly)
COV_WINDOW = 252         # trailing window for the shrinkage cov / correlation matrix
MIN_MEMBERS = 5          # need >=5 warm ETFs to form a cross-sectional demeaned blend
START = "2006-01-03"     # match the frozen mf artifact window (warmup uses earlier bars)
# costs
COST_PER_SIDE = 6e-4     # 1bp comm + 3bp half-spread + 2bp latency
BORROW_ANN = 50e-4       # 50bp/yr GC borrow on the short leg


# ------------------------------------------------------------------- data
def load_panel() -> pd.DataFrame:
    """Wide date x ETF panel of total-return-adjusted daily closes (the 17-ETF lake)."""
    cols = {}
    for d in sorted(glob.glob(str(LAKE / "instrument_id=*"))):
        iid = Path(d).name.split("=", 1)[1]
        tkr = iid.split(":")[-1].replace("USD", "")  # XUSE:CASH:SPYUSD -> SPY
        files = sorted(glob.glob(str(Path(d) / "**" / "*.parquet"), recursive=True))
        if not files:
            continue
        df = pd.concat([pd.read_parquet(f) for f in files]).sort_values("ts_open")
        s = pd.Series(
            df["close"].to_numpy(dtype=np.float64),
            index=pd.to_datetime(df["ts_open"]).dt.tz_localize(None).dt.normalize(),
        )
        cols[tkr] = s[~s.index.duplicated(keep="last")]
    panel = pd.DataFrame(cols).sort_index()
    return panel


def ewma_vol(logret: pd.DataFrame, span: int) -> pd.DataFrame:
    """Zero-mean EWMA sigma_hat of 1-bar log returns (src vol.ewma_vol_from_returns)."""
    return logret.pow(2).ewm(span=span, adjust=False, min_periods=span).mean().pow(0.5)


def mf_trend(logclose: pd.DataFrame, sigma: pd.DataFrame, lb: int) -> pd.DataFrame:
    """mf_trend_L = ln(C_t/C_{t-L}) / (sigma_hat_t * sqrt(L)) -- src momentum.ts_momentum."""
    mom = logclose - logclose.shift(lb)
    return mom / (sigma.where(sigma > 0.0) * np.sqrt(lb))


# ------------------------------------------------------------------- construction
def corr_inv_sqrt(cov: np.ndarray) -> np.ndarray:
    """C^(-1/2) from a covariance: to correlation, eigen-floor, inverse-sqrt whitening."""
    d = np.sqrt(np.clip(np.diag(cov), 1e-16, None))
    corr = cov / np.outer(d, d)
    corr = 0.5 * (corr + corr.T)
    w, v = np.linalg.eigh(corr)
    floor = 1e-3 * float(np.mean(w))  # tame the ill-conditioned near-collinear directions
    w = np.clip(w, floor, None)
    return (v * (w ** -0.5)[None, :]) @ v.T


def target_weights(
    signal_row: np.ndarray,      # cs-demeaned blended trend on the active set (sign = direction)
    sigma_ann: np.ndarray,       # per-ETF annualized vol (sqrt diag of shrunk cov)
    cov_ann: np.ndarray,         # annualized shrunk covariance (active set)
    mode: str,                   # "baseline" | "t1" | "t2" (t2 uses a single-leg signal upstream)
) -> np.ndarray:
    """Raw -> gross-normalized/clipped weights, then the book vol-target overlay (gross-capped).

    Faithful to TrendVolTarget + overlay.vol_target: sign inverse-vol, Sigma|w|=gross_max, clip
    +-w_max, renormalize toward full gross; then s=min(target/ex_ante, s_max) with a gross re-clip
    (which BINDS, so the sleeve realizes its natural ~5% vol -- exactly the live behavior)."""
    sign = np.sign(signal_row)
    g = np.zeros_like(sign)
    ok = (sigma_ann > 0) & np.isfinite(sign)
    # Signed inverse-vol is the vol-normalized vector.
    g[ok] = sign[ok] / sigma_ann[ok]
    if mode == "t1":
        # The only delta versus baseline is correlation whitening.
        g = corr_inv_sqrt(cov_ann) @ g
    # gross-normalize -> clip -> renormalize toward full gross (TrendVolTarget.solve)
    gross = np.abs(g).sum()
    if gross <= 0:
        return np.zeros_like(g)
    w = g * (GROSS_MAX / gross)
    w = np.clip(w, -W_MAX, W_MAX)
    gc, ma = np.abs(w).sum(), np.abs(w).max()
    if gc > 0 and ma > 0:
        w = w * min(GROSS_MAX / gc, W_MAX / ma)
    # book vol-target overlay (overlay.vol_target): ex-ante -> scale -> gross re-clip
    ex_ante = float(np.sqrt(max(w @ cov_ann @ w, 0.0)))
    s = VOL_SCALE_MAX if ex_ante <= 0 else min(VOL_TARGET / ex_ante, VOL_SCALE_MAX)
    w = s * w
    gr = np.abs(w).sum()
    if gr > GROSS_MAX:
        w = w * (GROSS_MAX / gr)
    return w


def run_variant(
    panel: pd.DataFrame,
    logclose: pd.DataFrame,
    ret: pd.DataFrame,
    trend_blend: pd.DataFrame,   # composite trend score (equal blend or single leg), date x ETF
    rebal_dates: list[pd.Timestamp],
    all_dates: pd.DatetimeIndex,
    mode: str,
) -> tuple[pd.Series, dict]:
    """Build the piecewise-constant target-weight book for one construction; return net returns."""
    tickers = list(panel.columns)
    W = pd.DataFrame(np.nan, index=all_dates, columns=tickers)
    prev = pd.Series(0.0, index=tickers)
    turn_events: list[float] = []
    for t in rebal_dates:
        win = ret.loc[:t].tail(COV_WINDOW)
        # active = warm signal + enough window history
        sig = trend_blend.loc[t]
        active = [
            c for c in tickers
            if np.isfinite(sig.get(c, np.nan)) and win[c].notna().sum() >= int(0.8 * COV_WINDOW)
        ]
        if len(active) < MIN_MEMBERS:
            W.loc[t] = prev.to_numpy()
            continue
        a = np.asarray(active)
        sub = win[active].to_numpy()
        sub = np.where(np.isfinite(sub), sub, 0.0)
        T = sub.shape[0]
        S = (sub.T @ sub) / float(T)                 # zero-mean sample cov (src convention)
        S = 0.5 * (S + S.T)
        try:
            S_shr, _ = ledoit_wolf_cc(sub, S)        # Ledoit-Wolf constant-correlation shrink
        except Exception:
            S_shr = S
        cov_ann = S_shr * ANN
        sigma_ann = np.sqrt(np.clip(np.diag(cov_ann), 1e-12, None))
        raw = sig[active].to_numpy(dtype=np.float64)
        demeaned = raw - raw.mean()                  # cs_zscore direction (sign of demeaned blend)
        w_act = target_weights(demeaned, sigma_ann, cov_ann, mode)
        w_full = pd.Series(0.0, index=tickers)
        w_full[a] = w_act
        turn_events.append(float(np.abs(w_full - prev).sum()))
        W.loc[t] = w_full.to_numpy()
        prev = w_full
    # piecewise-constant hold between rebalances (rows set only at rebalances; ffill the rest)
    W = W.ffill().fillna(0.0)
    # PIT: weight from prior close applied to today's return
    Wp = W.shift(1).fillna(0.0)
    gross_ret = (Wp * ret.reindex(all_dates)).sum(axis=1)
    borrow = np.clip(-Wp, 0.0, None).sum(axis=1) * (BORROW_ANN / ANN)
    cost = pd.Series(0.0, index=all_dates)
    for t, dt in zip(rebal_dates, turn_events, strict=False):
        if t in cost.index:
            cost.loc[t] += dt * COST_PER_SIDE
    net = (gross_ret - borrow - cost).dropna()
    net = net.loc[net.index >= pd.Timestamp(START)]
    turn_ann = float(np.sum(turn_events) / (len(net) / ANN)) if len(net) else float("nan")
    return net, {
        "turnover_ann": turn_ann,
        "n_rebals": len(rebal_dates),
        "gross_cost": float(cost.sum()),
    }


# ------------------------------------------------------------------- metrics
def sharpe(r: pd.Series) -> float:
    sd = r.std(ddof=0)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def sortino(r: pd.Series) -> float:
    dn = r[r < 0].std(ddof=0)
    return float(r.mean() / dn * np.sqrt(ANN)) if dn > 0 else float("nan")


def maxdd(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def skew(r: pd.Series) -> float:
    x = r.dropna().to_numpy()
    sd = x.std(ddof=0)
    return float(((x - x.mean()) ** 3).mean() / sd ** 3) if sd > 0 else float("nan")


def vol_ann(r: pd.Series) -> float:
    return float(r.std(ddof=0) * np.sqrt(ANN))


def to_vol(r: pd.Series, target: float) -> pd.Series:
    v = vol_ann(r)
    return r * (target / v) if v > 0 else r


def spy_corr(net: pd.Series, ret: pd.DataFrame) -> float:
    if "SPY" not in ret.columns:
        return float("nan")
    j = pd.concat([net.rename("b"), ret["SPY"].rename("s")], axis=1).dropna()
    return float(np.corrcoef(j["b"], j["s"])[0, 1]) if len(j) > 30 else float("nan")


def main() -> int:
    variants = {
        "baseline": ("baseline", "blend_63_126_252"),
        "T1_corr_whiten": ("t1", "blend_63_126_252"),
        "T2_single_110": ("baseline", "single_110"),
    }

    def trial_config(name: str, mode: str, signal: str) -> dict:
        return {
            "variant": name,
            "allocator": mode,
            "signal": signal,
            "universe": "managed_futures_17_etfs",
            "vol_span": VOL_SPAN,
            "rebalance_bars": REBALANCE,
            "gross_max": GROSS_MAX,
            "cost_per_side": COST_PER_SIDE,
            "borrow_ann": BORROW_ANN,
        }

    configs = {name: trial_config(name, mode, signal) for name, (mode, signal) in variants.items()}
    union = ExperimentUnion.discover(LEDGER, REPO)
    union.preflight_hypotheses(
        [{"probe": "alphatrend_arp", **config} for config in configs.values()]
    )

    OUT.mkdir(parents=True, exist_ok=True)
    panel = load_panel()
    logclose = np.log(panel)
    ret = panel.pct_change()
    logret = logclose.diff()
    sigma = ewma_vol(logret, VOL_SPAN)

    legs = {lb: mf_trend(logclose, sigma, lb) for lb in (*BLEND_LB, T2_LB)}
    blend3 = sum(legs[lb] for lb in BLEND_LB) / float(len(BLEND_LB))   # equal blend (default)
    single110 = legs[T2_LB]

    all_dates = panel.index
    warm = blend3.loc[blend3.index >= pd.Timestamp("2004-01-01")].dropna(how="all").index
    first = warm.min()
    grid = [d for d in all_dates if d >= first]
    rebal_dates = grid[::REBALANCE]

    variant_inputs = {
        "baseline": ("baseline", blend3),
        "T1_corr_whiten": ("t1", blend3),
        "T2_single_110": ("baseline", single110),
    }
    nets: dict[str, pd.Series] = {}
    diags: dict[str, dict] = {}
    for name, (mode, sig) in variant_inputs.items():
        net, d = run_variant(panel, logclose, ret, sig, rebal_dates, all_dates, mode)
        nets[name] = net
        diags[name] = d

    # common window + common vol-match target (baseline realized vol -> resembles the live book)
    common = nets["baseline"].index
    for n in nets.values():
        common = common.intersection(n.index)
    base_vol = vol_ann(nets["baseline"].loc[common])
    match_vol = round(base_vol, 4)

    audit_before = union.n_trials()
    for name, net in nets.items():
        record_probe_trial(
            "alphatrend_arp",
            configs[name],
            net.loc[common],
            now_ms=now_ms(),
            periods_per_year=int(ANN),
            experiment_log=union,
        )
    trials_logged = union.n_trials() - audit_before
    n_trials = union.n_hypotheses()
    sr_var = union.hypothesis_sharpe_variance()

    # avg pairwise correlation + effective breadth over the common window (the ceiling context)
    rc = ret.reindex(common).dropna(how="all", axis=1)
    cc = rc.corr()
    off = ~np.eye(cc.shape[0], dtype=bool)
    rhobar = float(np.nanmean(cc.to_numpy()[off]))
    N = cc.shape[0]
    n_eff = N / (1.0 + (N - 1) * rhobar ** 2)

    rows = []
    for name, net in nets.items():
        r = net.loc[common]
        rm = to_vol(r, match_vol)           # vol-matched: Sharpe/skew invariant, maxDD comparable
        dsr = dsr_from_returns(rm, max(2, n_trials), sr_var, ANN)
        rows.append({
            "variant": name,
            "net_sharpe": round(sharpe(r), 3),
            "DSR@N": round(float(dsr.dsr), 3),
            "vol_ann_realized": round(vol_ann(r), 4),   # PRE-match: the diversification signature
            "maxDD_volmatched": round(maxdd(rm), 4),     # comparable across variants
            "skew": round(skew(r), 3),
            "sortino": round(sortino(r), 3),
            "corr_SPY": round(spy_corr(r, ret.reindex(common)), 3),
            "turnover_ann": round(diags[name]["turnover_ann"], 2),
        })
    tab = pd.DataFrame(rows).set_index("variant")

    b = tab.loc["baseline"]
    lines = []

    def say(s: str = "") -> None:
        lines.append(s)
        print(s)

    say("=" * 82)
    say("ALPHATREND CONSTRUCTION A/B — corr-aware whitening (T1) + single-110d (T2)")
    say(f"window {common.min().date()}..{common.max().date()}  n={len(common)} sessions  "
        f"| ledger N={n_trials} (0 trials logged by this screen)")
    say(f"17-ETF avg pairwise corr rhobar={rhobar:+.3f}  ->  N_eff={n_eff:.2f} of N={N}  "
        f"(Sharpe ceiling ~ sqrt(N_eff)={np.sqrt(n_eff):.2f}x a single trend)")
    say(f"vol-match target = baseline realized vol = {match_vol:.3f}  (maxDD/skew compared here)")
    say("=" * 82)
    say(tab.to_string())
    say()
    say("DELTAS vs baseline (T = treatment):")
    for name in ("T1_corr_whiten", "T2_single_110"):
        t = tab.loc[name]
        say(f"  {name:16s}  dSharpe={t.net_sharpe - b.net_sharpe:+.3f}  "
            f"dDSR={t['DSR@N'] - b['DSR@N']:+.3f}  "
            f"dMaxDD={t.maxDD_volmatched - b.maxDD_volmatched:+.4f} "
            f"({'better' if t.maxDD_volmatched > b.maxDD_volmatched else 'worse'})  "
            f"dSkew={t['skew'] - b['skew']:+.3f}  dTurnover={t.turnover_ann - b.turnover_ann:+.2f}")

    # crisis maxDD table (vol-matched) — the crash-protection check T1 is supposed to help
    crises = {"GFC_2008": ("2007-10-01", "2009-03-31"),
              "COVID_2020": ("2020-02-15", "2020-04-30"),
              "BEAR_2022": ("2022-01-01", "2022-12-31")}
    say()
    say("crisis maxDD (vol-matched, more-negative = deeper):")
    crow = {}
    for name, net in nets.items():
        rm = to_vol(net.loc[common], match_vol)
        crow[name] = {c: round(maxdd(rm.loc[(rm.index >= a) & (rm.index <= z)]), 4)
                      for c, (a, z) in crises.items()}
    say(pd.DataFrame(crow).to_string())

    report = {
        "probe": "alphatrend_arp", "window": [str(common.min().date()), str(common.max().date())],
        "n_sessions": len(common), "ledger_N": int(n_trials),
        "trials_logged_this_run": trials_logged,
        "rhobar": rhobar, "N_eff": n_eff, "vol_match_target": match_vol,
        "table": json.loads(tab.reset_index().to_json(orient="records")),
        "crisis_maxdd_volmatched": crow, "diags": diags,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    (OUT / "report.txt").write_text("\n".join(lines))
    say()
    say(f"artifacts -> {OUT}  (report.txt / report.json)  | records appended: {trials_logged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
