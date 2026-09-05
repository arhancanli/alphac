"""Publish the figures the AlphaVintage correction paper quotes, each recomputed from its inputs.

WHY. `/research/alphavintage-missing-release-correction` states a sealed outcome — a calendar-
correct net Sharpe, a Newey-West t, a maximum drawdown, a superseded Sharpe, and the session counts
they were measured over. Two of those figures traced to nothing published: the superseded Sharpe
sat only in an unpublished probe result, and **the maximum drawdown was in no artifact at all** —
it is derivable from the probe's equity curve, and nobody outside this repository could derive it.

A number in a correction paper is the last place a reader should have to take something on trust.
The paper is the document that says we were wrong; if its own figures cannot be checked, the
correction asks for exactly the credence the original mistake did.

THE DRAWDOWN IS RECOMPUTED HERE, not copied: the probe's `result.json` does not carry one. It is
derived from `equity.parquet` by the standard peak-to-trough definition, and both inputs are
hashed into the output so a reader can confirm they are looking at the same files.

Reads the probe artifacts read-only. Runs no backtest, opens no return data, registers no
hypothesis: 0 trials.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / "artifacts" / "probe" / "cpi_surprise_size"
RESULT = PROBE / "result.json"
EQUITY = PROBE / "equity.parquet"
OUTPUT = REPO / "artifacts" / "engineering" / "alphavintage_sealed_outcome.json"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    result = json.loads(RESULT.read_text())
    equity = pd.read_parquet(EQUITY)
    curve = equity["equity"].astype(float).to_numpy()
    drawdown = curve / np.maximum.accumulate(curve) - 1.0
    max_drawdown = float(drawdown.min())

    payload = {
        "schema": "canli.alphac-alphavintage-sealed-outcome.v1",
        "claim_boundary": (
            "The figures the published correction paper quotes, recomputed from the probe's own "
            "artifacts so a reader can check them. It re-states a sealed result; it does not "
            "re-run it, re-open return data, or change any verdict. 0 trials."
        ),
        "why_this_exists": (
            "Two figures in that paper traced to nothing published: the superseded Sharpe lived "
            "only in an unpublished probe result, and the maximum drawdown was in no artifact at "
            "all. A correction paper whose own numbers cannot be checked asks for exactly the "
            "credence the original mistake did."
        ),
        "net_sharpe": result.get("net_sharpe"),
        "newey_west_t": result.get("nw_t"),
        "active_day_net_sharpe_superseded": result.get("active_day_net_sharpe_superseded"),
        "portfolio_days": result.get("portfolio_days"),
        "active_days": result.get("active_days"),
        "verdict": result.get("verdict"),
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": round(max_drawdown * 100, 1),
        "max_drawdown_definition": (
            "peak-to-trough on the probe's own equity curve: min(equity / cummax(equity) - 1). "
            "RECOMPUTED here because result.json does not carry a drawdown; the paper quoted a "
            "figure no published artifact contained."
        ),
        "equity_curve_rows": len(equity),
        "inputs": {
            "result_json": {"path": str(RESULT.relative_to(REPO)), "sha256": _sha256(RESULT)},
            "equity_parquet": {"path": str(EQUITY.relative_to(REPO)), "sha256": _sha256(EQUITY)},
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  net Sharpe            {payload['net_sharpe']}")
    print(f"  superseded Sharpe     {payload['active_day_net_sharpe_superseded']}")
    print(f"  max drawdown          {payload['max_drawdown_pct']}%  (recomputed)")
    print(
        f"  sessions              {payload['portfolio_days']} portfolio / "
        f"{payload['active_days']} active"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
