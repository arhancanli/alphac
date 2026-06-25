#!/usr/bin/env python3
"""Experiment #4 — maker-execution BACKTEST for the live crypto carry sleeve.

Runs the carry sleeve through the SAME purged walk-forward twice: once with the deployed
taker fills (NextOpenFill) and once with the opt-in MakerFill (conservative close-direction
fill rule + adverse-selection chase). The deployed/golden path is untouched — MakerFill is
injected only here via WalkForwardRunner(fill_model_factory=...).

This turns the closed-form EV screen (scripts/exp3_maker_exec_screen.py) into an engine-level
measurement, and adds the one thing the screen could only assume: the REALIZED maker fill
rate (fraction of fills that printed as MAKER liquidity), read straight off the fills log.
The headline is the net-Sharpe uplift = Sharpe(maker) - Sharpe(taker), reported at a sweep of
adverse-selection penalties so the sensitivity is explicit. Own ledger (measurement).

HONESTY: the close-direction fill rule is a deliberate ~50% LOWER BOUND on the true fill rate
(see MakerFill docstring) and adverse selection is punitive — so a positive uplift here is a
conservative floor, and the true production figure depends on live post-only fill logs, never
on this backtest alone. Usage: exp4_maker_exec_backtest.py [--smoke] [--adv 2,5,8]
"""
# ruff: noqa: E501
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

_LOG = logging.getLogger("exp4")

CARRY = ["carry_fund_21", "carry_fund_90", "carry_z_252", "carry_mom_21_63"]
_BARS_PER_DAY = 24
_REBALANCE_BARS = 72
_NO_TRADE_BAND = 0.0003
_INITIAL_CASH = 1_000_000.0
_EMBARGO_BARS = 168


def _run_carry(settings, window, train_days, test_days, out_dir, now, ledger, fill_factory):
    """Run the carry sleeve WF with an optional fill_model_factory (None -> taker baseline)."""
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
            FeatureEngine(reader, store, universe), universe, default_registry(),
            settings.signals, alpha_names=CARRY,
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings),
            service, settings, fill_model_factory=fill_factory,
        )
        result = runner.run(
            start, end,
            train_bars=train_days * _BARS_PER_DAY, test_bars=test_days * _BARS_PER_DAY,
            allocator="rank", embargo_bars=_EMBARGO_BARS, initial_cash=_INITIAL_CASH,
            rebalance_bars=_REBALANCE_BARS, no_trade_band=_NO_TRADE_BAND,
            out_dir=out_dir, now_ms=now, alpha_names=CARRY, experiment_log=ledger,
        )
    return result


def _maker_fill_rate(result):
    """Fraction of OOS fills that printed as MAKER liquidity (the empirical fill rate)."""
    fills = result.fills
    if fills is None or len(fills) == 0 or "liquidity" not in fills.columns:
        return None, 0
    liq = fills["liquidity"].astype(str).str.lower()
    return float((liq == "maker").mean()), len(fills)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="exp4_maker_exec_backtest")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--adv", default="2,5,8", help="adverse-selection bps sweep, comma-separated")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401
    from alphaforge.backtest import MakerFill
    from alphaforge.config.settings import load_settings
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.validation.experiments import ExperimentLog

    if a.smoke:
        start_iso, end_iso, train_days, test_days = (a.start or "2025-01-01"), (a.end or "2026-01-01"), 120, 45
    else:
        start_iso, end_iso, train_days, test_days = (a.start or "2024-06-01"), (a.end or "2026-06-01"), 365, 91
    adv_list = [float(x) for x in a.adv.split(",") if x.strip()]

    now = now_ms()
    run_ts = datetime.fromtimestamp(now / 1000, UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path("artifacts/exp4") / (("smoke_" if a.smoke else "") + run_ts)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(out / "exp4.log", encoding="utf-8")])
    settings = load_settings(None)
    window = (parse_utc(f"{start_iso}T00:00:00Z"), parse_utc(f"{end_iso}T00:00:00Z"))
    ledger = ExperimentLog(out / "experiments.jsonl")  # OWN ledger (measurement)

    _LOG.info("exp4 taker baseline ..")
    taker = _run_carry(settings, window, train_days, test_days, out / "taker", now, ledger, None)
    s_taker = float(taker.summary.sharpe)
    _LOG.info("taker sharpe=%.4f", s_taker)

    maker_runs = {}
    for adv in adv_list:
        _LOG.info("exp4 maker adverse_selection=%.1fbps ..", adv)
        res = _run_carry(settings, window, train_days, test_days, out / f"maker_adv{adv:g}",
                         now, ledger, (lambda cm, _a=adv: MakerFill(cm, adverse_selection_bps=_a)))
        s_maker = float(res.summary.sharpe)
        fill_rate, n_fills = _maker_fill_rate(res)
        maker_runs[f"adv_{adv:g}bps"] = {
            "sharpe": round(s_maker, 4), "uplift_vs_taker": round(s_maker - s_taker, 4),
            "vol_ann": round(float(res.summary.vol_ann), 4),
            "fees_paid": round(float(res.summary.fees_paid), 2),
            "maker_fill_rate": round(fill_rate, 4) if fill_rate is not None else None,
            "n_fills": n_fills,
        }
        _LOG.info("maker adv=%.1f sharpe=%.4f uplift=%+.4f fill_rate=%s",
                  adv, s_maker, s_maker - s_taker, fill_rate)

    metrics = {
        "run_ts": run_ts, "smoke": a.smoke,
        "label": "MAKER-EXEC BACKTEST — opt-in MakerFill vs deployed taker on the carry sleeve; golden path untouched. Close-direction fill rule = conservative ~50% LOWER BOUND; production figure needs live fill logs.",
        "window": {"start": start_iso, "end": end_iso}, "sleeve": "crypto carry", "factors": CARRY,
        "taker_baseline": {"sharpe": round(s_taker, 4), "vol_ann": round(float(taker.summary.vol_ann), 4),
                           "fees_paid": round(float(taker.summary.fees_paid), 2)},
        "maker": maker_runs,
        "decision_rule": "ship maker live ONLY once paper post-only fill logs confirm the fill rate beats break-even at the measured adverse selection; this backtest is a conservative floor, not the production number.",
    }
    (out / "exp4_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    _LOG.info("DONE -> %s/exp4_metrics.json", out)
    print(json.dumps({"taker_sharpe": round(s_taker, 4), "maker": maker_runs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
