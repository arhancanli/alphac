#!/usr/bin/env python3
"""Experiment #1 — crypto MOMENTUM vs CARRY sleeve decorrelation.

The cheapest, highest-information null in the strategy roadmap: does isolating a
crypto MOMENTUM sleeve give a return stream decorrelated from the deployed crypto
CARRY sleeve? It uses ONLY already-registered factors and existing lake data — zero
new data, zero new factors.

Build two standalone, dollar-neutral, net-of-cost crypto sleeves over a purged
walk-forward (train365 / test91 / embargo168, rank allocator, 72h rebalance, 30bp
no-trade band), equal-risk-combine them, and measure:
  - each sleeve's standalone net Sharpe + deflated Sharpe (DSR),
  - the full-sample correlation between the two sleeve curves,
  - the equal-risk combined two-sleeve Sharpe vs the decorrelated ceiling,
  - the STRESS correlation on the worst-2.5% days (book + per-sleeve union),

The decision rule the roadmap pre-committed: only if the carry/momentum correlation
is low (<0.3 calm AND not blowing out in stress) AND momentum's standalone deflated
Sharpe is non-trivially positive does it justify pre-registering ONE crypto-momentum
sleeve trial against the global N budget. Otherwise: publish the null, spend no slot.

TRIAL-COUNT HONESTY: this writes to its OWN ledger under the run dir (a MEASUREMENT,
not a deploy trial). If any sleeve here later becomes a deploy candidate, that trial
must be counted in the global experiments.log funnel — these measurement runs do not
pre-spend the deploy DSR budget, but they ARE auditable here.

Modeled byte-for-byte on scripts/grand_backtest.py::_run_one_config wiring.
Usage: exp1_crypto_decorr.py [--smoke] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""
# ruff: noqa: E402, E501  (sys.path bootstrap before imports; long metric-dict literals)
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import numpy as np

_LOG = logging.getLogger("exp1")

CARRY = ["carry_fund_21", "carry_fund_90", "carry_z_252", "carry_mom_21_63"]
MOM = ["mom_xs_504_48", "mom_xs_2160_168", "mom_ts_504"]

_BARS_PER_DAY = 24  # H1 grid
_REBALANCE_BARS = 72
_NO_TRADE_BAND = 0.0003  # ~30bp
_INITIAL_CASH = 100_000.0
_EMBARGO_BARS = 168


def _run_sleeve(settings, name, alpha_names, window, train_days, test_days, out_dir, now, ledger):
    """Build the per-sleeve wiring (the grand_backtest template) and run the WF."""
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    paths = LakePaths(settings.paths.lake_dir)
    start, end = window
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe),
            universe,
            default_registry(),
            settings.signals,
            alpha_names=alpha_names,
        )
        runner = WalkForwardRunner(
            reader, store, universe,
            TransactionCostModel.from_settings(settings),
            service, settings,
        )
        _LOG.info("[%s] running WF on %s ..", name, alpha_names)
        result = runner.run(
            start, end,
            train_bars=train_days * _BARS_PER_DAY,
            test_bars=test_days * _BARS_PER_DAY,
            allocator="rank",
            embargo_bars=_EMBARGO_BARS,
            initial_cash=_INITIAL_CASH,
            rebalance_bars=_REBALANCE_BARS,
            no_trade_band=_NO_TRADE_BAND,
            out_dir=out_dir,
            now_ms=now,
            alpha_names=alpha_names,
            experiment_log=ledger,
        )
    sr = float(result.summary.sharpe)
    dsr = float(result.validation.dsr) if result.validation else None
    _LOG.info("[%s] sharpe=%.3f vol=%.3f dsr=%s", name, sr, float(result.summary.vol_ann), dsr)
    return result


def _stress_corr(rets_a, rets_b, ref, pct=2.5):
    """Correlation of two daily-return series on the worst `pct`% days of `ref`."""
    if ref.size < 5:
        return float("nan")
    thr = np.nanpercentile(ref, pct)
    mask = ref <= thr
    a, b = rets_a[mask], rets_b[mask]
    if a.size < 2 or a.std() < 1e-12 or b.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="exp1_crypto_decorr")
    ap.add_argument("--smoke", action="store_true", help="short window + small legs to prove the wiring fast")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401  register the factor library
    from alphaforge.config.settings import load_settings
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.portfolio.book import SleeveCurve, combine_book
    from alphaforge.validation.experiments import ExperimentLog

    if a.smoke:
        start_iso, end_iso, train_days, test_days = (a.start or "2024-09-01"), (a.end or "2026-06-01"), 180, 60
    else:
        start_iso, end_iso, train_days, test_days = (a.start or "2021-01-01"), (a.end or "2026-06-01"), 365, 91

    now = now_ms()
    run_ts = datetime.fromtimestamp(now / 1000.0, tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out_root = Path("artifacts/exp1") / (("smoke_" if a.smoke else "") + run_ts)
    out_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(out_root / "exp1.log", encoding="utf-8")])
    _LOG.info("exp1 run_ts=%s smoke=%s window=[%s,%s) train=%d test=%d",
              run_ts, a.smoke, start_iso, end_iso, train_days, test_days)

    settings = load_settings(None)
    req = (parse_utc(f"{start_iso}T00:00:00Z"), parse_utc(f"{end_iso}T00:00:00Z"))
    # clamp to the real clean lake range (reuse the grand_backtest probe)
    try:
        from grand_backtest import _probe_clean_window

        from alphaforge.core.instruments import InstrumentStore
        from alphaforge.data.store.lake import LakePaths
        from alphaforge.data.store.reader import PITDataReader
        from alphaforge.data.universe.store import UniverseStore
        with InstrumentStore(settings.paths.var_dir / "ops.sqlite"):
            window = _probe_clean_window(
                UniverseStore(LakePaths(settings.paths.lake_dir)),
                PITDataReader(LakePaths(settings.paths.lake_dir)), req, as_of=now)
        _LOG.info("probed clean window: [%s, %s)",
                  datetime.fromtimestamp(window[0]/1000, UTC).date(),
                  datetime.fromtimestamp(window[1]/1000, UTC).date())
    except Exception as e:
        _LOG.warning("probe failed (%s); using requested window verbatim", e)
        window = req

    ledger = ExperimentLog(out_root / "experiments.jsonl")  # OWN ledger (measurement, not deploy)
    carry = _run_sleeve(settings, "carry", CARRY, window, train_days, test_days, out_root / "carry", now, ledger)
    mom = _run_sleeve(settings, "momentum", MOM, window, train_days, test_days, out_root / "momentum", now, ledger)

    # equal-risk combine on the raw net-of-cost curves (combine_book does the risk-balancing)
    sc = [SleeveCurve("carry", carry.equity.index.to_list(), carry.equity.to_list()),
          SleeveCurve("momentum", mom.equity.index.to_list(), mom.equity.to_list())]
    book = combine_book(sc, scheme="equal_risk", trading_days=365)
    cr, mr, br = book.sleeve_returns["carry"], book.sleeve_returns["momentum"], book.book_returns
    union_ref = np.minimum(cr, mr)  # a day is "stress" if EITHER sleeve is deep in its tail

    metrics = {
        "run_ts": run_ts, "smoke": a.smoke,
        "window": {"start": str(datetime.fromtimestamp(window[0]/1000, UTC).date()),
                   "end": str(datetime.fromtimestamp(window[1]/1000, UTC).date())},
        "carry": {"sharpe": float(carry.summary.sharpe), "vol_ann": float(carry.summary.vol_ann),
                  "dsr": float(carry.validation.dsr) if carry.validation else None},
        "momentum": {"sharpe": float(mom.summary.sharpe), "vol_ann": float(mom.summary.vol_ann),
                     "dsr": float(mom.validation.dsr) if mom.validation else None},
        "combined": {
            "sharpe": float(book.sharpe),
            "sharpe_decorrelated_ceiling": float(book.sharpe_theory_uncorr),
            "diversification_ratio": float(book.diversification_ratio),
            "maxdd": float(book.maxdd),
            "corr_full_sample": float(book.corr.get(("carry", "momentum"), float("nan"))),
            "corr_stress_book_worst2.5pct": _stress_corr(cr, mr, br),
            "corr_stress_either_sleeve_worst2.5pct": _stress_corr(cr, mr, union_ref),
            "n_days": int(book.n_days),
        },
        "decision_rule": "spend a deploy slot ONLY if corr_full < 0.3 AND not blowing out in stress AND momentum DSR non-trivially positive; else publish the null.",
        "ledger": "own (measurement); count globally only if a sleeve here becomes a deploy candidate",
    }
    (out_root / "exp1_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    _LOG.info("DONE -> %s/exp1_metrics.json", out_root)
    print(json.dumps(metrics["combined"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
