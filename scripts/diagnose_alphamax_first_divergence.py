"""Locate the first difference using retained outputs; no strategy rerun."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/alphamax_durable_replay_20260912"
REFERENCE = ROOT / "evidence/alphamax-reference-recovery-20260912/reference_output"
REPLAY = OUT / "workspace/outputs/k30_dn_63"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    prior = json.loads(
        Path(
            "/Users/arhancanli/alphaforge/artifacts/publication/alphamax_upstream_clean_workspace.json"
        ).read_text()
    )
    a = pd.read_parquet(REFERENCE / "equity.parquet")
    b = pd.read_parquet(REPLAY / "equity.parquet")
    assert a.ts.equals(b.ts)
    differing = np.flatnonzero(a.equity.to_numpy() != b.equity.to_numpy())
    first = int(differing[0])
    x = pd.read_parquet(REFERENCE / "legs/leg_00/orders.parquet")
    y = pd.read_parquet(REPLAY / "legs/leg_00/orders.parquet")
    joined = x.merge(
        y,
        on=["decision_ts", "instrument_id"],
        suffixes=("_reference", "_replay"),
        validate="one_to_one",
    )
    changed = joined[
        (joined.qty_reference != joined.qty_replay)
        | (joined.status_reference != joined.status_replay)
    ]
    changed.to_parquet(OUT / "first_decision_order_differences.parquet", index=False)
    leg_results = []
    for path in sorted((REFERENCE / "legs").iterdir()):
        fields = {}
        for name in ["equity", "orders", "fills", "positions"]:
            expected = pd.read_parquet(path / f"{name}.parquet")
            actual = pd.read_parquet(REPLAY / "legs" / path.name / f"{name}.parquet")
            fields[name] = {
                "exact": expected.equals(actual),
                "reference_rows": len(expected),
                "replay_rows": len(actual),
            }
        leg_results.append({"leg": path.name, "comparisons": fields})
    body = {
        "scope": "RETAINED_OUTPUT_DIAGNOSTIC",
        "replay_matches_prior_replay_hash": sha(REPLAY / "equity.parquet")
        == prior["comparison"]["equity_curve"]["replay_sha256"],
        "first_different_equity": {
            "timestamp": int(a.ts.iloc[first]),
            "reference": float(a.equity.iloc[first]),
            "replay": float(b.equity.iloc[first]),
            "difference": float(b.equity.iloc[first] - a.equity.iloc[first]),
        },
        "first_orders": {
            "timestamp": int(x.decision_ts.min()),
            "same_instrument_set": set(x.instrument_id) == set(y.instrument_id),
            "matched_instruments": len(joined),
            "all_decision_prices_exact": bool(
                (joined.decision_price_reference == joined.decision_price_replay).all()
            ),
            "changed_quantity_count": int((joined.qty_reference != joined.qty_replay).sum()),
            "changed_status_count": int((joined.status_reference != joined.status_replay).sum()),
            "newly_filled": sorted(
                set(y.loc[y.status == "filled", "instrument_id"])
                - set(x.loc[x.status == "filled", "instrument_id"])
            ),
            "no_longer_filled": sorted(
                set(x.loc[x.status == "filled", "instrument_id"])
                - set(y.loc[y.status == "filled", "instrument_id"])
            ),
        },
        "legs": leg_results,
        "localization": "Initial sizing differs; short TEAM is replaced by short CVS",
        "unresolved": "Original forecasts, covariance and full inputs unavailable; cause unproven",
        "new_hypotheses": 0,
        "union_hypotheses": 238,
        "bindings": {
            str(p.relative_to(ROOT)): sha(p)
            for p in [
                Path(__file__),
                REFERENCE / "equity.parquet",
                REPLAY / "equity.parquet",
                REFERENCE / "legs/leg_00/orders.parquet",
                REPLAY / "legs/leg_00/orders.parquet",
                OUT / "output_inventory.json",
            ]
        },
    }
    with (OUT / "first_divergence.json").open("x") as f:
        json.dump(body, f, indent=2, sort_keys=True)
    print(json.dumps(body["first_orders"], indent=2))


if __name__ == "__main__":
    main()
