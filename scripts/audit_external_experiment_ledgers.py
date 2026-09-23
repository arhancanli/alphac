#!/usr/bin/env python3
"""Find experiment ledgers outside the canonical union and price them against the trial budget.

WHY. Deflation is a property of the search, and the search is wherever measurements were run.
On 2026-09-12/13 an autonomous research session ran 118 new hypothesis identities inside a clone
of this repository (`~/alphac-prospective-pause-20260911`). Every one of them was recorded
correctly in that clone's `experiments.jsonl` ledgers, and not one of them was visible to this
repository, so the public trial ledger kept publishing 229 identities and "171 remaining" while
the true union stood at 347, past the 320 staged review the owner's own policy says pauses
registration. Nothing was wrong with the ledgers; the union was simply computed over one tree.

This audit computes the union the policy actually governs: the canonical tree plus every other
checkout of this engine on the machine. It reports the identities the public ledger cannot see,
the merged count, and which staged reviews that count has reached without a recorded review.
The nightly health board runs it as `C11-external-ledgers`.

What it does NOT do: it never imports, moves or edits a ledger, never reserves an identity, and
never decides which measurements were legitimate. Reconciling the union is an owner decision
recorded in `config/trial_accounting_reviews.json` (the `staged_reviews_held` map clears a reached
threshold), and importing ledgers is a governed change to the canonical tree.

Identity arithmetic is the repository's own (`alphaforge.validation.experiments`): a hypothesis
identity is a config with only the `start`/`end` window keys removed, so a window-only
remeasurement in a clone is not a new identity, while a cost-stress or baseline variant with any
other field changed is one, exactly as the published ledger counts them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion, hypothesis_hash
from alphaforge.validation.trial_budget import AMENDMENTS, effective_budget

REPO = Path(__file__).resolve().parents[1]
POLICY = REPO / "config" / "trial_accounting.json"
OUTPUT = REPO / "artifacts" / "analysis" / "external_experiment_ledgers" / "result.json"
SCHEMA = "canli.alphac-external-experiment-ledgers.v1"
AUTHOR = "Arhan Canli"

STATUS_COMPLETE = "CANONICAL_UNION_COMPLETE"
STATUS_UNRECONCILED = "EXTERNAL_IDENTITIES_UNRECONCILED"
STATUS_REVIEW_DUE = "STAGED_REVIEW_REACHED_WITHOUT_RECORD"
STATUS_OVER_BUDGET = "MERGED_UNION_EXCEEDS_BUDGET"


def is_engine_tree(path: Path) -> bool:
    """The same test ExperimentUnion.discover applies: a checkout has configs/base.yaml."""
    return (path / "configs" / "base.yaml").is_file()


def candidate_trees(search_roots: list[Path], canonical: Path) -> list[Path]:
    """Every engine checkout under the search roots, plus agent worktrees inside them, minus the
    canonical tree itself and anything marked as an archive. Symlinks are not followed so a link
    back into the canonical tree cannot count it twice."""
    canonical = canonical.resolve()
    found: dict[Path, Path] = {}
    for root in search_roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        children = [c for c in sorted(root.iterdir()) if c.is_dir() and not c.is_symlink()]
        nested = [
            w
            for c in [*children, canonical]
            for w in sorted((c / ".claude" / "worktrees").glob("*"))
            if w.is_dir() and not w.is_symlink()
        ]
        worktrees = canonical / ".claude" / "worktrees"
        for tree in children + nested:
            resolved = tree.resolve()
            if resolved == canonical:
                continue
            # Anything inside the canonical tree is already part of its union, except the agent
            # worktrees under .claude/worktrees, which discover() prunes as non-source and which
            # therefore hold ledgers the canonical union cannot see.
            if canonical in resolved.parents and worktrees not in resolved.parents:
                continue
            if "archive" in tree.name.casefold():
                continue
            if is_engine_tree(tree):
                found[resolved] = tree
    return [found[k] for k in sorted(found)]


def identities_of(tree: Path) -> tuple[dict[str, list[str]], int, int]:
    """hypothesis key -> ledger paths (relative), plus record and ledger counts."""
    union = ExperimentUnion.discover(tree / "var" / "experiments.jsonl", tree)
    keys: dict[str, list[str]] = {}
    records = 0
    ledgers = 0
    for path in union.paths:
        if not path.exists():
            continue
        rows = ExperimentLog(path).all()
        if not rows:
            continue
        ledgers += 1
        records += len(rows)
        for row in rows:
            keys.setdefault(hypothesis_hash(row.config), []).append(
                str(path.resolve().relative_to(tree.resolve()))
            )
    return keys, records, ledgers


REVIEWS_FILENAME = "trial_accounting_reviews.json"


def load_policy(path: Path) -> dict[str, Any]:
    """The policy, plus the EVENT record kept beside it.

    ``staged_reviews_held`` is read from ``trial_accounting_reviews.json`` next to the policy
    (and, for tests that build a policy inline, from the policy itself). The policy file is
    embedded byte-for-byte in the admission v7 promotion receipt and hash-bound by every v2
    reservation, so a held review is recorded beside it, never inside it (2026-09-14: recording
    the 320 review inside the policy drifted five sealed bindings without changing one rule).
    """
    policy = json.loads(path.read_text(encoding="utf-8"))
    review = policy.get("prospective_v7_review") or {}
    held: dict[str, Any] = dict(policy.get("staged_reviews_held") or {})
    reviews_path = path.with_name(REVIEWS_FILENAME)
    if reviews_path.exists():
        reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
        held.update(reviews.get("staged_reviews_held") or {})
    budget = int(policy["hypothesis_identity_budget"])
    staged = [int(x) for x in review.get("staged_hard_reviews", [])]
    amendments_path = path.with_name(AMENDMENTS.name)
    if amendments_path.exists():
        # The owner's budget amendment (alphaforge.validation.trial_budget) raises the ceiling
        # and adds staged reviews above it; the policy file itself never changes.
        in_force = effective_budget(path.parent.parent, path)
        budget = in_force.ceiling
        staged = list(in_force.staged_hard_reviews)
    return {
        "budget": budget,
        "staged_hard_reviews": staged,
        # A reached threshold is cleared only by an owner-written record beside the policy.
        "staged_reviews_held": {int(k): v for k, v in held.items()},
        "published_identities": int(policy["observed_hypothesis_identities"]),
        "research_status": str(policy.get("research_status")),
    }


def audit(
    canonical: Path,
    search_roots: list[Path],
    policy: dict[str, Any],
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    canonical = canonical.resolve()
    canonical_keys, canonical_records, canonical_ledgers = identities_of(canonical)
    trees: list[dict[str, Any]] = []
    merged: set[str] = set(canonical_keys)
    external_new: set[str] = set()
    for tree in candidate_trees(search_roots, canonical):
        keys, records, ledgers = identities_of(tree)
        if not keys:
            continue
        new = sorted(k for k in keys if k not in canonical_keys)
        external_new.update(new)
        merged.update(keys)
        trees.append(
            {
                "path": str(tree),
                "ledgers": ledgers,
                "immutable_execution_records": records,
                "distinct_hypothesis_identities": len(keys),
                "identities_not_in_canonical": len(new),
                "ledgers_holding_new_identities": sorted({p for k in new for p in keys[k]}),
            }
        )
    merged_count = len(merged)
    reached = [t for t in policy["staged_hard_reviews"] if merged_count >= t]
    unreviewed = [t for t in reached if t not in policy["staged_reviews_held"]]
    over_budget = merged_count > policy["budget"]
    if over_budget:
        status = STATUS_OVER_BUDGET
    elif unreviewed:
        status = STATUS_REVIEW_DUE
    elif external_new:
        status = STATUS_UNRECONCILED
    else:
        status = STATUS_COMPLETE
    stamp = (now or dt.datetime.now(dt.UTC)).isoformat()
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "author": AUTHOR,
        "generated_at": stamp,
        "claim_boundary": (
            "This audit counts hypothesis identities recorded in experiment ledgers outside the "
            "canonical tree, using the repository's own identity arithmetic. It does not judge "
            "whether those measurements were legitimate, does not import them, and does not "
            "change any published number. A reached staged review is cleared only by an owner "
            "record in config/trial_accounting_reviews.json under staged_reviews_held."
        ),
        "canonical_tree": str(canonical),
        "canonical": {
            "ledgers": canonical_ledgers,
            "immutable_execution_records": canonical_records,
            "distinct_hypothesis_identities": len(canonical_keys),
            "policy_observed_hypothesis_identities": policy["published_identities"],
        },
        "external_trees": trees,
        "external_identities_not_in_canonical": len(external_new),
        "merged_distinct_hypothesis_identities": merged_count,
        "budget": policy["budget"],
        "budget_remaining_after_merge": policy["budget"] - merged_count,
        "staged_hard_reviews": policy["staged_hard_reviews"],
        "staged_reviews_reached": reached,
        "staged_reviews_reached_without_record": unreviewed,
        "research_status": policy["research_status"],
        "status": status,
    }
    canonical_json = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = "sha256:" + hashlib.sha256(canonical_json).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO, help="canonical engine tree")
    ap.add_argument(
        "--search",
        type=Path,
        action="append",
        help="directory whose children are candidate checkouts (default: $HOME)",
    )
    ap.add_argument("--policy", type=Path, default=POLICY)
    ap.add_argument("--write", type=Path, default=OUTPUT)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    roots = args.search or [Path(os.path.expanduser("~"))]
    result = audit(args.root, roots, load_policy(args.policy))
    args.write.parent.mkdir(parents=True, exist_ok=True)
    args.write.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(
            f"{result['status']}: canonical "
            f"{result['canonical']['distinct_hypothesis_identities']} identities, "
            f"{result['external_identities_not_in_canonical']} external identities not in "
            f"canonical across {len(result['external_trees'])} tree(s), merged union "
            f"{result['merged_distinct_hypothesis_identities']} / budget {result['budget']}, "
            f"staged reviews reached without record: "
            f"{result['staged_reviews_reached_without_record'] or 'none'}"
        )
        for tree in result["external_trees"]:
            print(
                f"  {tree['path']}: {tree['identities_not_in_canonical']} new of "
                f"{tree['distinct_hypothesis_identities']} in {tree['ledgers']} ledgers"
            )
        print(f"wrote {args.write}")
    return 0 if result["status"] == STATUS_COMPLETE else 1


if __name__ == "__main__":
    sys.exit(main())
