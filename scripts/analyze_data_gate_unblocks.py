"""Classify what is actually blocking each DATA_GATED family, and what each unblock costs.

WHY THIS EXISTS. Eleven of sixteen feasibility studies sit at DATA_GATED, and "data-gated" reads
like one problem. It is three, with wildly different costs: a free API key nobody registered, a
paid vendor decision, and genuine extraction engineering. Lumping them together hides the fact
that some of the fourteen-sleeve programme is blocked on a two-minute signup.

Reads the feasibility artifacts and greps the audit scripts for the credentials they consult.
Opens no return data, runs no backtest, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FEASIBILITY = REPO / "artifacts" / "feasibility"
SCRIPTS = REPO / "scripts"
OUTPUT = REPO / "artifacts" / "analysis" / "data_gate_unblocks" / "result.json"

# Credential -> what it costs to obtain. Stated so a blocker is never reported without its price.
CREDENTIALS: dict[str, dict[str, str]] = {
    "EIA_API_KEY": {
        "cost": "FREE",
        "obtain": "https://www.eia.gov/opendata/register.php",
        "effort": "instant, email only",
    },
    "DATABENTO_API_KEY": {
        "cost": "PAID",
        "obtain": "https://databento.com",
        "effort": "commercial agreement; usage-priced",
    },
    "POLYGON_API_KEY": {
        "cost": "FREE_TIER",
        "obtain": "https://polygon.io/dashboard/signup",
        "effort": "instant; free tier is rate-limited and may not cover the full history",
    },
}

_ENV = re.compile(r'os\.environ\.get\(\s*"([A-Z][A-Z0-9_]*)"')


def _scripts_for(family: str) -> list[Path]:
    stem = family.replace("-", "_")
    return sorted(
        path
        for path in SCRIPTS.glob("*.py")
        if (stem.split("_")[0] in path.stem and "feasibility" in path.stem)
        or stem in path.stem
    )


def _credentials_used(paths: list[Path]) -> list[str]:
    found: set[str] = set()
    for path in paths:
        found.update(name for name in _ENV.findall(path.read_text()) if name in CREDENTIALS)
    return sorted(found)


def main() -> int:
    families: list[dict[str, Any]] = []
    for directory in sorted(p for p in FEASIBILITY.iterdir() if p.is_dir()):
        results = sorted(directory.glob("*.json"))
        if not results:
            continue
        artifact = json.loads(results[0].read_text())
        decision = str(artifact.get("decision", "UNKNOWN"))
        gates = artifact.get("gates") or {}
        failing = sorted(k for k, v in gates.items() if v is False)
        blocking = list(artifact.get("blocking_reasons") or [])
        paths = _scripts_for(directory.name)
        credentials = _credentials_used(paths)
        missing = [name for name in credentials if not os.environ.get(name)]

        if missing:
            free = [n for n in missing if CREDENTIALS[n]["cost"] in ("FREE", "FREE_TIER")]
            classification = "BLOCKED_ON_FREE_CREDENTIAL" if free else "BLOCKED_ON_PAID_DATA"
        elif failing or blocking:
            classification = "BLOCKED_ON_EXTRACTION_QUALITY"
        else:
            classification = "NOT_BLOCKED"

        families.append(
            {
                "family": directory.name,
                "decision": decision,
                "classification": classification,
                "failing_gates": failing,
                "failing_gate_count": len(failing),
                "passing_gate_count": sum(1 for v in gates.values() if v is True),
                "blocking_reasons": blocking,
                "credentials_required": credentials,
                "credentials_missing": missing,
                "credential_cost": {
                    name: CREDENTIALS[name] for name in missing
                },
                "return_hypotheses_spent": artifact.get("return_hypotheses_spent", 0),
            }
        )

    by_class: dict[str, list[str]] = {}
    for family in families:
        by_class.setdefault(family["classification"], []).append(family["family"])

    # Closest to passing: gated, needs no credential, and fails the fewest gates.
    nearest = sorted(
        (
            f
            for f in families
            if f["decision"] == "DATA_GATED"
            and f["classification"] == "BLOCKED_ON_EXTRACTION_QUALITY"
            and f["failing_gate_count"] > 0
        ),
        key=lambda f: (f["failing_gate_count"], -f["passing_gate_count"]),
    )

    result = {
        "schema": "canli.alphac-data-gate-unblocks.v1",
        "claim_boundary": (
            "Classifies blockers only. Opens no return data, runs no backtest, registers no "
            "hypothesis, and claims nothing about any candidate's edge, sign or correlation. "
            "0 trials."
        ),
        "families_examined": len(families),
        "by_classification": by_class,
        "families": families,
        "nearest_to_passing": [
            {
                "family": f["family"],
                "failing_gates": f["failing_gates"],
                "passing": f["passing_gate_count"],
            }
            for f in nearest[:5]
        ],
        "owner_actions": [
            {
                "action": f"register {name} ({meta['cost']}) at {meta['obtain']}",
                "effort": meta["effort"],
                "unblocks": sorted(
                    f["family"] for f in families if name in f["credentials_missing"]
                ),
            }
            for name, meta in CREDENTIALS.items()
            if any(name in f["credentials_missing"] for f in families)
        ],
        "honest_reading": (
            "A credential unblocks COLLECTION, never admission. A family whose key arrives still "
            "has to pass its remaining feasibility gates, then pre-register, then clear all "
            "eighty-five admission checks. The free keys are worth registering because they are "
            "free, not because they are close to a sleeve."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    for name, members in sorted(by_class.items()):
        print(f"  {name}: {len(members)}")
    print("\n  owner actions:")
    for action in result["owner_actions"]:
        print(f"    - {action['action']}")
        print(f"      unblocks: {', '.join(action['unblocks']) or '(none mapped)'}")
    print("\n  nearest to passing (no credential needed):")
    for item in result["nearest_to_passing"]:
        print(f"    - {item['family']}: {item['passing']} gates pass, "
              f"{len(item['failing_gates'])} fail -> {item['failing_gates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
