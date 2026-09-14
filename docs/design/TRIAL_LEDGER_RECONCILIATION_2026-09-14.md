# Trial ledger reconciliation, 2026-09-14

Status: FINDING RECORDED, GUARD SHIPPED, RECONCILIATION NOT PERFORMED. The union of hypothesis
identities this project has actually measured is larger than the union it publishes, because
measurements were run in a clone of the repository that the canonical accounting cannot see.
This document states the measured facts, the guard that now makes such a split visible nightly,
and the two honest ways to close it. Closing it is an owner decision.

## What was measured

Command (from the repository root, any time):

```sh
uv run python scripts/audit_external_experiment_ledgers.py
```

Artifact: `artifacts/analysis/external_experiment_ledgers/result.json` (hash-bound, regenerated
on every run and by the nightly health board into `var/health/external_ledgers.json`). The run of
2026-09-14 reported:

| quantity | value | source |
| --- | ---: | --- |
| canonical distinct hypothesis identities (this tree, `ExperimentUnion.discover`) | 229 | `result.json` `canonical.distinct_hypothesis_identities` |
| public ledger `distinct_hypothesis_identities` | 229 | `~/meridian/public/glassbox/trial_ledger.json` |
| external engine trees found under `$HOME` | 1 | `~/alphac-prospective-pause-20260911` |
| profile ledgers in that tree | 127 | `result.json` `external_trees[0].ledgers` |
| distinct identities in that tree | 347 | `result.json` `external_trees[0].distinct_hypothesis_identities` |
| identities not in canonical | 118 | `result.json` `external_identities_not_in_canonical` |
| merged distinct hypothesis identities | 347 | `result.json` `merged_distinct_hypothesis_identities` |
| budget | 400 | `config/trial_accounting.json` |
| staged hard reviews reached without a record | 320 | `result.json` `staged_reviews_reached_without_record` |

The clone is a git checkout at the same commit as this tree's `main` (`095eded`) with 699
uncommitted files; its new ledgers sit under `artifacts/analysis/*_2026091{1,2,3}/` and its
identity packet directory holds 348 packets against this tree's 230. The identity arithmetic is
the repository's own: a hypothesis identity is a configuration with only the `start`/`end`
window keys removed. Baseline, candidate and cost-stress runs of one study therefore count as
separate identities here exactly as they do on the public ledger, which is why the clone's own
prose ("union is now 256") understates its ledgers: it counted governed reservations, not
configurations, and the published number counts configurations.

## Why this matters

Deflation is a property of the search. Every deflated Sharpe the site publishes, and the
book-level DSR gate the admission contract applies, uses the union count as selection N. A
union of 229 where 347 were measured flatters every published deflated figure, and the
`budget_remaining` of 171 the site shows is really 53. Separately, the owner's policy
(`prospective_v7_review.staged_hard_reviews`) says registration pauses at 320 for a fresh
owner review; the search passed 320 on 2026-09-13 without one.

Nothing in the clone's accounting was wrong. Each measurement was ledgered, reserved and
packeted through the governed path. The defect is structural: the union was computed over one
tree while measurements ran in two.

## The guard

`scripts/audit_external_experiment_ledgers.py` walks every engine checkout under `$HOME` (a
directory with `configs/base.yaml`, plus agent worktrees under `.claude/worktrees`, minus the
canonical tree and anything named as an archive), computes each tree's union with the same
`ExperimentUnion` the public ledger uses, and reports the identities the canonical tree cannot
see, the merged count against the budget, and which staged reviews the merged count has reached
without a record. `scripts/health_check.py` runs it nightly as `C11-external-ledgers`: PASS when
the canonical tree is the whole union, WARN when unreconciled identities exist, FAIL when a
staged review has been reached without a record or the budget is exceeded. A reached review is
cleared only by an owner-written `staged_reviews_held` entry in `config/trial_accounting.json`,
so the guard cannot be quietened by anything short of the review it exists to demand.

Tests: `tests/unit/test_audit_external_experiment_ledgers.py` (synthetic trees built through the
real `ExperimentLog`, including the window-only exemption, worktrees, archives and the CLI exit
code) and `tests/unit/test_health_external_ledgers.py` (the verdict mapping, and that silence is
a WARN, never a PASS).

## The two honest ways to close it

1. **Import.** Merge the clone's 127 profile ledgers into the canonical tree under
   `artifacts/analysis/` (they are already in the layout `ExperimentUnion.discover` reads),
   regenerate the public ledger, record the 320 review in `config/trial_accounting.json` as
   `staged_reviews_held`, and let every published deflated figure move to N = 347. This is the
   path the policy's definitions imply: every measured configuration is a trial.
2. **Withdraw.** Declare the clone's measurements withdrawn evidence by moving them under a
   path containing `archive`, which `discover()` and this audit both exclude, and record why. This
   is only honest if the measurements are never used to select anything, including the
   "corrected baselines" the clone's reports describe.

Either way, no further identity should be reserved in either tree until the owner has chosen,
because every new reservation in the clone widens the gap and every new reservation here reuses
ordinals the clone has already spent.

## What this document does not claim

It does not judge whether any clone measurement was economically meaningful, does not restate
any Sharpe or drawdown from the clone's reports, and does not change a published number. The
public ledger still reads 229 until the owner's decision is implemented and republished.
