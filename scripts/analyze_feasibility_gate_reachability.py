"""For each near-miss feasibility gate, ask whether it can be reached at all.

WHY. Three families sit one gate from clearing feasibility, which invites exactly one move:
adjust the extraction until the number clears. That is tuning a measurement to agree with a
target. The question asked here instead is whether the shortfall is EXTRACTION -- something the
detector misses that is really in the documents -- or REALITY -- the documents do not contain it
at the rate the protocol assumed. Only the first is fixable, and only the second is a finding.

Reads frozen feasibility artifacts already on disk. Opens no market data, registers no hypothesis
identity, and proposes no change to any pre-registered threshold: 0 trials.

Companion to scripts/analyze_spinoff_prorata_gate.py, which answers the same question for
spin_off_dislocation against its 98 hash-verified documents.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "analysis" / "feasibility_gate_reachability" / "result.json"

MERGER = REPO / "artifacts/feasibility/merger_arbitrage/target_anchor_timeline.parquet"
CUSTOMER = REPO / "artifacts/feasibility/customer_supplier_propagation/document_sample.parquet"

# A genuine customer-concentration disclosure: a customer or client, plus a materiality statement.
# Deliberately broad on WORDING and strict on MEANING.
CONCENTRATION = re.compile(
    r"(?:\b(?:customer|client)s?\b.{0,200}"
    r"(?:\baccounted for\b|\brepresented\b|\d{1,3}(?:\.\d+)?\s*%|\bpercent\b)"
    r"|(?:\baccounted for\b|\brepresented\b|\d{1,3}(?:\.\d+)?\s*%).{0,200}"
    r"\b(?:customer|client)s?\b)",
    re.I | re.S,
)


def _merger() -> dict:
    frame = pd.read_parquet(MERGER)
    frame["has_prior"] = frame["prior_8k_accession"].notna()
    by_form = {
        str(form): {
            "prior_item101_8k_rate": float(group["has_prior"].mean()),
            "anchors": len(group),
            "clears_0_80": bool(group["has_prior"].mean() >= 0.80),
        }
        for form, group in frame.groupby("form")
    }
    return {
        "gate": "prior_item101_8k_rate_gte_0_80",
        "gate_threshold": 0.80,
        "blended_rate": float(frame["has_prior"].mean()),
        "by_form": by_form,
        "verdict": "GATE_BLENDS_TWO_POPULATIONS",
        "why": (
            "The threshold is applied across deal structures with different filing obligations. A "
            "tender offer's SC 14D9 follows a contemporaneous merger agreement, so its prior "
            "Item 1.01 8-K is nearly always present; a definitive merger proxy can be filed long "
            "after the agreement and by issuers who announced it otherwise. Measured separately, "
            "SC 14D9 clears 0.80 outright and DEFM14A does not come close. The blended figure "
            "describes neither population."
        ),
        "⚠️_this_is_not_permission_to_narrow_the_universe": (
            "Restricting to tender offers AFTER observing that they pass is selection, and the "
            "0.8665 above is now in-sample for that decision and cannot serve as its evidence. A "
            "tender-offer-scoped identity is a legitimate REDESIGN, and it needs its own "
            "pre-registration with its threshold and universe fixed before anything is measured "
            "again. What this analysis establishes is that the CURRENT protocol mis-specified its "
            "population, not that a narrower one works."
        ),
        "sc_to_t_note": (
            "SC TO-T appears in counts_by_year_form (521 filings) and not in the anchor timeline. "
            "That is deliberate and correct: TARGET_FORMS is {DEFM14A, SC 14D9} because SC TO-T "
            "is the bidder's filing, not the target's. Checked rather than assumed."
        ),
    }


def _customer() -> dict:
    frame = pd.read_parquet(CUSTOMER)
    frame["n_strict"] = frame["strict_name_candidates"].fillna(0).astype(int)

    def windows(row: pd.Series) -> list[str]:
        try:
            raw = json.loads(row["windows_json"]) if row["windows_json"] else []
        except (TypeError, ValueError):
            return []
        return [w if isinstance(w, str) else json.dumps(w) for w in raw]

    named = concentration_named = concentration_unnamed = 0
    for _, row in frame.iterrows():
        has_concentration = any(CONCENTRATION.search(w) for w in windows(row))
        if row["n_strict"] > 0:
            named += 1
            concentration_named += int(has_concentration)
        else:
            concentration_unnamed += int(has_concentration)

    total = len(frame)
    genuine = concentration_named + concentration_unnamed
    return {
        "gate": "strict_named_document_rate_at_least_50pct",
        "gate_threshold": 0.50,
        "published_rate": named / total,
        "documents_sampled": total,
        "documents_with_genuine_concentration_language": genuine,
        "genuine_concentration_share": genuine / total,
        "naming_rate_among_genuine_disclosures": (
            concentration_named / genuine if genuine else None
        ),
        "verdict": "GATE_UNREACHABLE_BY_DETECTOR_REPAIR",
        "why": (
            "An issuer may disclose a material customer concentration WITHOUT naming the "
            "customer, and most do. Among documents that genuinely carry concentration language, "
            f"only {concentration_named}/{genuine} name the customer "
            f"({concentration_named / genuine:.1%}) against a gate of 50%. The shortfall is what "
            "the filings contain, not what the parser reads."
        ),
        "a_hypothesis_this_measurement_REFUTED": (
            "Five window excerpts read by eye from the misses were generic business and "
            "risk-factor text, which suggested the denominator was inflated with documents that "
            "disclose no concentration at all. Measured across all 300, that is wrong: 93.3% do "
            "carry real concentration language, and correcting the denominator moves the rate "
            f"from {named / total:.4f} to {concentration_named / genuine:.4f} -- about two "
            "points, against a 15-point shortfall. Five excerpts were an unrepresentative sample "
            "and the hypothesis they suggested is recorded here as refuted rather than dropped."
        ),
    }


def main() -> int:
    for path in (MERGER, CUSTOMER):
        if not path.exists():
            print(f"missing {path}; refusing to guess")
            return 1

    families = {"merger_arbitrage": _merger(), "customer_supplier_propagation": _customer()}
    result = {
        "schema": "canli.alphac-feasibility-gate-reachability.v1",
        "claim_boundary": (
            "Asks only whether each near-miss gate is reachable by repairing extraction. Opens no "
            "market data, registers no hypothesis identity, proposes no threshold change and "
            "authorizes no candidate. 0 trials."
        ),
        "families": families,
        "companion": "artifacts/analysis/spinoff_prorata_gate/result.json",
        "summary": (
            "Of the three families one gate from feasibility, none is blocked by extraction. "
            "spin_off_dislocation and customer_supplier_propagation ask for language the filings "
            "do not contain at the assumed rate; merger_arbitrage applies one threshold to two "
            "populations with different filing obligations. All three need identity redesign with "
            "fresh pre-registration, not a better parser. That is a slower answer than 'one gate "
            "away' implied, and it is the true one."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    merger = families["merger_arbitrage"]
    print(f"\n  merger_arbitrage — blended {merger['blended_rate']:.4f} vs gate 0.80")
    for form, stats in sorted(merger["by_form"].items()):
        mark = "CLEARS" if stats["clears_0_80"] else "fails "
        print(
            f"    {form:10} {stats['prior_item101_8k_rate']:.4f}  "
            f"n={stats['anchors']:>5}  {mark}"
        )
    customer = families["customer_supplier_propagation"]
    print(f"\n  customer_supplier_propagation — published {customer['published_rate']:.4f} "
          f"vs gate 0.50")
    print(f"    genuine concentration disclosures : "
          f"{customer['genuine_concentration_share']:.4f} of the sample")
    print(f"    naming rate among those           : "
          f"{customer['naming_rate_among_genuine_disclosures']:.4f}  <- the real ceiling")
    print(f"\n  {result['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
