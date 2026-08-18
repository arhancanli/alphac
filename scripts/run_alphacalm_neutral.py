#!/usr/bin/env python3
"""AlphaCalm, dollar-neutral — execute PREREG_ALPHACALM_NEUTRAL.md.

THE DECOMPOSITION THIS PERFORMS. `crypto_lowvol_720` RAISES the live 3-sleeve book (1.3954 ->
1.4228, +0.0274 — the largest lift of any candidate measured). But it does so while running
+24.5% NET LONG on average, never neutral in any of its 14 legs, and its max drawdown gets WORSE
(-3.43% -> -4.40%). Those two facts together say the lift may be crypto beta rather than a
cross-sectional edge — and the book already buys crypto beta deliberately, disclosed as a +20%
strategic overlay.

So this run splits the +0.0274 into edge and beta. Enforcing dollar-neutrality removes the beta
by construction; whatever Sharpe survives is the edge.

WHY THE TILT EXISTS, in the codebase's own words. portfolio/optimizer.py:368-379 documents that
WITHOUT `dollar_neutral`, "the inverse-vol asymmetry between legs lets a net-dollar tilt leak
(measured -11% net-short on momentum -> ~11% uncompensated variance + a hidden short-beta bet)".
The constraint normalises each leg to equal gross so the net is exactly zero. It is set in
configs/equity.yaml and in NO crypto profile, which is why no crypto sleeve has ever been
constrained. The remedy has been one flag away the whole time.

Reinforcing the beta reading: ranking Binance perps by trailing 30d realised vol at three separate
dates returns BTC, BNB, TRX, XRP, LTC, ETH, ADA, SOL — the MAJORS. "Cross-sectional low-vol" in
crypto is a SIZE ranking, and inverse-vol sizing then over-weights those low-vol majors. That is
the mechanical origin of the net-long tilt.

THIS IS ONE NEW TRIAL. A config change is a new hypothesis. N rises by one. Declared, not hidden.

    uv run python scripts/run_alphacalm_neutral.py
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PREREG = _ROOT / "docs/design/PREREG_ALPHACALM_NEUTRAL.md"
OUT_DIR = _ROOT / "artifacts/walkforward/alphacalm_neutral"
LEDGER = _ROOT / "var/experiments.jsonl"


def _recorded_config() -> dict:
    """The reopened lowvol_720 configuration, read from the ledger rather than retyped."""
    for line in LEDGER.open():
        if "lowvol_720" not in line:
            continue
        d = json.loads(line)
        if d.get("config", {}).get("alpha_names") == ["lowvol_720"]:
            return d["config"]
    raise SystemExit("no lowvol_720 row in the ledger; cannot inherit the declared configuration")


def main() -> int:
    print("=" * 92)
    print("ALPHACALM NEUTRAL — decompose the +0.0274 book lift into edge vs crypto beta")
    print("=" * 92)

    from alphaforge.config.settings import load_settings
    from alphaforge.validation.prereg import assert_matches

    settings = load_settings(None)
    assert_matches(PREREG, lake_dir=settings.paths.lake_dir, profile="base",
                   alpha_names=["lowvol_720"], allocator="rank")
    print("  pre-registration check PASSED")

    cfg = _recorded_config()
    ids = list(cfg["instrument_ids"])
    print(f"  inherited config: {len(ids)} ids, rebalance {cfg['rebalance_bars']}, "
          f"band {cfg['no_trade_band']}, train/test {cfg['train_bars']}/{cfg['test_bars']}")

    # THE ONE CHANGE. optimizer.py:368 normalises each leg to equal gross so the net is exactly 0.
    if not settings.portfolio.dollar_neutral:
        settings = settings.model_copy(
            update={"portfolio": settings.portfolio.model_copy(update={"dollar_neutral": True})}
        )
    print(f"  dollar_neutral = {settings.portfolio.dollar_neutral}  <- THE ONLY CHANGE")

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
    paths = LakePaths(settings.paths.lake_dir)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe, default_registry(), settings.signals,
            sleeve=sleeve, alpha_names=["lowvol_720"],
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings), service, settings,
        )
        res = runner.run(
            int(cfg["start"]), int(cfg["end"]),
            train_bars=int(cfg["train_bars"]), test_bars=int(cfg["test_bars"]),
            allocator=cfg["allocator"], embargo_bars=sleeve.embargo_bars,
            instrument_ids=ids, rebalance_bars=int(cfg["rebalance_bars"]),
            no_trade_band=float(cfg["no_trade_band"]),
            out_dir=OUT_DIR, now_ms=None, experiment_log=None,
            alpha_names=["lowvol_720"],
        )

    after = sum(1 for _ in LEDGER.open())
    s = res.summary
    print("=" * 92)
    print(f"  ledger {before} -> {after}")
    print(f"  net Sharpe (NEUTRAL) : {float(s.sharpe):+.4f}    (K2 gate >= 0.30)")
    print("  long-biased original : +0.523  (365-day annualisation)")
    print(f"  vol {float(s.vol_ann):.4f}  maxDD {float(s.max_dd):.4f}")
    print("  K1 (mean |net| < 5% of gross) and K3 (book contribution) computed separately from")
    print("  the persisted legs — a Sharpe that survives is only meaningful if neutrality BOUND.")
    out = _ROOT / "artifacts/analysis/alphacalm_neutral"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(
        {"sharpe_neutral": float(s.sharpe), "vol_ann": float(s.vol_ann), "max_dd": float(s.max_dd),
         "sharpe_long_biased": 0.523, "k2_gate": 0.30, "k2_pass": float(s.sharpe) >= 0.30,
         "prereg": PREREG.name}, indent=2) + "\n")
    print(f"  written: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
