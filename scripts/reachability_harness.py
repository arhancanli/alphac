"""Before writing a protocol for a family, ask whether its gate is reachable at all.

WHY THIS EXISTS. On 2026-08-21 all three families sitting "one gate from passing" turned out to
be unreachable by extraction — the gates asked for language the filings do not contain, or applied
one threshold across populations with different filing obligations. That test was written three
times by hand, each time from scratch, and each time the tempting alternative was to widen the
detector until the number cleared. That is tuning a measurement to agree with a target.

WHAT GENERALISES AND WHAT DOES NOT — stated plainly, because pretending the whole thing
generalises is how a harness becomes a rubber stamp.

  GENERALISES   the decision logic: measured rate vs gate vs ceiling, and the verdict that
                follows from those three numbers.
  GENERALISES   the heterogeneity test: given a per-row outcome and a candidate stratifier,
                detect whether a blended rate hides a subgroup that clears the gate on its own.
  DOES NOT      the CEILING PROBE. What a perfect detector would find is family-specific — for
                spin-off it was "any pro-rata token in any written form", for customer-supplier
                it was "the naming rate among documents that genuinely disclose a concentration".
                Each family must supply its own, and this harness makes that a required argument
                rather than inventing one.

Every registered family is re-run against its PUBLISHED answer, so the harness cannot drift away
from the results it claims to reproduce.

Reads frozen artifacts read-only. Registers no hypothesis, opens no return data: 0 trials.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "reachability_harness" / "result.json"

UNREACHABLE = "GATE_UNREACHABLE_BY_DETECTOR_REPAIR"
BLENDED = "GATE_BLENDS_TWO_POPULATIONS"
REACHABLE = "REACHABLE_BY_DETECTOR_REPAIR"
CLEARS = "GATE_ALREADY_CLEARS"


@dataclass(frozen=True)
class Reachability:
    """One family's answer to 'can this gate be reached at all?'."""

    family: str
    gate: str
    threshold: float
    measured_rate: float
    ceiling_rate: float
    ceiling_basis: str
    strata: dict[str, tuple[float, int]] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        if self.measured_rate >= self.threshold:
            return CLEARS
        clearing = {k: v for k, v in self.strata.items() if v[0] >= self.threshold}
        if clearing and len(self.strata) > 1:
            return BLENDED
        if self.ceiling_rate < self.threshold:
            return UNREACHABLE
        return REACHABLE

    @property
    def headroom(self) -> float:
        """How much a perfect detector could still add. Negative means the gate is out of reach."""
        return self.ceiling_rate - self.threshold

    def to_dict(self) -> dict[str, Any]:
        clearing = sorted(k for k, v in self.strata.items() if v[0] >= self.threshold)
        return {
            "family": self.family,
            "gate": self.gate,
            "threshold": self.threshold,
            "measured_rate": self.measured_rate,
            "ceiling_rate": self.ceiling_rate,
            "ceiling_basis": self.ceiling_basis,
            "headroom_over_threshold": self.headroom,
            "strata": {k: {"rate": v[0], "n": v[1]} for k, v in self.strata.items()},
            "strata_clearing_alone": clearing,
            "verdict": self.verdict,
            "what_the_verdict_means": _MEANING[self.verdict],
            "⚠️_if_blended": (
                "A subgroup clearing the gate is NOT permission to narrow the universe. Selecting "
                "it after observing that it passes is selection, and its rate is then in-sample "
                "for that decision and cannot be its evidence. It is a REDESIGN needing its own "
                "pre-registration with threshold and universe fixed before anything is measured "
                "again."
            )
            if self.verdict == BLENDED
            else None,
        }


_MEANING = {
    UNREACHABLE: (
        "A perfect detector reaches less than the gate requires. The shortfall is what the "
        "documents contain, not what the parser reads, and no extraction work will close it. The "
        "identity needs a redesign that names the document carrying the evidence before it names "
        "a threshold."
    ),
    BLENDED: (
        "One threshold is applied across populations that do not share the obligation it tests. "
        "The blended rate describes none of them."
    ),
    REACHABLE: (
        "A perfect detector would clear the gate, so the shortfall IS extraction and the work is "
        "worth doing. This is the only verdict that justifies parser effort."
    ),
    CLEARS: "The gate already passes as measured; nothing to reach.",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads((REPO / path).read_text())


# ---------------------------------------------------------------------------------------------
# Registered families. Each supplies its OWN ceiling probe, because what a perfect detector
# would find is a property of the mechanism and not of this harness.
# ---------------------------------------------------------------------------------------------

def _spin_off() -> Reachability:
    published = _load(Path("artifacts/analysis/spinoff_prorata_gate/result.json"))
    return Reachability(
        family="spin_off_dislocation",
        gate=published["gate"],
        threshold=published["gate_threshold"],
        measured_rate=published["shipped_detector_rate"],
        ceiling_rate=published["any_pro_rata_token_rate"],
        ceiling_basis=(
            "documents containing a pro-rata token in ANY written form — hyphenated, "
            "non-breaking, or spaced. A detector cannot find language that is absent."
        ),
    )


def _customer_supplier() -> Reachability:
    published = _load(Path("artifacts/analysis/feasibility_gate_reachability/result.json"))
    family = published["families"]["customer_supplier_propagation"]
    return Reachability(
        family="customer_supplier_propagation",
        gate=family["gate"],
        threshold=family["gate_threshold"],
        measured_rate=family["published_rate"],
        ceiling_rate=family["naming_rate_among_genuine_disclosures"],
        ceiling_basis=(
            "the naming rate among documents that genuinely carry concentration language. An "
            "issuer may disclose a material customer concentration without naming the customer, "
            "and most do."
        ),
    )


def _merger_arbitrage() -> Reachability:
    published = _load(Path("artifacts/analysis/feasibility_gate_reachability/result.json"))
    family = published["families"]["merger_arbitrage"]
    strata = {
        form: (stats["prior_item101_8k_rate"], stats["anchors"])
        for form, stats in family["by_form"].items()
    }
    return Reachability(
        family="merger_arbitrage",
        gate=family["gate"],
        threshold=family["gate_threshold"],
        measured_rate=family["blended_rate"],
        # No separate ceiling probe: the shortfall here is not extraction at all, so the ceiling
        # IS the measured rate and the heterogeneity test is what carries the verdict.
        ceiling_rate=family["blended_rate"],
        ceiling_basis=(
            "not applicable — the filing either exists or it does not, so there is no detector to "
            "improve. The question is which population the threshold was written for."
        ),
        strata=strata,
    )


REGISTRY: dict[str, Callable[[], Reachability]] = {
    "spin_off_dislocation": _spin_off,
    "customer_supplier_propagation": _customer_supplier,
    "merger_arbitrage": _merger_arbitrage,
}

# The answers these three published when each was worked by hand. The harness must reproduce
# them, or it has drifted away from the results it claims to generalise.
PUBLISHED_VERDICTS = {
    "spin_off_dislocation": UNREACHABLE,
    "customer_supplier_propagation": UNREACHABLE,
    "merger_arbitrage": BLENDED,
}


def main() -> int:
    results = []
    mismatches = []
    for name, probe in REGISTRY.items():
        answer = probe()
        results.append(answer.to_dict())
        expected = PUBLISHED_VERDICTS[name]
        if answer.verdict != expected:
            mismatches.append(f"{name}: harness says {answer.verdict}, published {expected}")

    if mismatches:
        raise AssertionError(
            "the harness does not reproduce the published answers, so it has drifted from the "
            f"results it generalises: {mismatches}"
        )

    result = {
        "schema": "canli.alphac-reachability-harness.v1",
        "claim_boundary": (
            "Reads frozen feasibility artifacts read-only. Registers no hypothesis identity, "
            "opens no return data, and authorises no candidate. 0 trials."
        ),
        "purpose": (
            "Run BEFORE a protocol is written for any family. A near-miss gate invites exactly "
            "one move — widen the detector until the number clears — which is tuning a "
            "measurement to agree with a target. This asks the opposite question first."
        ),
        "what_generalises": [
            "the decision logic: measured rate vs gate vs ceiling, and the verdict that follows",
            "the heterogeneity test: whether a blended rate hides a subgroup that clears alone",
        ],
        "what_does_not_generalise": (
            "The CEILING PROBE. What a perfect detector would find is a property of the mechanism, "
            "so every family must supply its own; the harness makes that a required argument "
            "rather than inventing one. A harness that guessed the ceiling would be a rubber "
            "stamp."
        ),
        "families": results,
        "reproduces_published_answers": True,
        "verdict_meanings": _MEANING,
        "how_to_add_a_family": (
            "Write a probe returning a Reachability with its own ceiling_rate and ceiling_basis, "
            "register it, and add its expected verdict to PUBLISHED_VERDICTS if it has already "
            "been worked by hand. The harness refuses to run if any registered family stops "
            "reproducing its published answer."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  {'family':32} {'gate':>7} {'measured':>9} {'ceiling':>8} {'headroom':>9}  verdict")
    for row in results:
        headroom = row["headroom_over_threshold"]
        print(
            f"  {row['family']:32} {row['threshold']:>7.2f} {row['measured_rate']:>9.4f} "
            f"{row['ceiling_rate']:>8.4f} {headroom:>+9.4f}  {row['verdict']}"
        )
    print(f"\n  all {len(results)} families reproduce their published answers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
