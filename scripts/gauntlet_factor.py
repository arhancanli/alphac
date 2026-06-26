#!/usr/bin/env python3
"""Gauntlet ONE factor (canonical OR zoo) through the deflated walk-forward for a profile.

`af research walkforward` only sees the deployed library, so it errors on research-zoo factors
(eq_mom_63_42, eq_maxret_21, carry_fund_7, ...). This loads the zoo first, then runs the SAME
WalkForwardRunner the CLI uses — net of the committed cost model, with DSR/skew in the result.
Modeled on the proven scripts/exp4 wiring. Usage:

    gauntlet_factor.py --profile sharadar --alpha eq_mom_63_42 --start 2012-01-01 --out artifacts/sweep/g_eq_mom_63_42
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gauntlet_factor")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--alpha", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401  canonical factors
    from alphaforge.research import zoo

    zoo.register_all()  # THE fix: register the research zoo so the runner can resolve zoo alphas

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
    is_crypto = settings.data.asset_class.value == "crypto_perp"
    bpd = 24 if is_crypto else 1  # H1 vs D1 bars per day
    rebalance = 72 if is_crypto else 63
    embargo = 168 if is_crypto else 63
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
            start, end, train_bars=365 * bpd, test_bars=91 * bpd, allocator="rank",
            embargo_bars=embargo, initial_cash=1_000_000.0, rebalance_bars=rebalance,
            no_trade_band=0.0003, out_dir=out, now_ms=now, alpha_names=[a.alpha],
        )
    dsr = float(result.validation.dsr) if result.validation else None
    print(f"{a.alpha}: net_sharpe={float(result.summary.sharpe):.3f} dsr={dsr} "
          f"vol={float(result.summary.vol_ann):.3f} maxdd={float(result.summary.max_dd):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
