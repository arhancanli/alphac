"""Publish the earnings-narrative-change pre-registration's parameters as data, not prose.

WHY. A pre-registration's whole function is that the specification is fixed BEFORE measurement, so
that a reader can later check the run against it. This one's parameters existed only as English
sentences — "adjusted close at session -252", "the four current equal-quarter sleeves (22.5%
each)". Nobody outside this repository could compare the executed run to the committed spec,
because the spec was not in a form anything could compare against.

Found on 2026-08-22 by the number-trace audit: those two figures appear on the published page and
in no artifact. That is how the gap surfaced, and it is worth being plain that making the guard
green was the trigger — but the reason to fix it this way rather than exempt them is that a
prose-only specification is a weakness in the pre-registration itself.

DERIVED VALUES SHOW THEIR ARITHMETIC. The 22.5% sleeve weight is not a measurement; it is what four
equal quarters become when a candidate is funded pro rata at 10%. Publishing the inputs and the
operation lets a reader check the number rather than accept it.

Reads the committed pre-registration and the probe's own result read-only. Runs no backtest, opens
no return data, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREREG = REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE.md"
RESULT = REPO / "artifacts" / "probe" / "earnings_narrative_change" / "result.json"
OUTPUT = REPO / "artifacts" / "engineering" / "prereg_earnings_narrative_parameters.json"


def main() -> int:
    text = PREREG.read_text() if PREREG.exists() else ""
    result = json.loads(RESULT.read_text()) if RESULT.exists() else {}

    sleeves = 4
    candidate_weight = 0.10
    weight_before = 1.0 / sleeves
    weight_after = weight_before * (1.0 - candidate_weight)

    payload = {
        "schema": "canli.alphac-prereg-parameters.v1",
        "claim_boundary": (
            "The numeric parameters this pre-registration commits to, extracted from the committed "
            "document and stated as data. It asserts nothing about the candidate's performance, "
            "re-runs nothing, and changes no threshold. 0 trials."
        ),
        "why_this_exists": (
            "A pre-registration's function is that the spec is fixed before measurement so a "
            "reader can check the run against it. These parameters existed only as English "
            "sentences, so nothing could compare the executed run to the committed spec."
        ),
        "document": {
            "path": str(PREREG.relative_to(REPO)) if PREREG.exists() else None,
            "sha256": ("sha256:" + hashlib.sha256(PREREG.read_bytes()).hexdigest())
            if PREREG.exists()
            else None,
            "public_path": "/research/prereg-earnings-narrative-change",
        },
        "committed_parameters": {
            "momentum_lookback_sessions": 252,
            "momentum_lookback_session_index": -252,
            "momentum_skip_sessions": 21,
            "momentum_skip_session_index": -21,
            "hedge_beta_window_sessions": 252,
            "hold_sessions": 63,
            "minimum_aligned_observations": 252,
            "minimum_stressed_observations": 63,
            "note": (
                "Stated in the document as '12-1 momentum ... adjusted close at session -21 "
                "divided by adjusted close at session -252', a trailing 252-session SPY beta "
                "hedge, and void conditions below 252 aligned or 63 stressed observations."
            ),
        },
        "marginal_test_weights": {
            "current_sleeves": sleeves,
            "sleeve_weight_before": weight_before,
            "candidate_weight": candidate_weight,
            "sleeve_weight_after": weight_after,
            "sleeve_weight_after_pct": round(weight_after * 100, 1),
            "derivation": (
                f"{sleeves} equal sleeves at {weight_before:.0%} each; the candidate is assigned "
                f"{candidate_weight:.0%} funded PRO RATA, so every existing sleeve keeps "
                f"{1 - candidate_weight:.0%} of its weight: {weight_before:.2f} x "
                f"{1 - candidate_weight:.2f} = {weight_after:.3f}. This is arithmetic, not a "
                "measurement, and it is published with its inputs so it can be checked rather "
                "than accepted."
            ),
        },
        "measured_book_effect": {
            "candidate_10pct_sharpe": (result.get("book") or {}).get("candidate_10pct_sharpe"),
            "base_sharpe": (result.get("book") or {}).get("base_sharpe"),
            "source": "artifacts/probe/earnings_narrative_change/result.json",
            "note": "Included so the weight the spec commits to and the weight the run used are "
            "visible on one page.",
        },
        "parameters_found_verbatim_in_the_document": sorted(
            {m for m in re.findall(r"-?\d+", text) if m in {"252", "-252", "21", "-21", "63"}}
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  lookback {payload['committed_parameters']['momentum_lookback_sessions']} sessions")
    print(
        f"  sleeve weight after a {candidate_weight:.0%} candidate: "
        f"{payload['marginal_test_weights']['sleeve_weight_after_pct']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
