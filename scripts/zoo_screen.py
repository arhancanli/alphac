#!/usr/bin/env python3
"""Fast first-cut screen for the strategy ZOO — Rank-IC over every zoo factor in one pass.

The cheap stage of the brutal funnel: register the whole zoo (hundreds of factors) into the
registry, then run the SAME Rank-IC report the engine uses (`af research ic`) over all of them
against a profile's lake. Output is ranked by Newey-West t-stat of the non-overlapping Rank-IC —
the honest "does this signal predict returns at all" first cut. Most candidates die here, cheaply
(IC is a per-bar cross-sectional rank correlation; no portfolio sim, no per-leg refit). The
SURVIVORS (top by |t|) then go to the full deflated walk-forward gauntlet, where the Deflated
Sharpe is penalized by the FULL number screened here.

    zoo_screen.py --profile sharadar --start 2003-01-01 --end 2026-06-01 --horizons 63 --top 40
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
    ap = argparse.ArgumentParser(prog="zoo_screen")
    ap.add_argument("--profile", default="sharadar")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--horizons", default="63", help="comma-separated forward-return horizons (bars)")
    ap.add_argument("--top", type=int, default=40, help="print the top-N by |NW t-stat|")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    import alphaforge.features.library  # noqa: F401  the canonical factors
    from alphaforge.config.settings import load_settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.time import now_ms, parse_utc
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.research import zoo
    from alphaforge.research.ic_report import ICReportRunner

    reg = default_registry()
    before = len(reg.all_specs())
    added = zoo.register_all(reg)
    total = len(reg.all_specs())
    print(f"zoo: registered {added} grid factors (library {before} -> {total} total to screen)")

    settings = load_settings(a.profile)
    start = settings.data.backfill_start_ms if a.start is None else parse_utc(f"{a.start}T00:00:00Z")
    end = now_ms() if a.end is None else parse_utc(f"{a.end}T00:00:00Z")
    horizons = [int(h) for h in a.horizons.split(",") if h.strip()]
    out_dir = Path(a.out) if a.out else (settings.paths.lake_dir.parent / "research" / "zoo")
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as instruments:
        runner = ICReportRunner(
            FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths), asset_class=settings.data.asset_class),
            PITDataReader(paths),
            UniverseStore(paths),
            reg,
            paths=paths,
            asset_class=settings.data.asset_class,
        )
        runner.run(start=start, end=end, horizons=horizons, out_dir=out_dir)

    # rank the screened factors by |NW t-stat| at the first horizon and print the top survivors
    import json as _json
    rep = _json.loads((out_dir / "ic_report.json").read_text())
    h0 = horizons[0]
    rows = [r for r in rep.get("rows", []) if int(r.get("horizon", h0)) == h0]

    def _t(r):
        return abs(float(r.get("t_nw") or 0.0))

    ranked = sorted(rows, key=_t, reverse=True)
    print(f"\n=== TOP {a.top} of {len(rows)} screened factors by |Rank-IC NW t| @ h={h0} (the IC first cut) ===")
    print(f"{'factor':<24}{'|NW t|':>9}{'mean_IC':>10}{'IC_IR':>9}{'hit':>7}")
    for r in ranked[: a.top]:
        print(f"{r.get('factor', '?'):<24}{_t(r):>9.2f}{float(r.get('mean_ic', 0)):>10.4f}"
              f"{float(r.get('ic_ir', 0)):>9.3f}{float(r.get('hit_rate', 0)):>7.2f}")
    survivors = [r["factor"] for r in ranked if _t(r) >= 2.0]
    print(f"\n|NW t| >= 2.0 survivors ({len(survivors)}): {', '.join(survivors) if survivors else '(none clear the cut)'}")
    print(f"full report: {out_dir / 'ic_report.json'}  (screened {total} factors; this N feeds the gauntlet's DSR deflation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
