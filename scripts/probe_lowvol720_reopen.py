#!/usr/bin/env python3
"""PROBE — execute the pre-registered reopening of `crypto_lowvol_720`.

The pre-registration is `docs/design/PREREG_CRYPTO_LOWVOL_REOPEN.md`, written and committed
2026-08-06 BEFORE any correlation was computed. This script does not decide anything: it
executes the measurement that document declared and evaluates the thresholds that document
fixed, in the order that document fixed them. Every threshold below is a transcription. If a
number here disagrees with the doc, the DOC is right and this script is a bug.

ZERO NEW TRIALS — the honesty claim that makes this legitimate.
    The config is not authored here. It is READ from the row already in `var/experiments.jsonl`
    (alpha_names == ['lowvol_720']), so the hypothesis was already counted in the honest N=127.
    The walk-forward is re-executed with ``now_ms=None`` and ``experiment_log=None``, which is
    the runner's documented no-ledger path (walkforward.py:791 — "when it is None the anti-overfit
    step is skipped entirely, nothing is recorded"). Stage 1 asserts the global ledger's line
    count is byte-identical before and after. Re-running an already-counted config to persist an
    artifact that was never saved is not a new hypothesis; running a MODIFIED config would be,
    and the config-drift guard below refuses to do that.

Stage 1 (``--stage rerun``): re-run the recorded config unchanged, persist `equity.parquet`
    (the file whose absence is the entire reason this candidate was never judged on the axis
    that matters), and reproduce the published net Sharpe 0.694625 as a correctness check.

Stage 2 (``--stage tests``): evaluate K1-K4 on the persisted curve. K5 (venue reality) is a
    deployment gate, not a measurement, and is reported as OUTSTANDING rather than evaluated.

    K1  book correlation      rho > +0.15  -> KILL   (>= 500 overlapping days required)
    K2  the costume test      rho > +0.25  -> KILL   (vs crypto_carry_wk specifically)
    K3  single-factor test    R^2 > 0.50   -> KILL   (BTC + a BTC-dominance proxy)
    K4  contribution          < +0.024     -> KILL   (book-Sharpe lift at equal weight)

THE LAG-ALIGNMENT REQUIREMENT (prereg, mandatory). Published sleeve curves are stamped one
session after the day they represent; a naive calendar join was measured 2026-08-06 to
understate correlation by ~30x (-0.029 vs +0.871 on the same two series). Every correlation
here is therefore computed at the lag in {-1, 0, +1} that MAXIMISES |rho|, the full lag table
is reported, and the chosen lag is named. Reporting only the calendar-join figure is named in
the prereg as the single most likely way this analysis produces a false pass.

    uv run python scripts/probe_lowvol720_reopen.py --stage rerun
    uv run python scripts/probe_lowvol720_reopen.py --stage tests

# CURVE-EXEMPT: this probe does not GENERATE a return stream — stage 1 delegates to
# WalkForwardRunner, which persists the canonical equity.parquet itself (that persistence is the
# entire point of the re-run), and stage 2 only reads curves. Nothing here would be lost.
"""
# ruff: noqa: E402, E501  (sys.path bootstrap before imports; long metric-dict literals)
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import pandas as pd

_LOG = logging.getLogger("lowvol720_reopen")

# ---------------------------------------------------------------------------------------
# Transcribed from docs/design/PREREG_CRYPTO_LOWVOL_REOPEN.md. Do not edit after a result
# is known -- changing any threshold below post-hoc is the first item on that document's
# own "what would make this pre-registration dishonest" list.
# ---------------------------------------------------------------------------------------
K1_BOOK_CORR_KILL = 0.15
K1_MIN_OVERLAP_DAYS = 500
K2_COSTUME_CORR_KILL = 0.25
K3_R2_KILL = 0.50
K4_MIN_CONTRIBUTION = 0.024
LAGS = (-1, 0, 1)

PUBLISHED_SHARPE = 0.6946246749457002  # var/experiments.jsonl, the row being re-executed
REPRO_TOL = 0.01  # |delta| above this and the curve is NOT the one that was killed

ANN = 252
LEDGER = _ROOT / "var" / "experiments.jsonl"
RERUN_DIR = _ROOT / "artifacts" / "walkforward" / "crypto_lowvol_720_reopen"
OUT_DIR = _ROOT / "artifacts" / "analysis" / "lowvol720_reopen"

# The three curves that ARE the live book (state.json book.sleeves). Same three, same paths,
# as the corrected scripts/analyze_sleeve_scaling.py -- a candidate must be judged against the
# same book the incumbents were judged against, or the comparison means nothing.
SLEEVES = {
    "alphamax (k30_dn_63)": _ROOT / "artifacts/walkforward/k30_dn_63/equity.parquet",
    "alphatrend (mf_live_fwd)": _ROOT / "artifacts/walkforward/mf_live_fwd/equity.parquet",
    "alphaforge (crypto_carry_wk)": _ROOT / "artifacts/walkforward/crypto_carry_wk/equity.parquet",
}
COSTUME_TARGET = "alphaforge (crypto_carry_wk)"  # K2 compares against this one specifically
BTC_1D = _ROOT / "data/lake/ohlcv_1d/instrument_id=BINANCE:PERP:BTCUSDT"
LAKE_1D = _ROOT / "data/lake/ohlcv_1d"


# ---------------------------------------------------------------------------------------
# Curve handling. `daily_logret` is copied VERBATIM from scripts/analyze_sleeve_scaling.py so
# that "a daily return" means exactly one thing across the two analyses that steer this book.
# ---------------------------------------------------------------------------------------
def daily_logret(path: str | Path) -> pd.Series:
    """Equity curve -> daily log returns, tolerant of hourly curves (crypto)."""
    e = pd.read_parquet(path)
    s = pd.Series(
        e["equity"].astype(float).values,
        index=pd.to_datetime(e["ts"], unit="ms"),
    ).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    daily = s.resample("1D").last().dropna()
    return np.log(daily).diff().dropna()


def sharpe(r: pd.Series | np.ndarray) -> float:
    x = np.asarray(r, float)
    sd = x.std(ddof=0)
    return float(x.mean() / sd * math.sqrt(ANN)) if sd > 0 else 0.0


def lag_table(a: pd.Series, b: pd.Series) -> tuple[dict, list[dict]]:
    """Correlate `a` against `b` at each lag in LAGS; return (chosen, full table).

    Lag L shifts the REFERENCE series `b` forward by L days before the join, so L=+1 tests
    "b is stamped one session late relative to a". The chosen lag is the one maximising |rho|,
    exactly as the pre-registration mandates. Ties break to the smaller |L| (then to L<0), so
    the choice is deterministic and does not depend on dict/iteration order.
    """
    rows: list[dict] = []
    for lag in LAGS:
        j = pd.concat([a.rename("a"), b.shift(lag).rename("b")], axis=1).dropna()
        n = int(len(j))
        if n < 30 or j["a"].std() == 0 or j["b"].std() == 0:
            rho = float("nan")
        else:
            rho = float(j["a"].corr(j["b"]))
        rows.append({"lag": int(lag), "rho": rho, "n_days": n})
    valid = [r for r in rows if not math.isnan(r["rho"])]
    if not valid:
        return {"lag": None, "rho": float("nan"), "n_days": 0}, rows
    chosen = sorted(valid, key=lambda r: (-abs(r["rho"]), abs(r["lag"]), r["lag"]))[0]
    return chosen, rows


def equal_risk_returns(curves: dict[str, pd.Series]) -> pd.Series:
    """Inverse-vol (equal-risk) combination of daily return series on their common days.

    Weights are computed on the common window and held fixed -- this is a measurement of the
    book's return stream, not a live allocator, so there is no PIT question to answer here.
    """
    frame = pd.concat(curves, axis=1).dropna()
    vols = frame.std(ddof=0)
    w = (1.0 / vols) / (1.0 / vols).sum()
    return (frame * w).sum(axis=1)


def book_sharpe_analytic(s_bar: float, rho_bar: float, n: int) -> float:
    """S_book = s_bar * sqrt(N_eff), N_eff = N / (1 + (N-1) * rho_bar). The prereg's K4 basis."""
    denom = 1.0 + (n - 1) * rho_bar
    if denom <= 0:
        return float("inf")
    return s_bar * math.sqrt(n / denom)


def mean_pairwise_corr(frame: pd.DataFrame) -> float:
    c = frame.corr().values
    iu = np.triu_indices_from(c, k=1)
    return float(np.nanmean(c[iu]))


# ---------------------------------------------------------------------------------------
# Stage 1 -- re-execute the recorded config, persist the curve that was never saved.
# ---------------------------------------------------------------------------------------
def _load_recorded_config() -> dict:
    """The ONE ledger row for this hypothesis. Refuses to guess if it is not unique."""
    rows = []
    with LEDGER.open() as fh:
        for line in fh:
            if "lowvol_720" not in line:
                continue
            d = json.loads(line)
            if d.get("config", {}).get("alpha_names") == ["lowvol_720"]:
                rows.append(d)
    if len(rows) != 1:
        raise SystemExit(
            f"expected exactly ONE recorded lowvol_720 trial in {LEDGER}, found {len(rows)}. "
            "Re-running is only zero-trial if the config is the one already counted."
        )
    return rows[0]


def stage_rerun() -> int:
    record = _load_recorded_config()
    cfg = record["config"]
    ids = list(cfg["instrument_ids"])

    # Config-drift guard: everything the runner is about to be handed comes from the ledger row.
    # A key we do not know how to pass through is a config change in disguise -- stop instead.
    known = {
        "allocator", "alpha_names", "end", "instrument_ids", "no_trade_band",
        "rebalance_bars", "start", "test_bars", "train_bars",
    }
    unknown = set(cfg) - known
    if unknown:
        raise SystemExit(f"recorded config has keys this probe cannot replay unchanged: {sorted(unknown)}")

    print("=" * 88)
    print("STAGE 1 — re-execute the recorded config (zero new trials)")
    print("=" * 88)
    print(f"  config_hash      {record['config_hash']}")
    print(f"  published sharpe {record['sharpe_ann']:.6f}   n_obs {record['n_obs']}")
    print(f"  alphas           {cfg['alpha_names']}   allocator {cfg['allocator']}")
    print(f"  rebalance_bars   {cfg['rebalance_bars']}   no_trade_band {cfg['no_trade_band']}")
    print(f"  train/test bars  {cfg['train_bars']} / {cfg['test_bars']}")
    print(f"  window           {pd.to_datetime(cfg['start'], unit='ms')} -> {pd.to_datetime(cfg['end'], unit='ms')}")
    print(f"  instruments      {len(ids)} (replayed verbatim from the ledger row)")
    print(f"  out_dir          {RERUN_DIR}")

    ledger_lines_before = sum(1 for _ in LEDGER.open())

    import alphaforge.features.library  # noqa: F401  (registers the factor library)
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.logging import setup_logging
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    settings = load_settings(None)
    setup_logging(settings.paths.var_dir / "log")
    sleeve = sleeve_for(settings.data.asset_class)
    paths = LakePaths(settings.paths.lake_dir)
    RERUN_DIR.mkdir(parents=True, exist_ok=True)

    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            sleeve=sleeve,
            alpha_names=list(cfg["alpha_names"]),
        )
        runner = WalkForwardRunner(
            reader, store, universe,
            TransactionCostModel.from_settings(settings),
            service, settings,
        )
        result = runner.run(
            int(cfg["start"]), int(cfg["end"]),
            train_bars=int(cfg["train_bars"]),
            test_bars=int(cfg["test_bars"]),
            allocator=cfg["allocator"],
            embargo_bars=sleeve.embargo_bars,
            instrument_ids=ids,
            rebalance_bars=int(cfg["rebalance_bars"]),
            no_trade_band=float(cfg["no_trade_band"]),
            out_dir=RERUN_DIR,
            now_ms=None,          # <- no ledger write, no DSR re-record: zero new trials
            alpha_names=list(cfg["alpha_names"]),
            experiment_log=None,  # <- belt and braces on the same guarantee
        )

    ledger_lines_after = sum(1 for _ in LEDGER.open())
    got = float(result.summary.sharpe)
    delta = got - PUBLISHED_SHARPE

    print("-" * 88)
    print(f"  ledger lines before/after   {ledger_lines_before} / {ledger_lines_after}"
          f"   {'OK — nothing recorded' if ledger_lines_before == ledger_lines_after else 'FAIL — A TRIAL WAS RECORDED'}")
    print(f"  reproduced sharpe           {got:.6f}   (published {PUBLISHED_SHARPE:.6f}, delta {delta:+.6f})")
    print(f"  vol_ann {float(result.summary.vol_ann):.4f}   max_dd {float(result.summary.max_dd):.4f}")
    if ledger_lines_before != ledger_lines_after:
        raise SystemExit("ABORT: the re-run wrote to the global trial ledger. The zero-trial claim is void.")
    if abs(delta) > REPRO_TOL:
        print()
        print("  *** REPRODUCTION FAILED ***  The re-run does not match the number this candidate")
        print("      was killed on. Stage 2 would then be measuring a DIFFERENT strategy than the")
        print("      one the kill log describes. This must be published as a data/engine drift")
        print("      finding before any correlation is quoted.")
    curve = RERUN_DIR / "equity.parquet"
    print(f"  persisted curve             {curve}  ({'exists' if curve.exists() else 'MISSING'})")
    return 0


# ---------------------------------------------------------------------------------------
# Stage 2 -- the pre-registered kill conditions.
# ---------------------------------------------------------------------------------------
def _btc_daily() -> pd.Series:
    import pyarrow.dataset as ds

    t = ds.dataset(BTC_1D, format="parquet").to_table(columns=["ts_open", "close"]).to_pandas()
    s = pd.Series(t["close"].astype(float).values, index=pd.to_datetime(t["ts_open"]).dt.tz_localize(None))
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return np.log(s).diff().dropna()


def _dominance_proxy(ids: list[str], window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.Series:
    """BTC return minus the equal-weight mean return of the alts in the SAME universe.

    The prereg names "a BTC-dominance proxy" without fixing its construction, so the rule is
    fixed here and stated: every non-BTC instrument in the replayed config that has >= 80%
    daily coverage over the test window, equal-weighted. Nothing is hand-picked; a coverage
    rule the analyst could tune after seeing the answer is exactly the hole this closes.
    """
    import pyarrow.dataset as ds

    lo, hi = window
    n_days = max((hi - lo).days, 1)
    alts = [i for i in ids if i != "BINANCE:PERP:BTCUSDT"]
    rets: dict[str, pd.Series] = {}
    for iid in alts:
        part = LAKE_1D / f"instrument_id={iid}"
        if not part.exists():
            continue
        t = ds.dataset(part, format="parquet").to_table(columns=["ts_open", "close"]).to_pandas()
        if t.empty:
            continue
        s = pd.Series(t["close"].astype(float).values, index=pd.to_datetime(t["ts_open"]).dt.tz_localize(None)).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        s = s[(s.index >= lo) & (s.index <= hi)]
        if len(s) < 0.80 * n_days:
            continue
        rets[iid] = np.log(s).diff().dropna()
    if not rets:
        return pd.Series(dtype=float)
    alt_mean = pd.concat(rets, axis=1).mean(axis=1)
    btc = _btc_daily()
    j = pd.concat([btc.rename("btc"), alt_mean.rename("alt")], axis=1).dropna()
    print(f"  [K3] dominance proxy built from {len(rets)} alts with >=80% coverage")
    return (j["btc"] - j["alt"]).rename("dominance")


def _ols_r2(y: pd.Series, X: pd.DataFrame) -> tuple[float, dict[str, float], int]:
    j = pd.concat([y.rename("y"), X], axis=1).dropna()
    if len(j) < 30:
        return float("nan"), {}, int(len(j))
    yv = j["y"].values
    Xv = np.column_stack([np.ones(len(j))] + [j[c].values for c in X.columns])
    beta, *_ = np.linalg.lstsq(Xv, yv, rcond=None)
    resid = yv - Xv @ beta
    ss_res = float((resid**2).sum())
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    coefs = {"const": float(beta[0]), **{c: float(b) for c, b in zip(X.columns, beta[1:], strict=True)}}
    return float(r2), coefs, int(len(j))


def stage_tests() -> int:
    curve_path = RERUN_DIR / "equity.parquet"
    if not curve_path.exists():
        raise SystemExit(f"{curve_path} missing — run --stage rerun first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cand = daily_logret(curve_path)
    sleeves = {k: daily_logret(p) for k, p in SLEEVES.items()}
    cand_sr = sharpe(cand)

    print("=" * 88)
    print("STAGE 2 — the pre-registered kill conditions (K1 -> K4, in the declared order)")
    print("=" * 88)
    print(f"  candidate      {len(cand)} daily returns, {cand.index[0].date()} -> {cand.index[-1].date()}, sharpe {cand_sr:+.3f}")
    for k, s in sleeves.items():
        print(f"  {k:<30} {len(s):>5} days, {s.index[0].date()} -> {s.index[-1].date()}, sharpe {sharpe(s):+.3f}")

    results: dict[str, dict] = {}
    verdicts: list[tuple[str, str, str]] = []  # (gate, PASS/KILL/INCONCLUSIVE, reason)

    # --- K1: correlation to the equal-risk book -----------------------------------------
    book = equal_risk_returns(sleeves)
    chosen, rows = lag_table(cand, book)
    overlap_at_chosen = chosen["n_days"]
    k1_kill = (not math.isnan(chosen["rho"])) and chosen["rho"] > K1_BOOK_CORR_KILL
    k1_enough = overlap_at_chosen >= K1_MIN_OVERLAP_DAYS
    results["K1_book_corr"] = {
        "rho_at_chosen_lag": chosen["rho"], "chosen_lag": chosen["lag"],
        "n_overlap_days": overlap_at_chosen, "min_days_required": K1_MIN_OVERLAP_DAYS,
        "threshold_kill_above": K1_BOOK_CORR_KILL, "lag_table": rows,
        "book_sharpe": sharpe(book),
    }
    print("-" * 88)
    print(f"  K1  rho(candidate, equal-risk book)   lag table: " +
          "  ".join(f"L={r['lag']:+d}: {r['rho']:+.4f} (n={r['n_days']})" for r in rows))
    print(f"      chosen lag {chosen['lag']:+d}  rho {chosen['rho']:+.4f}  overlap {overlap_at_chosen} days"
          f"  (need >= {K1_MIN_OVERLAP_DAYS})")
    if not k1_enough:
        verdicts.append(("K1", "INCONCLUSIVE", f"only {overlap_at_chosen} overlapping days, prereg requires >= {K1_MIN_OVERLAP_DAYS}"))
    else:
        verdicts.append(("K1", "KILL" if k1_kill else "PASS", f"rho {chosen['rho']:+.4f} vs kill-above {K1_BOOK_CORR_KILL}"))

    # --- K2: the costume test ------------------------------------------------------------
    carry = sleeves[COSTUME_TARGET]
    c2, rows2 = lag_table(cand, carry)
    k2_kill = (not math.isnan(c2["rho"])) and c2["rho"] > K2_COSTUME_CORR_KILL
    results["K2_costume"] = {
        "vs": COSTUME_TARGET, "rho_at_chosen_lag": c2["rho"], "chosen_lag": c2["lag"],
        "n_overlap_days": c2["n_days"], "threshold_kill_above": K2_COSTUME_CORR_KILL,
        "lag_table": rows2,
    }
    print(f"  K2  rho(candidate, {COSTUME_TARGET})   lag table: " +
          "  ".join(f"L={r['lag']:+d}: {r['rho']:+.4f} (n={r['n_days']})" for r in rows2))
    print(f"      chosen lag {c2['lag']:+d}  rho {c2['rho']:+.4f}  (kill above {K2_COSTUME_CORR_KILL})")
    verdicts.append(("K2", "KILL" if k2_kill else "PASS", f"rho {c2['rho']:+.4f} vs kill-above {K2_COSTUME_CORR_KILL}"))

    # --- K3: the single-factor test ------------------------------------------------------
    record = _load_recorded_config()
    ids = list(record["config"]["instrument_ids"])
    btc = _btc_daily()
    dom = _dominance_proxy(ids, (cand.index[0], cand.index[-1]))
    X = pd.concat([btc.rename("btc"), dom], axis=1)
    r2, coefs, n_reg = _ols_r2(cand, X)
    r2_btc_only, coefs_btc, _ = _ols_r2(cand, btc.rename("btc").to_frame())
    k3_kill = (not math.isnan(r2)) and r2 > K3_R2_KILL
    results["K3_single_factor"] = {
        "r2_btc_plus_dominance": r2, "r2_btc_only": r2_btc_only, "n_days": n_reg,
        "coefficients": coefs, "threshold_kill_above": K3_R2_KILL,
        "dominance_proxy": "BTC daily log return minus equal-weight mean of config alts with >=80% coverage",
    }
    print(f"  K3  R^2 on [BTC, dominance] = {r2:.4f}   (BTC alone {r2_btc_only:.4f}, n={n_reg} days, kill above {K3_R2_KILL})")
    print(f"      betas: " + "  ".join(f"{k}={v:+.4f}" for k, v in coefs.items()))
    verdicts.append(("K3", "KILL" if k3_kill else "PASS", f"R^2 {r2:.4f} vs kill-above {K3_R2_KILL}"))

    # --- K4: contribution ----------------------------------------------------------------
    # Declared basis: "using measured rho and Sharpe, compute the book-Sharpe contribution at
    # equal weight" -> the analytic S = s_bar * sqrt(N_eff). The empirical recombination is
    # reported alongside as a cross-check; if the two disagree in SIGN that is itself a finding.
    frame3 = pd.concat(sleeves, axis=1).dropna()
    s_bar3 = float(np.mean([sharpe(frame3[c]) for c in frame3.columns]))
    rho3 = mean_pairwise_corr(frame3)
    lag4 = chosen["lag"] or 0
    with_cand = {**sleeves, "candidate (lowvol_720)": cand.shift(-lag4)}
    frame4 = pd.concat(with_cand, axis=1).dropna()
    s_bar4 = float(np.mean([sharpe(frame4[c]) for c in frame4.columns]))
    rho4 = mean_pairwise_corr(frame4)
    s3 = book_sharpe_analytic(s_bar3, rho3, 3)
    s4 = book_sharpe_analytic(s_bar4, rho4, 4)
    contribution = s4 - s3
    emp3 = sharpe(equal_risk_returns({k: frame3[k] for k in frame3.columns}))
    emp4 = sharpe(equal_risk_returns({k: frame4[k] for k in frame4.columns}))
    k4_kill = contribution < K4_MIN_CONTRIBUTION
    results["K4_contribution"] = {
        "analytic": {"s_bar_3": s_bar3, "rho_bar_3": rho3, "book_sharpe_3": s3,
                     "s_bar_4": s_bar4, "rho_bar_4": rho4, "book_sharpe_4": s4,
                     "contribution": contribution},
        "empirical_crosscheck": {"book_sharpe_3": emp3, "book_sharpe_4": emp4,
                                 "contribution": emp4 - emp3, "n_days": int(len(frame4))},
        "threshold_kill_below": K4_MIN_CONTRIBUTION, "n_common_days_3": int(len(frame3)),
    }
    print(f"  K4  analytic   3 sleeves: s_bar {s_bar3:.3f}  rho_bar {rho3:+.4f}  S {s3:.3f}")
    print(f"                 +candidate: s_bar {s_bar4:.3f}  rho_bar {rho4:+.4f}  S {s4:.3f}")
    print(f"      contribution {contribution:+.4f}   (kill below +{K4_MIN_CONTRIBUTION})")
    print(f"      empirical cross-check: {emp3:.3f} -> {emp4:.3f}  ({emp4 - emp3:+.4f}, n={len(frame4)} common days)")
    verdicts.append(("K4", "KILL" if k4_kill else "PASS", f"contribution {contribution:+.4f} vs kill-below +{K4_MIN_CONTRIBUTION}"))

    # --- verdict --------------------------------------------------------------------------
    print("=" * 88)
    first_fail = next((v for v in verdicts if v[1] != "PASS"), None)
    for gate, status, reason in verdicts:
        print(f"  {gate}  {status:<13} {reason}")
    print("  K5  OUTSTANDING   venue reality (Binance-built, Binance unreachable) — a deployment")
    print("                    gate, not a measurement. Never evaluated here.")
    if first_fail is None:
        overall = "SURVIVES K1-K4"
        note = ("Enters at 10% of full weight on the probation ladder ONLY after K5. Its DSR is "
                "0.04 and that does not change; it is never described as cleared.")
    elif first_fail[1] == "KILL":
        overall = f"KILLED at {first_fail[0]}"
        note = "A candidate that fails a pre-registered test is not re-tested on a different axis."
    else:
        overall = f"INCONCLUSIVE at {first_fail[0]}"
        note = "The declared minimum sample was not available; no pass may be claimed."
    print("-" * 88)
    print(f"  VERDICT: {overall}")
    print(f"  {note}")
    print("=" * 88)

    payload = {
        "prereg": "docs/design/PREREG_CRYPTO_LOWVOL_REOPEN.md",
        "candidate": "crypto_lowvol_720",
        "candidate_sharpe_reproduced": cand_sr,
        "candidate_sharpe_published": PUBLISHED_SHARPE,
        "gates": results,
        "verdicts": [{"gate": g, "status": s, "reason": r} for g, s, r in verdicts],
        "K5_venue_reality": "OUTSTANDING — deployment gate, not evaluated",
        "overall": overall,
        "note": note,
    }
    (OUT_DIR / "result.json").write_text(json.dumps(payload, indent=2, default=float) + "\n")
    print(f"  written: {OUT_DIR / 'result.json'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_lowvol720_reopen")
    ap.add_argument("--stage", choices=("rerun", "tests"), required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    return stage_rerun() if a.stage == "rerun" else stage_tests()


if __name__ == "__main__":
    raise SystemExit(main())
