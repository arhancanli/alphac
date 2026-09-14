"""Check captured first weights against retained replay; no new return computation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphamax-initial-allocation-20260912"
PIN = ROOT / "artifacts/analysis/alphamax_durable_replay_20260912/workspace"


def main():
    a = pd.read_parquet(OUT / "allocation.parquet")
    order_path = PIN / "outputs/k30_dn_63/legs/leg_00/orders.parquet"
    b = pd.read_parquet(order_path)
    assert len(b.decision_ts.unique()) == 1
    x = a.merge(b, on="instrument_id", validate="one_to_one")
    assert len(x) == len(a) == len(b) == 202
    x["reconstructed_qty"] = np.floor(abs(x.target_weight) * 100000 / x.decision_price + 1e-9)
    assert (x.reconstructed_qty == x.qty).all()
    active = x.qty > 0
    assert ((x.loc[active, "target_weight"] > 0) == (x.loc[active, "side"] == "buy")).all()
    focus = a.set_index("instrument_id")
    gap = float(focus.loc["XUSE:CASH:TEAMUSD", "mu_ann"] - focus.loc["XUSE:CASH:CVSUSD", "mu_ann"])
    files = [
        Path(__file__),
        ROOT / "scripts/trace_alphamax_initial_allocation.py",
        order_path,
        OUT / "allocation.parquet",
        OUT / "covariance.parquet",
        OUT / "close_panel.parquet",
    ] + sorted((PIN / "src").rglob("*.py"))
    result = {
        "all_202_quantities_exact": True,
        "all_active_sides_exact": True,
        "team_minus_cvs_mu_ann": gap,
        "gap_basis_points_annual_forecast": gap * 10000,
        "rank_cutoff": {"TEAM": 172, "CVS": 173, "shorts_start_at": 173},
        "interpretation": "Fresh selection differs at a near-tied ranking boundary",
        "root_cause_proven": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
        "bindings": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
    }
    with (OUT / "allocation_verification.json").open("x") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "bindings"}, indent=2))


if __name__ == "__main__":
    main()
