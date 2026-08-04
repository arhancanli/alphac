#!/usr/bin/env python3
"""Gauntlet the MANAGED-FUTURES TREND sleeve through the deflated purged walk-forward.

The deploy-grade test for the 4th algorithm: blends mf_trend_63/126/252 through the DIRECTIONAL
`trend` allocator (TrendVolTarget) on the 17-ETF basket (data/lake_mf), net of the committed equity
cost model, with DSR in the result. Managed-futures cadence: monthly rebalance, 2y train / 6m test.
Reports net Sharpe / DSR / vol / maxDD + post-hoc skew & corr-to-SPY (the crash-protection check).

Mirrors scripts/gauntlet_factor.py's proven WalkForwardRunner wiring. Usage:

    mf_gauntlet.py --start 2003-01-01 --out artifacts/sweep/mf_trend
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_ALPHAS = ["mf_trend_63", "mf_trend_126", "mf_trend_252"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mf_gauntlet")
    ap.add_argument("--start", default="2003-01-01")
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--out", default="artifacts/sweep/mf_trend")
    # Small research book: the early-history / lower-ADV ETFs (DBA/UNG/FXY in 2007-09) can't absorb
    # a $1M order without breaching the sqrt-impact model's 5%-of-ADV validity (the backtest path
    # has no pre-trade ADV cap — a known engine gap, the proper fix is an ADV-aware order clamp in
    # discretize). Sharpe is scale-invariant, so a small book gives the cleanest read on the signal
    # (near-zero impact) and is the realistic capacity-respecting size anyway.
    ap.add_argument("--cash", type=float, default=50_000.0)
    ap.add_argument("--alphas", default=",".join(_ALPHAS), help="comma list (diagnostic: single horizon vs blend)")
    ap.add_argument("--rebalance", type=int, default=21)
    ap.add_argument("--profile", default="managed_futures", help="any trend profile (managed_futures, crypto_trend, ...)")
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401  canonical factors
    from alphaforge.research import zoo

    zoo.register_all()  # registers mf_trend_63/126/252

    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
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
    start, end = parse_utc(f"{a.start}T00:00:00Z"), parse_utc(f"{a.end}T00:00:00Z")
    now = now_ms()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # Bars-per-day by sleeve: crypto perps are H1 (24/7), equity/ETF are D1. The walk-forward window
    # sizes scale with it so train/test/embargo span the same wall-clock on either sleeve.
    is_crypto = settings.data.asset_class.value == "crypto_perp"
    bpd = 24 if is_crypto else 1
    train_bars = (365 * bpd) if is_crypto else 504
    test_bars = (91 * bpd) if is_crypto else 126
    embargo_bars = (168) if is_crypto else 21  # 7d crypto / 21 sessions equity

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        alphas = a.alphas.split(",")
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe, default_registry(), settings.signals, alpha_names=alphas,
            sleeve=sleeve_for(settings.data.asset_class),  # resolve the sleeve from the profile
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings), service, settings,
        )
        result = runner.run(
            start, end, train_bars=train_bars, test_bars=test_bars, allocator="trend",
            embargo_bars=embargo_bars, initial_cash=a.cash, rebalance_bars=a.rebalance,
            no_trade_band=0.0010, out_dir=out, now_ms=now, alpha_names=alphas,
        )

    s = result.summary
    dsr = float(result.validation.dsr) if result.validation else None
    # post-hoc skew + corr-to-SPY from the book's daily equity curve
    skew = corr_spy = float("nan")
    try:
        eq = pd.read_parquet(out / "equity.parquet")
        eqs = eq.set_index("ts")["equity"] if "ts" in eq.columns else eq.iloc[:, -1]
        ret = np.log(eqs.astype(float)).diff().dropna()
        skew = float(((ret - ret.mean()) ** 3).mean() / ret.std(ddof=0) ** 3)
        spy = pd.read_parquet(next((Path("data/lake_mf/ohlcv_1d") / "instrument_id=XUSE:CASH:SPYUSD").glob("**/*.parquet")))
        spy_ret = np.log(spy.sort_values("ts_open").set_index("ts_open")["close"].astype(float)).diff()
        spy_ret.index = pd.to_datetime(spy_ret.index, unit="ms")
        a2, b2 = ret.reset_index(drop=True), None
        # align on date
        rd = pd.Series(ret.values, index=pd.to_datetime(eqs.index[1:], unit="ms") if np.issubdtype(np.asarray(eqs.index).dtype, np.number) else eqs.index[1:])
        j = pd.concat([rd.rename("b"), spy_ret.rename("s")], axis=1).dropna()
        if len(j) > 30:
            corr_spy = float(np.corrcoef(j["b"], j["s"])[0, 1])
    except Exception as e:  # noqa: BLE001
        print(f"(skew/corr post-hoc failed: {str(e)[:80]})")

    print("\n================ MANAGED-FUTURES TREND — GAUNTLET ================")
    print(f"  window      : {a.start} .. {a.end}   (monthly rebalance, 2y train / 6m test)")
    print(f"  net Sharpe  : {float(s.sharpe):.3f}")
    print(f"  DSR         : {dsr}")
    print(f"  ann vol     : {float(s.vol_ann):.3f}")
    print(f"  max DD      : {float(s.max_dd):.3f}")
    print(f"  sortino     : {float(s.sortino):.3f}")
    print(f"  skew        : {skew:.2f}   (trend should be >~0 — the crash-protection signature)")
    print(f"  corr to SPY : {corr_spy:+.2f}   (want ~0 / negative — diversifies the book)")
    print(f"  CAGR        : {float(s.cagr):.3f}")
    print(f"  artifacts   : {out}")
    print("=================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
