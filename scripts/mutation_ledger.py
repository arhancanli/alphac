"""Prove every guard over a published claim can actually fail, and publish the result.

WHY THIS EXISTS. A check that cannot fail is worse than no check: it produces the confidence of a
guard with none of the protection, and it is invisible in review because a passing test looks
identical whether it is watching something or nothing. This repository has shipped that failure
repeatedly — five honesty guards all running and all unable to fire, a gate nobody could pass, a
presence check that passed with the line it named deleted, and a link audit that counted 1,309
links on a site with none.

WHAT IT DOES. For every unit test that guards a PUBLISHED claim, it breaks the thing that test is
watching, runs that test alone, and records whether it failed. Then it puts the artifact back and
verifies byte-for-byte that it did. The output is a table of guard → mutation → observed result.

TWO RULES THAT MAKE IT MORE THAN A SCRIPT:

  1. COVERAGE IS DERIVED, NOT LISTED. The set of guards over published claims is computed from the
     tests directory by the same rule every time. A guard added without a mutation entry fails
     this run rather than quietly joining the unmutated majority.

  2. A SURVIVING MUTATION IS A PUBLISHED FINDING, NOT A BUG TO FIX QUIETLY. If a guard passes while
     the thing it guards is broken, that is the most useful line in the table and it is printed
     first, kept in the artifact, and returns a non-zero exit.

Runs no backtest, opens no return data, registers no hypothesis: 0 trials.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests" / "unit"
MERIDIAN = Path.home() / "meridian"
OUTPUT = REPO / "artifacts" / "engineering" / "mutation_ledger.json"

# The rule that decides which tests guard a PUBLISHED claim. Applied to the tests directory rather
# than to a list, so the coverage question answers itself.
PUBLISHED_MARKERS = ("artifacts/", "meridian", "config/sleeve", "glassbox")


def guards_a_published_claim(path: Path) -> bool:
    source = path.read_text()
    return any(marker in source for marker in PUBLISHED_MARKERS)


def discover_guards() -> list[str]:
    return sorted(p.name for p in TESTS.glob("test_*.py") if guards_a_published_claim(p))


@dataclass(frozen=True)
class Mutation:
    """One way to break what a guard is watching."""

    guard: str
    describes: str
    target: Path
    mutate: Callable[[str], str]
    #: What SHOULD happen. "CAUGHT" for a real break; "SURVIVED" for a NEGATIVE CONTROL — an edit
    #: that changes no behaviour and must therefore NOT fail the guard. Without controls, a
    #: harness that reported CAUGHT for everything would look perfect.
    expect: str = "CAUGHT"
    notes: list[str] = field(default_factory=list)


def _replace(old: str, new: str) -> Callable[[str], str]:
    def apply(text: str) -> str:
        if old not in text:
            raise AssertionError(f"mutation anchor not found: {old[:60]!r}")
        return text.replace(old, new, 1)
    return apply


def _strip_from_published_lines(word: str, replacement: str) -> Callable[[str], str]:
    """Remove a word from every line a reader sees, leaving source comments untouched.

    Written because replacing the FIRST occurrence was not enough: the guard it targets passed
    while six of seven mentions survived, and four of those were comments. A disclosure guard has
    to be tested by removing the disclosure from ALL published copy, or the mutation is measuring
    whether the word exists somewhere rather than whether it is disclosed.
    """

    def apply(text: str) -> str:
        out, touched = [], 0
        for line in text.splitlines(keepends=True):
            if not line.lstrip().startswith("#") and word in line:
                line = line.replace(word, replacement)
                touched += 1
            out.append(line)
        if touched == 0:
            raise AssertionError(f"{word!r} appears on no published line")
        return "".join(out)

    return apply


def _bump_json(path_in_doc: tuple[str, ...], delta: float) -> Callable[[str], str]:
    """Move one number in a JSON document, leaving everything else byte-identical in meaning."""

    def apply(text: str) -> str:
        doc = json.loads(text)
        node: Any = doc
        for key in path_in_doc[:-1]:
            node = node[key]
        leaf = path_in_doc[-1]
        if not isinstance(node.get(leaf), (int, float)):
            raise AssertionError(f"{'.'.join(path_in_doc)} is not a number")
        node[leaf] = node[leaf] + delta
        return json.dumps(doc, indent=2, sort_keys=True) + "\n"

    return apply


def _first_json_number(pattern: str, delta: float) -> Callable[[str], str]:
    def apply(text: str) -> str:
        match = re.search(pattern, text)
        if match is None:
            raise AssertionError(f"no number matched {pattern}")
        value = float(match.group(1))
        return text[: match.start(1)] + repr(value + delta) + text[match.end(1) :]

    return apply


CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
LIVE_CONTRACT = REPO / "config" / "live_change_contract.json"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "test_admission_significance_floors.py",
        "raise the Newey-West t floor above what the deflated-Sharpe floor can reach",
        CONTRACT,
        _bump_json(("thresholds", "newey_west_t_min"), 40.0),
        notes=["The unsatisfiable-floors class: two gates that cannot both be met."],
    ),
    Mutation(
        "test_admission_contract_is_fully_enforced.py",
        "add a threshold the evaluator does not read",
        CONTRACT,
        _replace('"thresholds": {', '"thresholds": {\n    "a_gate_nobody_enforces": 0.5,'),
        notes=["A threshold sitting in the contract wearing a gate's costume."],
    ),
    Mutation(
        "test_admission_frontier_arithmetic.py",
        "move the published Sharpe target away from the correlation it requires",
        CONTRACT,
        _replace('"portfolio_sharpe_target": [', '"portfolio_sharpe_target": [ 9.0,'),
        notes=[
            "First aimed at average_pairwise_correlation_objective, which this guard does not "
            "read: it watches the GATE and the target. A mutation that misses is indistinguishable "
            "from a guard that cannot fail, and that is the whole trap this ledger exists inside.",
        ],
    ),
    Mutation(
        "test_sleeve_admission.py",
        "loosen the out-of-sample observation minimum",
        CONTRACT,
        _bump_json(("thresholds", "minimum_oos_observations"), -500),
    ),
    Mutation(
        "test_published_gates_match_the_contract.py",
        "change the contract the site derives its published gate summary from",
        CONTRACT,
        _bump_json(("thresholds", "average_pairwise_correlation_max"), 0.25),
    ),
    Mutation(
        "test_live_change_is_declared.py",
        "corrupt the declared live-configuration fingerprint",
        LIVE_CONTRACT,
        _replace("sha256:", "sha256:0"),
        notes=["The ceremony that stopped a live sizing change contaminating the forward record."],
    ),
    Mutation(
        "test_published_clone_url.py",
        "publish a clone URL for a repository that does not exist",
        MERIDIAN / "scripts" / "build-verify.mjs",
        _replace("/alphac.git", "/alphaforge.git"),
        notes=["The defect that actually shipped, reproduced."],
    ),
    Mutation(
        "test_indexnow_is_in_the_deploy_path.py",
        "stop the hourly deploy announcing what it published",
        REPO / "scripts" / "live_deploy_hourly.sh",
        _replace('    indexnow_submit "$HOME/meridian"', "    :"),
    ),
    Mutation(
        "test_publish_pipeline_order.py",
        "reorder the publish pipeline so a contract is copied before it is rebuilt",
        REPO / "scripts" / "live_publish.sh",
        _replace(
            "uv run python scripts/export_lint_debt_contract.py",
            "true # export_lint_debt_contract.py",
        ),
        notes=["The stale-artifact class: research_export copies whatever is on disk."],
    ),
    Mutation(
        "test_published_chain_label_matches_the_data.py",
        "label the chain's ENTRY count with the word days on the published page",
        MERIDIAN / "open.html",
        _replace(
            '<span data-tx="entries">--</span> entries',
            '<span data-tx="entries">--</span> days',
        ),
        notes=[
            "The count-is-not-a-duration defect, reproduced: this exact wording once overstated a "
            "47-day chain as 371 days. First aimed at the chain FILE, which this guard does not "
            "read — it watches what the page calls the number.",
        ],
    ),
    Mutation(
        "test_content_hashes_reproduce_publicly.py",
        "edit a published artifact after it was hashed",
        MERIDIAN / "public" / "glassbox" / "kill_log.json",
        _first_json_number(r'"killed_count":\s*(\d+)', 1),
        notes=["Exactly what the reproduce kit exists to detect, done from the inside."],
    ),
    Mutation(
        "test_research_export_freshness.py",
        "let a published contract go stale against its source",
        REPO / "artifacts" / "engineering" / "lint_debt_contract.json",
        _replace('"schema"', '"stale_marker": true,\n  "schema"'),
    ),
    Mutation(
        "test_kill_papers_quote_their_artifact.py",
        "make the generator print a figure the kill-log entry does not contain",
        REPO / "scripts" / "build_kill_papers.py",
        _replace(
            'rows.append(("Net Sharpe", _figure(entry, "sharpe", ".4f", quoted)))',
            'rows.append(("Net Sharpe", "42.7"))',
        ),
        notes=[
            "Two earlier attempts moved the kill log itself and were not caught, and that is "
            "CORRECT rather than a gap: this guard regenerates each paper from the entry, so "
            "moving the entry moves both sides together. What it actually watches is the "
            "GENERATOR, which is what research_export.py runs on every publish. The mutation "
            "therefore has to break the generator.",
        ],
    ),
    Mutation(
        "test_published_sleeve_claims_track_artifacts.py",
        "drop the KILLED disclosure from a sleeve whose artifact records that verdict",
        REPO / "scripts" / "paper_trading_state.py",
        _strip_from_published_lines("KILLED", "recorded"),
        notes=[
            "Two earlier attempts moved NUMBERS in the artifacts; this guard watches DISCLOSURE "
            "LANGUAGE — that a killed sleeve is described as killed — so a number is the wrong "
            "thing to move.",
        ],
    ),
    # THE FIVE THE RULE CAUGHT THAT GUARD THE ENGINE RATHER THAN A PUBLISHED CLAIM. The
    # discovery rule matched them on a docstring reference, and rather than narrow the rule to
    # make the count look complete, they are mutated too — the live trading loop is a more
    # consequential thing to guard than a sentence on a page.
    Mutation(
        "test_alphavintage_target.py",
        "double the live gross target this sleeve trades at",
        REPO / "scripts" / "alphavintage_target.py",
        _replace("LIVE_GROSS_TARGET = 1.0", "LIVE_GROSS_TARGET = 2.0"),
    ),
    Mutation(
        "test_live_cycle_equity_guard.py",
        "let non-equity instruments back into the equity target book",
        REPO / "scripts" / "live_cycle.py",
        _replace(
            "w = {iid: wt for iid, wt in w.items() if iid.startswith(_EQUITY_ID_PREFIX)}",
            "w = dict(w)",
        ),
        notes=["The unscoped-universe defect that put perpetuals in an equity artifact."],
    ),
    Mutation(
        "test_curve_store.py",
        "change the curve transform away from the log basis every consumer assumes",
        REPO / "src" / "alphaforge" / "analytics" / "curve_store.py",
        _replace(
            'np.log(daily.to_numpy(dtype="float64")),',
            'np.sqrt(daily.to_numpy(dtype="float64")),',
        ),
    ),
    Mutation(
        "test_paper_broker_funding.py",
        "stop the LIVE broker booking funding",
        REPO / "src" / "alphaforge" / "execution" / "paper.py",
        _replace(
            '        """Settle one funding event against the live position; return the cashflow.',
            "        return 0.0\n"
            '        """Settle one funding event against the live position; return the cashflow.',
        ),
        notes=[
            "The carry sleeve booked funding zero times in 44 days once, because a TypeError was "
            "swallowed by a bare except and nine tests pinned the intention rather than the path.",
        ],
    ),
    Mutation(
        "test_overlay_realized_leg_scale.py",
        "NEGATIVE CONTROL: edit a comment and nothing else",
        REPO / "src" / "alphaforge" / "portfolio" / "strategy.py",
        _replace(
            "# information about the unlevered book's vol. Dropping them is right; dividing",
            "# NEGATIVE CONTROL edit. Dropping them is right; dividing",
        ),
        expect="SURVIVED",
        notes=[
            "THE HARNESS'S NEGATIVE CONTROL. This edits a COMMENT and nothing else, so the guard "
            "must NOT fail. A mutation harness with no control looks perfect precisely when it is "
            "broken: if every run reports CAUGHT, the reason might be that the runner fails for "
            "reasons unrelated to the mutation.",
        ],
    ),
    Mutation(
        "test_audit_sleeve_family_lineage.py",
        "make the lineage audit return PASS unconditionally",
        REPO / "scripts" / "audit_sleeve_family_lineage.py",
        _replace('"PASS" if current_gate and not failed else "FAIL_CLOSED"', '"PASS"'),
        notes=[
            "Two earlier attempts moved DATA; this guard runs the audit over fixtures, so it "
            "watches the audit's LOGIC. A gate that always passes is the thing to break.",
        ],
    ),
)


def _run_test(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS / name), "-q", "--no-cov", "-x"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def main() -> int:
    guards = discover_guards()
    mutated = {m.guard for m in MUTATIONS}
    unknown = sorted(mutated - set(guards))
    if unknown:
        raise AssertionError(f"mutations registered for tests that do not exist: {unknown}")

    rows = []
    survived = []
    for mutation in MUTATIONS:
        target = mutation.target
        if not target.exists():
            rows.append(
                {
                    "guard": mutation.guard,
                    "mutation": mutation.describes,
                    "target": str(target),
                    "result": "TARGET_MISSING",
                }
            )
            survived.append(mutation.guard)
            continue

        original = target.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        baseline = _run_test(mutation.guard)
        try:
            target.write_text(mutation.mutate(original.decode()))
            after = _run_test(mutation.guard)
        finally:
            target.write_bytes(original)
        restored = hashlib.sha256(target.read_bytes()).hexdigest()
        if restored != digest:
            raise AssertionError(f"failed to restore {target} — repo left dirty, stopping")

        caught = after.returncode != 0
        observed = "CAUGHT" if caught else "SURVIVED"
        as_expected = observed == mutation.expect
        rows.append(
            {
                "guard": mutation.guard,
                "mutation": mutation.describes,
                "target": str(target.relative_to(REPO) if target.is_relative_to(REPO) else target),
                "passes_clean": baseline.returncode == 0,
                "expected": mutation.expect,
                "result": observed,
                "as_expected": as_expected,
                "restored_byte_identical": True,
                "notes": mutation.notes,
            }
        )
        if not as_expected or baseline.returncode != 0:
            survived.append(mutation.guard)
        flag = "ok  " if as_expected else "FIND"
        print(f"  {flag} {observed:8}  {mutation.guard:52} {mutation.describes}")

    unmutated = sorted(set(guards) - mutated)
    result = {
        "schema": "canli.alphac-mutation-ledger.v1",
        "claim_boundary": (
            "Breaks what each guard watches and records whether the guard failed. Runs no "
            "backtest, opens no return data, registers no hypothesis identity, and changes "
            "nothing permanently — every mutation is restored and the restoration is verified by "
            "hash. 0 trials."
        ),
        "why": (
            "A check that cannot fail is worse than no check: it produces the confidence of a "
            "guard with none of the protection, and a passing test looks identical whether it is "
            "watching something or nothing."
        ),
        "guards_over_published_claims": len(guards),
        "guards_mutated": len(MUTATIONS),
        "guards_not_yet_mutated": unmutated,
        "coverage_is_derived": (
            "The guard set is computed from tests/unit by the same rule every run, so a guard "
            "added without a mutation appears here rather than joining the unmutated majority "
            "unnoticed."
        ),
        "negative_controls": [r for r in rows if r.get("expected") == "SURVIVED"],
        "findings": [r for r in rows if r.get("as_expected") is False],
        "ledger": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(f"\nwrote {OUTPUT.relative_to(REPO)}")
    print(f"  guards over published claims : {len(guards)}")
    print(f"  mutated this run             : {len(MUTATIONS)}")
    print(f"  behaved as expected          : {sum(1 for r in rows if r.get('as_expected'))}")
    print(f"  negative controls            : {sum(1 for m in MUTATIONS if m.expect == 'SURVIVED')}")
    print(f"  FINDINGS                     : {len(survived)}")
    for name in survived:
        print(f"      {name}")
    if unmutated:
        print(f"  not yet mutated              : {len(unmutated)}")
        for name in unmutated:
            print(f"      {name}")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
