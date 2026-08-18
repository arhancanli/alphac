#!/usr/bin/env python3
"""Re-run the two fundamental factors whose trials were spent and returned NOTHING.

THE DEFECT. `var/experiments.jsonl` holds 134 rows. Exactly TWO have `sharpe_ann: null`:

    row 117  eq_accruals      config_hash 9b161b6c19cd2b6c   n_obs 5384
    row 118  eq_net_issuance  config_hash 6f975d14e246fd87   n_obs 5384

They are not a random pair. They are precisely the two factors of the pre-registered family that
the declaration itself singled out as having real mechanisms rather than being risk premia -
Sloan's accruals accounting identity, and issuance as a forced flow (Pontiff-Woodgate). Both
consumed a trial against the honest N and produced no measurement, and nobody noticed for three
days.

ROOT CAUSE, measured 2026-08-07. Both factors read columns that the lake they ran against does not
have:

    _eq_net_issuance_fn needs  shares_basic, share_factor
    _eq_accruals_fn     needs  op_cash_flow (via the TTM helper)

    data/lake/fundamentals   14 columns - HAS NEITHER
    data/lake_sharadar       22 columns - HAS ALL OF THEM

The family ran under the `equity` profile, whose `lake_dir` is `data/lake`. The other five factors
of the family only touch columns present in BOTH lakes, which is why five produced numbers and two
produced silence. And `configs/sharadar.yaml` line 5 says, in its own words, that it carries "SF1
fundamentals (incl. op_cash_flow) the accruals/issuance/investment factors need".

So the declaration named the right source and the run used the wrong one. From
docs/design/PREREG_FUNDAMENTAL_SINGLES.md: "Fundamentals | Sharadar SF1 lake (frozen 2026-06-20)".

THIS IS NOT A NEW TRIAL. Both config hashes are already counted in the honest N=133. Running the
declared configuration against the declared data source, for the first time, is executing the
pre-registration rather than extending it. `now_ms=None` / `experiment_log=None` keep the ledger
untouched and the row count is asserted before and after.

WHY IT MATTERS. In the fund's own 98-factor screen, eq_net_issuance ranks 5th of 98 (t_nw +3.542,
mean IC +0.0522, the highest of the top eight) while eq_asset_growth - the factor already approved
for deployment as AlphaLedger - scores t_nw +0.829, IC +0.0117. We may be about to deploy the
weaker sibling because the stronger one returned a silent null.

PRICE IT HONESTLY BEFORE READING THE RESULT. In this same repo, eq_gross_profitability screened at
t_nw +2.95 / IC +0.0303 and then printed a walk-forward net Sharpe of -0.263. Screen-to-walkforward
has already failed here once, badly, on a factor from this very family. A high screen t is not a
prediction. Prior: 20-25%.

    uv run python scripts/rerun_null_fundamentals.py
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

LEDGER = _ROOT / "var" / "experiments.jsonl"
#: The columns each factor needs, asserted against the lake BEFORE compute is spent. The whole
#: point of this re-run is that these were missing last time and nothing said so.
REQUIRED = {
    "eq_net_issuance": ["shares_basic", "share_factor"],
    "eq_accruals": ["op_cash_flow", "net_income", "assets"],
}


#: Run order. eq_net_issuance FIRST and eq_accruals second, deliberately.
#:
#: A full walk-forward here measures ~8 data-days per wall-minute, i.e. roughly 15 HOURS for one
#: 2000-2026 pass. Running these alphabetically put the decisive factor behind the closed one and
#: pushed the answer that matters out to ~30 hours. eq_net_issuance is the candidate that may
#: replace AlphaLedger (screen t_nw +3.542 vs +0.829); eq_accruals already screened NEGATIVE
#: (t_nw -0.338, mean IC -0.0027) and the research closed it. Measure the one that can change a
#: decision first; the other is completeness, not a gate.
RUN_ORDER = ["eq_net_issuance", "eq_accruals"]


def _rows() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with LEDGER.open() as fh:
        for line in fh:
            d = json.loads(line)
            names = d.get("config", {}).get("alpha_names") or []
            if len(names) == 1 and names[0] in REQUIRED and d.get("sharpe_ann") is None:
                out[names[0]] = d
    return out


def _assert_columns(lake_dir: Path) -> None:
    """Fail LOUDLY if the lake lacks a needed column. Silence here is the original bug."""
    import glob

    import pyarrow.dataset as ds

    parts = glob.glob(str(lake_dir / "fundamentals" / "**" / "*.parquet"), recursive=True)
    if not parts:
        raise SystemExit(f"ABORT: no fundamentals parquet under {lake_dir}")
    cols = {f.name for f in ds.dataset(parts[0], format="parquet").to_table().schema}
    missing = {k: [c for c in v if c not in cols] for k, v in REQUIRED.items()}
    missing = {k: v for k, v in missing.items() if v}
    if missing:
        raise SystemExit(
            f"ABORT: {lake_dir} is missing required columns {missing}.\n"
            "This is the exact condition that made these two trials return null the first time. "
            "Running anyway would burn hours and produce another silent NaN."
        )
    print(f"  lake {lake_dir} carries every required column ({len(cols)} total)")


def main() -> int:
    print("=" * 92)
    print("RE-RUN THE NULL FUNDAMENTALS — declared config, declared data source, zero new trials")
    print("=" * 92)
    rows = _rows()
    if not rows:
        raise SystemExit("no null-sharpe rows found for these factors; nothing to re-run")
    for name, d in rows.items():
        print(f"  {name:<18} hash {d['config_hash']}  n_obs {d['n_obs']}  sharpe_ann {d['sharpe_ann']}")

    from alphaforge.config.settings import load_settings

    settings = load_settings("sharadar")   # <- THE FIX: the source the pre-registration declared
    print(f"\n  profile 'sharadar' -> lake_dir {settings.paths.lake_dir}")
    # ENFORCE THE DECLARATION before spending compute. Three runs on 2026-08-07 used a
    # lake their pre-registration did not name; two burned a trial on a silent null and one
    # crashed after four hours. The document was right every time and nothing read it.
    from alphaforge.validation.prereg import assert_matches

    assert_matches(
        _ROOT / "docs/design/PREREG_FUNDAMENTAL_SINGLES.md",
        lake_dir=settings.paths.lake_dir,
        profile="sharadar",
    )
    print("  pre-registration check PASSED: profile and lake match the declaration")

    _assert_columns(Path(settings.paths.lake_dir))

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
    results: dict[str, dict] = {}

    for name in [n for n in RUN_ORDER if n in rows]:
        d = rows[name]
        cfg = d["config"]
        out_dir = _ROOT / "artifacts" / "walkforward" / f"{name}_rerun"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n  === {name} -> {out_dir.name} ===")
        with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
            reader = PITDataReader(paths)
            universe = UniverseStore(paths)
            service = SignalService(
                FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
                universe, default_registry(), settings.signals,
                sleeve=sleeve, alpha_names=[name],
            )
            runner = WalkForwardRunner(
                reader, store, universe, TransactionCostModel.from_settings(settings),
                service, settings,
            )
            res = runner.run(
                int(cfg["start"]), int(cfg["end"]),
                train_bars=int(cfg["train_bars"]), test_bars=int(cfg["test_bars"]),
                allocator=cfg["allocator"], embargo_bars=sleeve.embargo_bars,
                instrument_ids=list(cfg["instrument_ids"]),
                rebalance_bars=int(cfg["rebalance_bars"]),
                no_trade_band=float(cfg["no_trade_band"]),
                out_dir=out_dir, now_ms=None, experiment_log=None,
                alpha_names=[name],
            )
        s = res.summary
        results[name] = {"sharpe": float(s.sharpe), "vol_ann": float(s.vol_ann),
                         "max_dd": float(s.max_dd)}
        print(f"    net Sharpe {float(s.sharpe):+.4f}  vol {float(s.vol_ann):.4f}  maxDD {float(s.max_dd):.4f}")

    after = sum(1 for _ in LEDGER.open())
    if before != after:
        raise SystemExit(f"ABORT: ledger moved {before} -> {after}; the zero-trial claim is void.")

    print("\n" + "=" * 92)
    print(f"  ledger {before} -> {after} (nothing recorded)")
    print("  For comparison, on the SAME 98-factor screen:")
    print("    eq_net_issuance   t_nw +3.542  IC +0.0522   <- 5th of 98")
    print("    eq_asset_growth   t_nw +0.829  IC +0.0117   <- deployed as AlphaLedger")
    print("    eq_gross_profitability screened t_nw +2.95 and walk-forwarded to -0.263.")
    print("  A screen t is not a prediction. Read the Sharpe above, not the screen.")
    out = _ROOT / "artifacts" / "analysis" / "null_fundamentals_rerun"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"  written: {out / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
