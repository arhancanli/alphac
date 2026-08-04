#!/usr/bin/env python3
"""PROBE: residual (idiosyncratic) momentum for the ALPHAMAX equity sleeve.

Blitz-Huij-Martens (2011) / Hanauer-Windmueller (JBF 2023) residual momentum, adapted to
the D1 session grid and this repo's finite-window equity contract:

    r_t     = ln(C*_t / C*_{t-1})                     # PIT split-adjusted close panel
    m_t     = equal-weight PIT-universe daily market return
    beta_it = rolling Cov/Var beta over `beta_window` sessions, strictly through t-1
              (the SAME rolling_beta the canonical eq_beta_252 / eq_rev_resid_21 use)
    eps_it  = r_it - beta_it * m_t                    # intercept deliberately excluded,
                                                      # exactly as BHM do (residuals keep
                                                      # their alpha drift) and exactly as
                                                      # the shipped eq_rev_resid_21 does
    signal  = sum(eps over sessions t-251..t-21) / std(eps over the same window)
              (12-1 formation; per-stock residual-vol scaling is PART of the BHM recipe)

Everything is reused from the committed library (rolling_beta / market_return /
_member_mask / _roll_sum / _roll_var / _adjusted_close_panel / log_returns), so PIT and
no-gap-bridging semantics are inherited, not re-invented. Finite window throughout.
Research-only: specs are registered in-process (zoo pattern); nothing in
src/alphaforge/** or configs/** is touched, the deployed registry count is unchanged.

Funnel discipline (docs/design/PRE_REGISTRATION.md + the zoo_screen protocol):

  1. `screen`  — Rank-IC screen (free-ish; does NOT append to the walk-forward trial
     ledger, same as scripts/zoo_screen.py which screened 223 factors ledger-free).
     Screens the pre-registered BHM recipe + 2 declared ablations NEXT TO the canonical
     eq_mom_252_21 in the same pass, same lake, same horizon (the pre-registered h=63).
  2. `gauntlet` — full deflated walk-forward for ONE factor via the SAME WalkForwardRunner
     the CLI uses. This DOES append to var_sharadar/experiments.jsonl automatically
     (WalkForwardRunner.run -> ExperimentLog) and the DSR is deflated by that ledger's N.
     Harness = the repo's established sharadar gauntlet shape (scripts/gauntlet_factor.py:
     train 365 / test 91 / rebalance 63 / embargo 63 / band 0.0003 / rank / start 2012)
     with ONE documented deviation: initial_cash=100_000 (all blessed equity runs used
     $100k; the $1M in gauntlet_factor.py is the known CostModelMisuse/ADV crash — see
     artifacts/eq_gauntlet.log).
  3. `compare` — net numbers side by side + the OOS daily-return correlation between the
     residual-momentum sleeve and the plain-momentum sleeve (if very high, residual
     momentum is a relabel of the live bet, not an improvement).

Pre-registered decision rule (declared before any number was seen):
  - gauntlet ONLY `eq_resmom_756_252_21` (the canonical BHM recipe), and only if its
    h=63 NW-t is >= max(1.5, the same-pass eq_mom_252_21 t). Ablations are screened for
    attribution but never gauntleted in this campaign (each gauntlet is a scarce trial).
  - the baseline eq_mom_252_21 is gauntleted once in the identical harness so the
    comparison is apples-to-apples (same window, same costs, same allocator, same cash).
  - success = materially better DSR/skew/maxDD at similar-or-better net Sharpe, AND
    return corr to plain momentum well below ~0.9. An honest "no improvement" is a
    full success of the probe.

Usage (repo root, uv):
    uv run python scripts/probe_alphamax_residual.py screen
    uv run python scripts/probe_alphamax_residual.py gauntlet --alpha eq_mom_252_21 \
        --out artifacts/probe/resmom/g_mom_252_21_2012
    uv run python scripts/probe_alphamax_residual.py gauntlet --alpha eq_resmom_756_252_21 \
        --out artifacts/probe/resmom/g_resmom_756_252_21_2012
    uv run python scripts/probe_alphamax_residual.py compare \
        --resmom artifacts/probe/resmom/g_resmom_756_252_21_2012 \
        --baseline artifacts/probe/resmom/g_mom_252_21_2012
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- variants
# (name, beta_window, lookback, skip, vol_scale). The FIRST is the pre-registered
# BHM/HW recipe: ~36-month market-beta estimation window (756 sessions), 12-1 formation
# (sum of residuals over sessions t-251..t-21), scaled by the residual SD of the same
# window. Ablations: no vol scaling (is it the residualization or the scaling?), and a
# 252-session beta window (the eq_beta_252 / eq_rev_resid_21 infrastructure window).
RESMOM_VARIANTS: tuple[tuple[str, int, int, int, bool], ...] = (
    ("eq_resmom_756_252_21", 756, 252, 21, True),
    ("eq_resmom_raw_756_252_21", 756, 252, 21, False),
    ("eq_resmom_252_252_21", 252, 252, 21, True),
)

SCREEN_START = "2003-01-01"  # same span as the blessed zoo_eq98 screen
GAUNTLET_START = "2012-01-01"  # the repo's established sharadar gauntlet start
END = "2026-06-01"


def _resmom_fn(ctx, spec):  # noqa: ANN001, ANN201 - FeatureFn signature
    """Residual 12-1 momentum body (module docstring). Finite-window, PIT.

    Reach honesty (the eq_rev_resid_21 lookback argument): the OLDEST residual in the
    formation window sits at t-(lookback-1); its beta (lagged through its own t-1) uses
    beta_window returns whose oldest consumes the close beta_window+1 rows earlier =>
    lookback_bars = beta_window + lookback + 1.
    """
    from alphaforge.features.context import long_series
    from alphaforge.features.library.equity_price import _adjusted_close_panel, _market_beta
    from alphaforge.features.library.vol import _roll_sum, _roll_var, log_returns

    adj_close = _adjusted_close_panel(ctx)
    returns = log_returns(adj_close)
    beta = _market_beta(ctx, adj_close, window=int(spec.params["beta_window"]))
    # _market_beta = rolling_beta(returns, equal-weight PIT-member market, window),
    # strictly through t-1; NaN until the window is full (no silently shrunk windows).
    from alphaforge.features.library.equity_price import _member_mask, market_return

    mask = _member_mask(ctx, adj_close.index, [str(c) for c in adj_close.columns])
    mkt = market_return(returns, mask)
    resid = returns.sub(beta.mul(mkt, axis=0))

    lookback = int(spec.params["lookback"])
    skip = int(spec.params["skip"])
    w = lookback - skip  # formation window: 231 sessions for (252, 21)
    arr = resid.to_numpy(dtype="float64")
    rsum = _roll_sum(arr, w)  # min_periods = w: a gap anywhere NaNs the window
    if bool(spec.params["vol_scale"]):
        rvar = _roll_var(arr, w)
        with np.errstate(invalid="ignore", divide="ignore"):
            sig = np.where(rvar > 0.0, rsum / np.sqrt(rvar), np.nan)
    else:
        sig = rsum
    wide = pd.DataFrame(sig, index=returns.index, columns=returns.columns).shift(skip)
    return long_series(wide, name=spec.name)


def _resmom_specs():
    """Build the research FeatureSpecs (registered in-process only, zoo pattern)."""
    from alphaforge.features.spec import Family, FeatureSpec

    specs = []
    for name, beta_window, lookback, skip, vol_scale in RESMOM_VARIANTS:
        specs.append(
            FeatureSpec(
                name=name,
                family=Family.MOMENTUM,
                direction=1,  # higher residual momentum => higher expected return
                cross_sectional=True,  # CS pipeline winsor->z-scores within PIT universe
                lookback_bars=beta_window + lookback + 1,
                params={
                    "beta_window": beta_window,
                    "lookback": lookback,
                    "skip": skip,
                    "vol_scale": vol_scale,
                },
                fn=_resmom_fn,
            )
        )
    return specs


def _register_into_default_registry() -> list[str]:
    """Register the variants into the global registry (needed by SignalService)."""
    import alphaforge.features.library  # noqa: F401  canonical factors first
    from alphaforge.features.registry import default_registry

    reg = default_registry()
    have = {s.name for s in reg.all_specs()}
    added = []
    for spec in _resmom_specs():
        if spec.name not in have:
            reg.register(lambda spec=spec: spec)
            added.append(spec.name)
    return added


# ------------------------------------------------------------------------------ screen
def cmd_screen(a) -> int:
    """Rank-IC screen: the 3 resmom variants + canonical eq_mom_252_21, one pass.

    Ledger-free by protocol (zoo_screen.py precedent). Uses a SCOPED registry so only
    these 4 factors are computed (the engine takes spec objects, not registry names).
    """
    import alphaforge.features.library  # noqa: F401
    from alphaforge.config.settings import load_settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import parse_utc
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.library import equity_price as _eqp
    from alphaforge.features.registry import FeatureRegistry
    from alphaforge.research.ic_report import ICReportRunner

    settings = load_settings(a.profile)
    start = parse_utc(f"{a.start}T00:00:00Z")
    end = parse_utc(f"{a.end}T00:00:00Z")
    horizons = [int(h) for h in a.horizons.split(",") if h.strip()]
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    reg = FeatureRegistry()
    mom_spec = _eqp.eq_mom_252_21()  # the canonical baseline, same pass for parity
    reg.register(lambda: mom_spec)
    for spec in _resmom_specs():
        reg.register(lambda spec=spec: spec)
    names = [s.name for s in reg.all_specs()]
    print(f"screen: {len(names)} factors in scoped registry: {', '.join(names)}")
    print(f"span {a.start} -> {a.end}, horizons {horizons}, profile {a.profile}")
    print("NOTE: IC screens do not append to the WF trial ledger (zoo_screen protocol); "
          "the configs screened here are disclosed in the campaign report instead.")

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as instruments:
        runner = ICReportRunner(
            FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths),
                          asset_class=settings.data.asset_class),
            PITDataReader(paths),
            UniverseStore(paths),
            reg,
            paths=paths,
            asset_class=settings.data.asset_class,
        )
        runner.run(start=start, end=end, horizons=horizons, out_dir=out_dir)

    rep = json.loads((out_dir / "ic_report.json").read_text())
    print("\n=== Rank-IC (NW t) — residual momentum vs plain 12-1, same pass ===")
    print(f"{'factor':<28}{'h':>4}{'NW t':>8}{'mean_IC':>10}{'IC_IR':>8}{'hit':>6}{'n':>6}")
    for r in sorted(rep.get("rows", []), key=lambda r: (int(r["horizon"]), r["factor"])):
        print(f"{r['factor']:<28}{int(r['horizon']):>4}{float(r.get('t_nw') or 0):>8.2f}"
              f"{float(r.get('mean_ic') or 0):>10.4f}{float(r.get('ic_ir') or 0):>8.3f}"
              f"{float(r.get('hit_rate') or 0):>6.2f}{int(r.get('n_obs') or 0):>6}")
    print(f"\nfull report: {out_dir / 'ic_report.json'}")
    return 0


# ---------------------------------------------------------------------------- gauntlet
def cmd_gauntlet(a) -> int:
    """Deflated walk-forward for ONE factor (canonical or probe), sharadar harness.

    Identical wiring to scripts/gauntlet_factor.py (the SAME WalkForwardRunner the CLI
    uses; trial auto-appended to <var_dir>/experiments.jsonl; DSR deflated by that
    ledger's N) with initial_cash=100_000 — the blessed cash level; $1M is the known
    ADV-ceiling crash on thin Sharadar small-caps.
    """
    added = _register_into_default_registry()
    print(f"registered probe factors: {added or '(already present)'}")

    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    settings = load_settings(a.profile)
    if settings.data.asset_class.value == "crypto_perp":
        raise SystemExit("this probe is equity-only; use --profile sharadar")
    start, end = parse_utc(f"{a.start}T00:00:00Z"), parse_utc(f"{a.end}T00:00:00Z")
    now = now_ms()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe, default_registry(), settings.signals, alpha_names=[a.alpha],
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings), service, settings,
        )
        result = runner.run(
            start, end, train_bars=365, test_bars=91, allocator="rank",
            embargo_bars=63, initial_cash=100_000.0, rebalance_bars=63,
            no_trade_band=0.0003, out_dir=out, now_ms=now, alpha_names=[a.alpha],
        )
    s, v = result.summary, result.validation
    dsr = float(v.dsr) if v else float("nan")
    ntr = int(v.n_trials_used) if v else -1
    print(f"\n{a.alpha}: NET sharpe={float(s.sharpe):.3f} dsr={dsr:.4f} (n_trials_used={ntr}) "
          f"psr={float(v.psr):.3f} vol={float(s.vol_ann):.3f} maxdd={float(s.max_dd):.3f} "
          f"cagr={float(s.cagr):.3f} turnover={float(s.turnover_ann):.2f} n_days={int(s.n_days)}")
    print(f"artifact: {out} | ledger: {v.ledger_path if v else '?'}")
    return 0


# ----------------------------------------------------------------------------- compare
def _load_run(out_dir: str) -> dict:
    d = Path(out_dir)
    wf = json.loads((d / "walkforward.json").read_text())
    s, v = wf.get("summary", {}), wf.get("validation", {})
    rets = None
    eq_path = d / "equity.parquet"
    if eq_path.exists():
        e = pd.read_parquet(eq_path)
        idx = pd.to_datetime(e["ts"], unit="ms", utc=True) if "ts" in e.columns else None
        rets = pd.Series(e["equity"].to_numpy(dtype="float64"), index=idx).pct_change().dropna()
    skew = kurt = float("nan")
    if rets is not None and len(rets) > 10:
        z = (rets - rets.mean()) / rets.std(ddof=0)
        skew, kurt = float((z**3).mean()), float((z**4).mean())
    return {
        "sharpe": float(s.get("sharpe", float("nan"))),
        "dsr": float(v.get("dsr", float("nan"))),
        "psr": float(v.get("psr", float("nan"))),
        "n_trials_used": v.get("n_trials_used"),
        "vol": float(s.get("vol_ann", float("nan"))),
        "maxdd": float(s.get("max_dd", float("nan"))),
        "cagr": float(s.get("cagr", float("nan"))),
        "turnover": float(s.get("turnover_ann", float("nan"))),
        "n_days": s.get("n_days"),
        "skew": skew,
        "kurt": kurt,
        "rets": rets,
    }


def cmd_compare(a) -> int:
    """Side-by-side NET numbers + OOS daily-return correlation (the relabel test)."""
    rm, bl = _load_run(a.resmom), _load_run(a.baseline)
    print("=" * 100)
    print(f"{'run':<26}{'netSharpe':>10}{'DSR':>8}{'PSR':>8}{'vol':>8}{'maxDD':>8}"
          f"{'CAGR':>8}{'skew':>7}{'kurt':>7}{'turn':>7}{'days':>6}")
    for name, r in (("resmom (BHM 756/252/21)", rm), ("plain eq_mom_252_21", bl)):
        print(f"{name:<26}{r['sharpe']:>10.3f}{r['dsr']:>8.3f}{r['psr']:>8.3f}{r['vol']:>8.3f}"
              f"{r['maxdd']:>8.3f}{r['cagr']:>8.3f}{r['skew']:>7.2f}{r['kurt']:>7.1f}"
              f"{r['turnover']:>7.2f}{r['n_days']!s:>6}")
    print("=" * 100)
    if rm["rets"] is not None and bl["rets"] is not None:
        joined = pd.concat([rm["rets"], bl["rets"]], axis=1, keys=["resmom", "mom"]).dropna()
        corr = float(joined["resmom"].corr(joined["mom"]))
        print(f"OOS daily-return correlation resmom vs plain momentum: {corr:.3f} "
              f"({len(joined)} overlapping days)")
        print("reading: >~0.9 => a relabel of the same bet; the BHM prize would be lower vol /"
              " less-negative skew / smaller maxDD at similar mean, plus corr meaningfully < 1.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="probe_alphamax_residual")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("screen", help="ledger-free Rank-IC screen (variants + baseline)")
    sc.add_argument("--profile", default="sharadar")
    sc.add_argument("--start", default=SCREEN_START)
    sc.add_argument("--end", default=END)
    sc.add_argument("--horizons", default="63,21")
    sc.add_argument("--out", default="data/research/probe_resmom")
    sc.set_defaults(fn=cmd_screen)

    g = sub.add_parser("gauntlet", help="deflated WF for one factor (appends to the ledger)")
    g.add_argument("--profile", default="sharadar")
    g.add_argument("--alpha", required=True)
    g.add_argument("--start", default=GAUNTLET_START)
    g.add_argument("--end", default=END)
    g.add_argument("--out", required=True)
    g.set_defaults(fn=cmd_gauntlet)

    c = sub.add_parser("compare", help="net numbers side by side + return correlation")
    c.add_argument("--resmom", required=True)
    c.add_argument("--baseline", required=True)
    c.set_defaults(fn=cmd_compare)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
