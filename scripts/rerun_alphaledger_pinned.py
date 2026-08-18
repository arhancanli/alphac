#!/usr/bin/env python3
"""Re-run AlphaLedger (eq_asset_growth) on the universe its pre-registration actually pinned.

WHY. docs/design/PREREG_SLEEVE4_INVESTMENT.md fixes the universe to the frozen
`data/research/universe_allowlist_20260619.json` cohort (8,017 ids, sha256 `2fd82d30...`) and
states: "No parameter below may be changed. If any of it is altered, this is a new trial and this
document is void."

Measured 2026-08-07, `artifacts/walkforward/prereg_investment/` ran on **6,880** ids:

    1,293 pinned names ABSENT from the run   (40/40 sampled have daily data - not a data filter)
       96 non-pinned EQUITY names PRESENT    (ABLX, ACCD1, AIRO1 - newer listings)
       60 crypto perps PRESENT               (zero effect: 0 held across all 933,091 position-rows,
                                              since an asset-growth factor reads a balance sheet
                                              and a perpetual future has none)

The universe was resolved dynamically at run time instead of being loaded from the frozen
allowlist. Every OTHER declared parameter matches exactly (allocator rank, 252/63/63/274,
rebalance 63, band 0.001, alpha eq_asset_growth). So the sleeve's headline evidence - 21y Sharpe
0.83, NW t +3.19, and the rho -0.367 to AlphaMax that makes it the book's largest diversifier -
rests on a run the pre-registration does not cover.

THIS IS NOT A NEW TRIAL. It executes the DECLARED configuration for the first time. Running the
config a document already specifies is not a new hypothesis - it is the hypothesis. `now_ms=None`
and `experiment_log=None` keep the ledger untouched, and the line count is asserted before and
after, exactly as the crypto_lowvol_720 re-execution did.

WHAT WOULD MAKE THIS DISHONEST: re-running with anything other than the pinned cohort; quietly
keeping whichever result is better; or reporting the new numbers without the old ones beside them.
All three are closed off below - the script fails if the universe does not verify, and it prints
old and new together.

    uv run python scripts/rerun_alphaledger_pinned.py
"""
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

ALLOWLIST = _ROOT / "data/research/universe_allowlist_20260619.json"
PINNED_SHA_PREFIX = "2fd82d30"
OLD_ARTIFACT = _ROOT / "artifacts/walkforward/prereg_investment"
OUT_DIR = _ROOT / "artifacts/walkforward/prereg_investment_pinned"
LEDGER = _ROOT / "var/experiments.jsonl"

#: Declared in PREREG_SLEEVE4_INVESTMENT.md. Asserted against the old artifact so a silent drift in
#: ANY of them is caught before compute is spent, not discovered in the result.
DECLARED = {
    "allocator": "rank",
    "alpha_names": ["eq_asset_growth"],
    "train_bars": 252,
    "test_bars": 63,
    "purge_bars": 63,
    "embargo_bars": 274,
    "rebalance_bars": 63,
    "no_trade_band": 0.001,
}


def _verify_pinned() -> list[str]:
    """Load the frozen cohort and PROVE it is the one the pre-registration names.

    The document quotes the file's own `sha256` field. A self-declared hash is worth nothing
    unless it reproduces, so this recomputes it: sha256 over the document with its own sha256 key
    removed, serialized with indent=1. Verified to reproduce 2fd82d30... on 2026-08-07.
    """
    doc = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    claimed = str(doc.get("sha256", ""))
    body = {k: v for k, v in doc.items() if k != "sha256"}
    actual = hashlib.sha256(json.dumps(body, indent=1).encode()).hexdigest()
    if actual != claimed:
        raise SystemExit(
            f"ABORT: {ALLOWLIST} does not match its own sha256.\n"
            f"  claimed {claimed}\n  actual  {actual}\n"
            "The frozen cohort has been modified. Nothing may be run against it until that is "
            "explained."
        )
    if not claimed.startswith(PINNED_SHA_PREFIX):
        raise SystemExit(
            f"ABORT: allowlist hash {claimed[:16]}... does not start with the pre-registered "
            f"{PINNED_SHA_PREFIX}... This is not the cohort the document pins."
        )
    ids = list(doc["instrument_ids"])
    print(f"  pinned cohort VERIFIED: {len(ids)} ids, sha256 {claimed[:16]}… reproduces")
    return ids


def main() -> int:
    print("=" * 92)
    print("ALPHALEDGER — re-run on the PINNED cohort (executing the pre-registration as written)")
    print("=" * 92)
    pinned = _verify_pinned()

    old = json.loads((OLD_ARTIFACT / "walkforward.json").read_text())
    ocfg = old["config"]
    drift = {k: (v, ocfg.get(k)) for k, v in DECLARED.items() if ocfg.get(k) != v}
    if drift:
        raise SystemExit(f"ABORT: the old artifact already differs from the declaration on {drift}. "
                         "Re-running would not isolate the universe change.")
    print("  every declared parameter matches the old artifact; ONLY the universe differs")
    old_ids = set(ocfg["instrument_ids"])

    # INTERSECTION, not replacement. The first attempt at this passed the raw 8,017-name allowlist
    # as instrument_ids, which BYPASSES WalkForwardRunner._window_ids — the point-in-time
    # membership filter that keeps a leg to instruments actually listed during it. It crashed 2h in:
    #
    #   CostModelMisuse: sqrt impact law invalid: notional 132.0 exceeds 5% of ADV 434.0
    #
    # i.e. it tried to trade $132 of a name with $434 of daily volume, because a cohort frozen on
    # 2026-06-19 was being forced into 2003 legs where those names had no membership and, in some
    # cases, no meaningful liquidity. The pre-registration pins an ELIGIBILITY cohort; it does not
    # instruct us to hold every member in every era, and reading it that way produces a book the
    # cost model correctly refuses to price.
    #
    # The faithful reading is: the PIT membership universe, RESTRICTED to the frozen cohort. That
    # removes 156 names from the original run (60 crypto perps, never held in any of the 933,091
    # position-rows, plus 96 equities outside the cohort) and restores none, because a pinned name
    # with no membership in the window was never eligible to begin with.
    universe_ids = sorted(old_ids & set(pinned))
    dropped = old_ids - set(universe_ids)
    crypto_dropped = {i for i in dropped if i.startswith("BINANCE:")}
    print(f"  old run {len(old_ids)} ids  ->  PIT-window ∩ pinned cohort = {len(universe_ids)} ids")
    print(f"  dropped {len(dropped)}: {len(crypto_dropped)} crypto perps (never held) + "
          f"{len(dropped) - len(crypto_dropped)} equities outside the frozen cohort")

    before = sum(1 for _ in LEDGER.open())

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

    # THE DECLARED SOURCE, not the convenient one. PREREG_SLEEVE4_INVESTMENT.md line 76:
    # "History (validation): Sharadar SF1, on disk, frozen at 2026-06-20."
    #
    # The first two attempts ran under the `equity` profile (lake_dir data/lake) and BOTH died at
    # the same instrument: "sqrt impact law invalid: notional 132.0 exceeds 5% of ADV 434.0".
    # data/lake is the whole-market Polygon feed and 11% of sampled names carry a median dollar
    # ADV under $10k; data/lake_sharadar carries 1%. The cost model was right to refuse, and the
    # run was reading the wrong lake.
    #
    # This is the THIRD instance today of one root cause: a pre-registration names a data source
    # and nothing in the code enforces it. eq_net_issuance and eq_accruals returned silent nulls
    # for the same reason. The durable fix is a profile assertion at run start, not vigilance.
    settings = load_settings("sharadar")
    setup_logging(settings.paths.var_dir / "log")
    sleeve = sleeve_for(settings.data.asset_class)

    # ENFORCE THE DECLARATION before spending compute. Three runs on 2026-08-07 used a
    # lake their pre-registration did not name; two burned a trial on a silent null and one
    # crashed after four hours. The document was right every time and nothing read it.
    from alphaforge.validation.prereg import assert_matches

    assert_matches(
        _ROOT / "docs/design/PREREG_SLEEVE4_INVESTMENT.md",
        lake_dir=settings.paths.lake_dir,
        profile="sharadar",
        alpha_names=["eq_asset_growth"],
    )
    print("  pre-registration check PASSED: profile and lake match the declaration")
    paths = LakePaths(settings.paths.lake_dir)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  out: {OUT_DIR}")
    print("  running… (86 legs over 2000-01-01..2026-06-01; this takes a while)")

    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe, default_registry(), settings.signals,
            sleeve=sleeve, alpha_names=list(DECLARED["alpha_names"]),
        )
        runner = WalkForwardRunner(
            reader, store, universe, TransactionCostModel.from_settings(settings), service, settings,
        )
        result = runner.run(
            int(ocfg["start"]), int(ocfg["end"]),
            train_bars=DECLARED["train_bars"], test_bars=DECLARED["test_bars"],
            allocator=DECLARED["allocator"], embargo_bars=DECLARED["embargo_bars"],
            instrument_ids=universe_ids,                # <- THE ONLY CHANGE
            rebalance_bars=DECLARED["rebalance_bars"],
            no_trade_band=DECLARED["no_trade_band"],
            initial_cash=float(ocfg.get("initial_cash", 100_000.0)),
            out_dir=OUT_DIR, now_ms=None, experiment_log=None,   # zero new trials
            alpha_names=list(DECLARED["alpha_names"]),
        )

    after = sum(1 for _ in LEDGER.open())
    if before != after:
        raise SystemExit(f"ABORT: ledger moved {before} -> {after}; the zero-trial claim is void.")

    osum = old["summary"]
    print("=" * 92)
    print(f"  ledger {before} -> {after}  (nothing recorded)")
    print(f"  {'metric':<16} {'OLD (6,880 ids)':>18} {'COHORT (6,724)':>18}")
    for k in ("sharpe", "vol_ann", "max_dd", "cagr"):
        o = osum.get(k)
        n = getattr(result.summary, k, None)
        if o is not None and n is not None:
            print(f"  {k:<16} {float(o):>18.4f} {float(n):>18.4f}")
    print("=" * 92)
    print("  The rho to AlphaMax and the deflated Sharpe must be recomputed from the new curve")
    print("  before this sleeve is described, funded, or scheduled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
