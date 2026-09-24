#!/usr/bin/env python3
"""Score the capital-readiness gate: may any real capital be placed yet? (Today: no, and why.)

Reads config/capital_readiness_gate.json and the artifacts its measured criteria name; an
attestation criterion passes only when config/capital_readiness_attestations.json records it with
a date and who attested. Missing evidence is FAIL, never PASS. Places no order. 0 trials.

    uv run python scripts/evaluate_capital_readiness.py [--write]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
GATE: Final = ROOT / "config" / "capital_readiness_gate.json"
ATTESTATIONS: Final = ROOT / "config" / "capital_readiness_attestations.json"
MATURITY: Final = ROOT / "artifacts" / "engineering" / "forward_evidence_maturity.json"
SHORTFALL: Final = ROOT / "artifacts" / "analysis" / "implementation_shortfall" / "result.json"
DRAWDOWN_CONTRACT: Final = ROOT / "config" / "drawdown_control_contract.json"
OWNER_GOALS: Final = ROOT / "config" / "owner_goals.json"
OUTPUT: Final = ROOT / "artifacts" / "engineering" / "capital_readiness.json"


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _sleeve_goal(goals: dict[str, Any] | None) -> int | None:
    """The owner's sleeve minimum, read from its one structured field; None when absent."""
    value = (
        ((goals or {}).get("goals") or {}).get("qualified_economically_distinct_sleeves") or {}
    ).get("minimum")
    return int(value) if isinstance(value, int) else None


def evaluate(
    gate: dict[str, Any],
    maturity: dict[str, Any] | None,
    shortfall: dict[str, Any] | None,
    drawdown_contract: dict[str, Any] | None,
    attestations: dict[str, Any] | None,
    sleeve_goal: int | None,
) -> dict[str, Any]:
    results = []
    attested = (attestations or {}).get("attestations", {})
    for criterion in gate["criteria"]:
        cid = criterion["id"]
        observed: Any = None
        passed = False
        if criterion["kind"] == "attestation":
            record = attested.get(cid) or {}
            passed = bool(record.get("attested_on") and record.get("attested_by"))
            observed = record or "not attested"
        elif maturity is None and cid.startswith("E"):
            observed = "forward evidence artifact missing"
        elif cid == "E1_forward_record_length":
            sharpe = maturity["sharpe_evidence"]
            observed = {
                "observations": sharpe["daily_return_observations"],
                "required": sharpe["establishment_minimum"],
            }
            passed = observed["observations"] >= observed["required"]
        elif cid == "E2_forward_sharpe_target":
            sharpe = maturity["sharpe_evidence"]
            estimate = sharpe.get("annualized_point_estimate")
            observed = {"estimate": estimate, "target": sharpe["target"]}
            passed = estimate is not None and estimate >= sharpe["target"]
        elif cid == "E3_realized_drawdown":
            dd = maturity["drawdown_evidence"]
            observed = {
                "realized": dd["realized_live_max_drawdown"],
                "bound": dd["realized_max_drawdown_bound"],
            }
            passed = observed["realized"] <= observed["bound"]
        elif cid == "E4_provenance":
            observed = bool(maturity["provenance_gate"]["passes"])
            passed = observed
        elif cid == "E5_qualified_sleeves":
            current = int(maturity["diversification_evidence"]["current_sleeves"])
            observed = {"current": current, "goal": sleeve_goal}
            passed = sleeve_goal is not None and current >= sleeve_goal
        elif cid == "X1_implementation_shortfall":
            limit = float(criterion["max_shortfall_bps"])
            sleeves = (shortfall or {}).get("sleeves") or {}
            measured = {
                name: row.get("implementation_shortfall_bps_of_decision_notional")
                for name, row in sleeves.items()
            }
            observed = {"shortfall_bps": measured, "limit_bps": limit}
            passed = bool(measured) and all(v is not None and v <= limit for v in measured.values())
        elif cid == "O1_drawdown_brake_live":
            observed = bool(((drawdown_contract or {}).get("activation") or {}).get("live"))
            passed = observed
        results.append(
            {
                "id": cid,
                "group": criterion["group"],
                "kind": criterion["kind"],
                "passed": passed,
                "observed": observed,
            }
        )
    failing = [r["id"] for r in results if not r["passed"]]
    return {
        "schema": "canli.alphac-capital-readiness.v1",
        "gate_status": gate["status"],
        "verdict": "READY_FOR_CAPITAL" if not failing else "NOT_READY_PAPER_ONLY",
        "failing": failing,
        "criteria": results,
        "claim_boundary": (
            "A readiness score, not investment advice or legal advice. Places no order."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = evaluate(
        json.loads(GATE.read_text(encoding="utf-8")),
        _load(MATURITY),
        _load(SHORTFALL),
        _load(DRAWDOWN_CONTRACT),
        _load(ATTESTATIONS),
        _sleeve_goal(_load(OWNER_GOALS)),
    )
    for row in report["criteria"]:
        print(
            f"{'PASS' if row['passed'] else 'FAIL'}  {row['id']:34s} "
            f"{json.dumps(row['observed'])[:110]}"
        )
    print(report["verdict"])
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
