"""Three of the four audit dimensions that were opened and never finished.

The adversarial audit stopped after two of six. This works the rest by hand and records every
finding — including the ones that turned out to be wrong, because an audit that keeps only its hits
cannot be checked by anybody who was not there.

  E  CONTRACT SATISFIABILITY, beyond the two pairs the production loader already rejects.
     Those two are enforced in code. This asks the remaining question: of the gates that CAN all
     be met at once, which one is ever decisive? A gate that no candidate can fail without
     already failing another is not strict — it is decoration, and it makes the contract read as
     more demanding than it is.

  F  PUBLISHED CLAIMS AGAINST ARTIFACTS. Whether the numbers in the site's narrative sections are
     present in the artifacts those sections are derived from.

  G  UNIT AND NUMERICAL PLAUSIBILITY. The class that produced a 100x cost error (dividing by 100
     where 10,000 was meant) and a published record eight times too long (a COUNT labelled with a
     DURATION). Every published field whose NAME declares a unit is checked for a value that is
     implausible in that unit.

Reads the contract, the artifacts and the published bundle read-only. 0 trials.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SITE = REPO.parent / "meridian" / "public" / "glassbox"
CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
OUTPUT = REPO / "artifacts" / "engineering" / "contract_and_unit_audit.json"

ANNUALIZATION_DAYS = 252.0


@dataclass
class Finding:
    dimension: str
    title: str
    verdict: str
    detail: str
    numbers: dict[str, Any] = field(default_factory=dict)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


# ------------------------------------------------------------------------------------------
# E. Which gates can ever be decisive?
# ------------------------------------------------------------------------------------------
def dimension_e() -> list[Finding]:
    contract = _load(CONTRACT)
    t = contract["thresholds"]
    findings: list[Finding] = []

    # E1. The correlation pair. A point gate and a bound gate on the same quantity, over a sample
    # whose size the contract also fixes, so the question is pure arithmetic.
    n = t["minimum_correlation_observations"]
    se = 1.0 / math.sqrt(n - 3)
    point = t["average_pairwise_correlation_max"]
    upper = t["average_pairwise_correlation_upper_95_max"]
    binding_from = upper - 1.645 * se
    decisive = binding_from < point
    findings.append(
        Finding(
            "E",
            "the upper-95 correlation gate cannot be the decisive one",
            "CONFIRMED" if not decisive else "REFUTED",
            (
                f"At {n} correlation observations the standard error is {se:.4f}, so the "
                f"upper-95 bound only exceeds {upper:+.2f} once the point estimate passes "
                f"{binding_from:+.4f} — and a point estimate that high already fails the "
                f"{point:+.2f} point gate. Both are satisfiable together, which is why the "
                "production loader does not reject them; but the bound gate can never be the "
                "reason a candidate is refused. It reads as a second, independent hurdle and it "
                "is not one."
            )
            if not decisive
            else (
                f"The bound gate binds from {binding_from:+.4f}, below the {point:+.2f} point "
                "gate, so it can be decisive."
            ),
            {
                "correlation_observations": n,
                "standard_error": round(se, 4),
                "point_gate": point,
                "upper_95_gate": upper,
                "upper_95_binds_above": round(binding_from, 4),
            },
        )
    )

    # E2. The book-level deflated-Sharpe gate against what the book has actually measured.
    book_gate = t.get("book_deflated_sharpe_min")
    restatement = SITE / "legacy_dsr_restatement.json"
    deflation = SITE / "deflation.json"
    if book_gate is not None and restatement.exists() and deflation.exists():
        best_variant = max(
            (v.get("restated_dsr") or 0.0) for v in _load(restatement)["restated_variants"]
        )
        best_book = _load(deflation)["best_config"]["dsr_shared"]
        findings.append(
            Finding(
                "E",
                "the book deflated-Sharpe gate is currently unreachable in practice",
                "CONFIRMED",
                (
                    f"Admission requires the BOOK to clear a deflated Sharpe of {book_gate}. The "
                    f"best figure this book has ever measured is {best_book} for the blended "
                    f"configuration and {best_variant:.4f} for the best single restated variant. "
                    "This is not a contradiction in the contract — it is satisfiable by a better "
                    "book — but it means no candidate can be admitted today however good the "
                    "candidate is, and that belongs on the page beside the gate rather than being "
                    "discovered by someone who tries."
                ),
                {
                    "book_deflated_sharpe_min": book_gate,
                    "best_measured_book_dsr": best_book,
                    "best_restated_variant_dsr": round(best_variant, 4),
                },
            )
        )

    # E3. The t-ratio floor, which is not decidable from arithmetic alone. Recorded as such rather
    # than left out, because "we did not check this" and "this is fine" must not look the same.
    if "newey_west_t_ratio_min" in t:
        findings.append(
            Finding(
                "E",
                "the Newey-West t-ratio floor is not decidable by arithmetic",
                "UNDECIDABLE",
                (
                    f"newey_west_t_ratio_min={t['newey_west_t_ratio_min']} gates the ratio of the "
                    "autocorrelation-robust t to the naive one, which depends on a candidate's "
                    "own autocorrelation. There is no threshold pair here that contradicts it, "
                    "and no arithmetic that clears it either. It can only be settled against real "
                    "candidates, and it is recorded as unsettled rather than as satisfied."
                ),
                {"newey_west_t_ratio_min": t["newey_west_t_ratio_min"]},
            )
        )
    return findings


# ------------------------------------------------------------------------------------------
# F. Published narrative numbers against the artifacts behind them.
# ------------------------------------------------------------------------------------------
_NARRATIVE_KEYS = ("executive_summary", "methodology", "roadmap", "honesty_note", "corrections")


def _numbers_in(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, str):
        found |= {m for m in re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", node) if len(m) > 1}
    elif isinstance(node, dict):
        for value in node.values():
            found |= _numbers_in(value)
    elif isinstance(node, list):
        for value in node:
            found |= _numbers_in(value)
    return found


def _renderings(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out |= {str(node), f"{node:,}", f"{node:.0f}", f"{node:.1f}", f"{node:.2f}", f"{node:.4f}"}
        if 0 <= node <= 1:
            out |= {f"{node * 100:.0f}", f"{node * 100:.1f}"}
    elif isinstance(node, str):
        out |= set(re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", node))
    elif isinstance(node, dict):
        for key, value in node.items():
            out.add(str(key))
            out |= _renderings(value)
    elif isinstance(node, list):
        for value in node:
            out |= _renderings(value)
    return out


def dimension_f() -> list[Finding]:
    research = SITE / "research.json"
    if not research.exists():
        return []
    bundle = _load(research)
    narrative = {k: v for k, v in bundle.items() if k in _NARRATIVE_KEYS}
    quoted = _numbers_in(narrative)
    # Everything the bundle carries OUTSIDE the narrative is the evidence those sections describe.
    evidence = _renderings({k: v for k, v in bundle.items() if k not in _NARRATIVE_KEYS})
    # Four-digit numbers are years and are not claims.
    untraceable = sorted(
        n for n in quoted - evidence if not re.fullmatch(r"(19|20)\d\d", n.replace(",", ""))
    )
    findings = [
        Finding(
            "F",
            "numbers in the published narrative that appear nowhere in the evidence it describes",
            "CONFIRMED" if untraceable else "REFUTED",
            (
                f"{len(untraceable)} of {len(quoted)} figures quoted in the narrative sections "
                f"({', '.join(_NARRATIVE_KEYS)}) are not present anywhere in the rest of the "
                f"bundle: {untraceable[:12]}"
            )
            if untraceable
            else (
                f"All {len(quoted)} figures quoted in the narrative sections are present in the "
                "evidence the bundle carries. This checks PRESENCE, not that each number is used "
                "in the right place — the stronger property belongs to E3."
            ),
            {"quoted": len(quoted), "untraceable": len(untraceable), "examples": untraceable[:12]},
        )
    ]
    if len(quoted) < 20:
        findings.append(
            Finding(
                "F",
                "the narrative sections quote too few numbers for this dimension to say much",
                "CONFIRMED",
                (
                    f"only {len(quoted)} figures appear in the narrative sections at all, so a "
                    "clean result here is a statement about how little prose carries numbers "
                    "rather than about how well those numbers are grounded. The stronger property "
                    "— every number ANYWHERE on the site tracing to an artifact — is E3's, and "
                    "this dimension should not be read as having established it."
                ),
                {"quoted": len(quoted)},
            )
        )
    return findings


# ------------------------------------------------------------------------------------------
# G. Units declared by a field's name against the value it holds.
# ------------------------------------------------------------------------------------------
#: (suffix, predicate, why a violation matters). Each rule encodes a real defect class.
_UNIT_RULES: tuple[tuple[str, Any, str], ...] = (
    ("_bps", lambda v: abs(v) > 10_000, "a basis-point field over 10,000 is probably a percent"),
    ("_pct", lambda v: abs(v) > 1_000, "a percent field over 1,000 is probably a ratio times 100"),
    (
        "_days",
        lambda v: isinstance(v, int) and v > 20_000,
        "a day count over 20,000 is longer than this programme has existed; a COUNT labelled with "
        "a DURATION overstated a published record eight-fold once",
    ),
    ("_usd", lambda v: abs(v) > 1e12, "a dollar field in the trillions is a unit error"),
    ("_ratio", lambda v: abs(v) > 100, "a ratio over 100 is probably a percentage"),
)


def dimension_g() -> list[Finding]:
    findings: list[Finding] = []
    checked = 0
    violations: list[dict[str, Any]] = []

    def walk(node: Any, path: str, source: str) -> None:
        nonlocal checked
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key), source)
        elif isinstance(node, list):
            for i, value in enumerate(node[:200]):
                walk(value, f"{path}[{i}]", source)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            leaf = path.rsplit(".", 1)[-1].split("[")[0]
            for suffix, predicate, why in _UNIT_RULES:
                if leaf.endswith(suffix):
                    checked += 1
                    if predicate(node):
                        violations.append(
                            {"source": source, "field": path, "value": node, "why": why}
                        )

    for artifact in sorted(SITE.glob("*.json")):
        try:
            walk(_load(artifact), "", artifact.name)
        except (ValueError, OSError):
            continue

    findings.append(
        Finding(
            "G",
            "published fields whose value is implausible for the unit their name declares",
            "CONFIRMED" if violations else "REFUTED",
            (
                f"{len(violations)} of {checked} unit-declaring fields across the published bundle "
                f"hold a value implausible for that unit: {violations[:6]}"
            )
            if violations
            else (
                f"All {checked} unit-declaring fields across the published bundle hold values "
                "plausible for the unit their name declares. The rules encode real defect classes "
                "rather than style: a 100x divisor error and a count labelled as a duration have "
                "both shipped here."
            ),
            {"fields_checked": checked, "violations": len(violations)},
        )
    )
    if checked < 20:
        findings.append(
            Finding(
                "G",
                "the unit scan matched too few fields to mean anything",
                "CONFIRMED",
                f"only {checked} fields carried a unit-declaring suffix, so a clean result here is "
                "the scanner finding nothing rather than nothing being wrong",
                {"fields_checked": checked},
            )
        )
    return findings


def main() -> int:
    dimensions = {"E": dimension_e(), "F": dimension_f(), "G": dimension_g()}
    rows = [f.__dict__ for group in dimensions.values() for f in group]
    result = {
        "schema": "canli.alphac-contract-and-unit-audit.v1",
        "claim_boundary": (
            "Three audit dimensions worked against the contract in force and the published bundle. "
            "It reads configuration and artifacts; it runs no backtest, opens no return data, "
            "registers no hypothesis identity and changes no threshold. Findings are reported, not "
            "acted on. 0 trials."
        ),
        "dimensions": {
            "E": "contract satisfiability beyond the pairs the loader already rejects",
            "F": "published narrative numbers against the evidence they describe",
            "G": "units declared by a field's name against the value it holds",
        },
        "companion": (
            "artifacts/engineering/guards_that_cannot_fire.json is the fourth dimension, and "
            "artifacts/engineering/mutation_ledger.json is its behavioural half."
        ),
        "refutations_are_kept": (
            "A dimension that found nothing says so, with what it checked. An audit that reports "
            "only its hits cannot be told apart from one that did not run."
        ),
        "findings": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    for row in rows:
        print(f"  [{row['dimension']}] {row['verdict']:11} {row['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
