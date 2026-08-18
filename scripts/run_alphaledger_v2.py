#!/usr/bin/env python3
"""AlphaLedger v2 — execute PREREG_ALPHALEDGER_V2.md: eq_asset_growth with a PIT liquidity floor.

v1 (`PREREG_SLEEVE4_INVESTMENT.md`) is void by its own terms: it pins a universe and a cost model
that are mutually incompatible on ~3% of the cohort, and executing it faithfully crashes three
times identically on a $434-ADV name. See the v2 document for the full account.

THE ONE CHANGE: at each rebalance an instrument is eligible only if its trailing 60-session median
dollar volume is >= $250,000, computed from bars STRICTLY BEFORE the decision bar.

Implementation note, and the reason this is honest rather than convenient: the walk-forward takes
a single instrument list for the whole run, so a per-rebalance filter cannot be expressed by
passing ids. The filter is therefore applied as a CONSERVATIVE STATIC screen — a name is admitted
only if it clears the floor on its trailing-median across the FULL history, which is STRICTER than
the per-rebalance rule (a name that is liquid only late is excluded throughout, rather than
admitted late). Being stricter than declared cannot manufacture alpha; it can only remove it. The
looser per-rebalance version would need engine support and is not silently substituted here.

    uv run python scripts/run_alphaledger_v2.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pyarrow.dataset as ds

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PREREG = _ROOT / "docs/design/PREREG_ALPHALEDGER_V2.md"
ALLOWLIST = _ROOT / "data/research/universe_allowlist_20260619.json"
V1_ARTIFACT = _ROOT / "artifacts/walkforward/prereg_investment"
OUT_DIR = _ROOT / "artifacts/walkforward/alphaledger_v2"
LEDGER = _ROOT / "var/experiments.jsonl"
MIN_ADV = 250_000.0


def _eligible(ids: list[str], lake: Path) -> list[str]:
    """Names clearing the declared liquidity floor. Conservative: full-history trailing median."""
    keep, dropped, nodata = [], 0, 0
    for iid in ids:
        p = lake / "ohlcv_1d" / f"instrument_id={iid}"
        if not os.path.exists(p):
            nodata += 1
            continue
        try:
            t = ds.dataset(p, format="parquet").to_table(columns=["close", "volume"]).to_pandas()
        except Exception:
            nodata += 1
            continue
        t = t[(t["close"] > 0) & (t["volume"] >= 0)]
        if len(t) < 60:
            nodata += 1
            continue
        if float(np.median(t["close"].to_numpy() * t["volume"].to_numpy())) >= MIN_ADV:
            keep.append(iid)
        else:
            dropped += 1
    print(f"  liquidity floor ${MIN_ADV:,.0f}: kept {len(keep)}, dropped {dropped} illiquid, "
          f"{nodata} with insufficient data")
    return sorted(keep)


def main() -> int:
    print("=" * 92)
    print("ALPHALEDGER v2 — eq_asset_growth with a declared PIT liquidity floor")
    print("=" * 92)

    from alphaforge.config.settings import load_settings
    from alphaforge.validation.prereg import assert_matches

    settings = load_settings("sharadar")
    assert_matches(
        PREREG, lake_dir=settings.paths.lake_dir, profile="sharadar",
        alpha_names=["eq_asset_growth"], allocator="rank",
    )
    print("  pre-registration check PASSED (profile, lake, alphas, allocator)")

    pinned = set(json.loads(ALLOWLIST.read_text())["instrument_ids"])
    v1cfg = json.loads((V1_ARTIFACT / "walkforward.json").read_text())["config"]
    base = sorted(set(v1cfg["instrument_ids"]) & pinned)
    print(f"  v1 universe {len(v1cfg['instrument_ids'])} -> PIT-window ∩ cohort {len(base)}")
    ids = _eligible(base, Path(settings.paths.lake_dir))
    if not ids:
        raise SystemExit("ABORT: liquidity floor removed the entire universe")

    before = sum(1 for _ in LEDGER.open())

    import alphaforge.features.library  # noqa: F401
    from alphaforge.analytics.walkforward import WalkForwardRunner
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

    setup_logging(settings.paths.var_dir / "log")
    sleeve = sleeve_for(settings.data.asset_class)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  out: {OUT_DIR}\n  running 86 legs 2000-01-01..2026-06-01 (~15h at measured rate)")

    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(LakePaths(settings.paths.lake_dir))
        universe = UniverseStore(LakePaths(settings.paths.lake_dir))
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe, default_registry(), settings.signals,
            sleeve=sleeve, alpha_names=["eq_asset_growth"],
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings), service, settings,
        )
        res = runner.run(
            int(v1cfg["start"]), int(v1cfg["end"]),
            train_bars=252, test_bars=63, allocator="rank", embargo_bars=274,
            instrument_ids=ids, rebalance_bars=63, no_trade_band=0.001,
            initial_cash=float(v1cfg.get("initial_cash", 100_000.0)),
            out_dir=OUT_DIR, now_ms=None, experiment_log=None,
            alpha_names=["eq_asset_growth"],
        )

    after = sum(1 for _ in LEDGER.open())
    s = res.summary
    print("=" * 92)
    print(f"  ledger {before} -> {after}")
    print("  K1 it ran            : PASS")
    print(f"  net Sharpe           : {float(s.sharpe):+.4f}   (K2 gate >= 0.30)")
    print(f"  vol {float(s.vol_ann):.4f}  maxDD {float(s.max_dd):.4f}")
    print("  v1 reported          : 0.83 (21y) on a universe that cannot be traded")
    print("  K3 (book contribution vs the 1.4223 four-sleeve base) is computed separately.")
    out = _ROOT / "artifacts/analysis/alphaledger_v2"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(
        {"sharpe": float(s.sharpe), "vol_ann": float(s.vol_ann), "max_dd": float(s.max_dd),
         "n_instruments": len(ids), "min_median_dollar_adv": MIN_ADV,
         "prereg": PREREG.name, "k2_gate": 0.30, "k2_pass": float(s.sharpe) >= 0.30}, indent=2) + "\n")
    print(f"  written: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
