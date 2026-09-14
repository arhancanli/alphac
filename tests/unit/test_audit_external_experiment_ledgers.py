"""The trial union must be computed over every checkout on the machine, not one tree.

2026-09-12/13: a research session ran 118 new hypothesis identities in a clone of this repository.
Each was ledgered correctly in the clone; none was visible here, so the public ledger kept
publishing 229 identities and "171 remaining" while the governed union stood at 347, past the
320 staged review. These tests pin the audit that makes such a split visible, using synthetic
trees built through the real ExperimentLog so the identity arithmetic is the published one.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from alphaforge.validation.experiments import ExperimentLog

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_external_experiment_ledgers.py"
_SPEC = importlib.util.spec_from_file_location("audit_external_experiment_ledgers", SCRIPT)
assert _SPEC and _SPEC.loader
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

NOW = dt.datetime(2026, 9, 14, 9, 0, tzinfo=dt.UTC)


def _tree(path: Path, configs: list[dict], ledger: str = "var/experiments.jsonl") -> Path:
    (path / "configs").mkdir(parents=True, exist_ok=True)
    (path / "configs" / "base.yaml").write_text("profile: test\n")
    log = ExperimentLog(path / ledger)
    (path / ledger).parent.mkdir(parents=True, exist_ok=True)
    for i, config in enumerate(configs):
        log.record(
            config,
            sharpe_ann=0.1 * i,
            sharpe_per_period=0.01 * i,
            n_obs=500,
            skew=0.0,
            kurtosis=3.0,
            now_ms=1_700_000_000_000 + i,
        )
    return path


def _policy(budget: int = 400, staged: list[int] | None = None, held: dict | None = None) -> dict:
    return {
        "budget": budget,
        "staged_hard_reviews": staged if staged is not None else [320, 360, 400],
        "staged_reviews_held": held or {},
        "published_identities": 3,
        "research_status": "ACTIVE_STAGED_PROSPECTIVE_BUDGET",
    }


def _cfg(n: int, **extra: object) -> dict:
    return {"family": "f", "param": n, "start": "2020-01-01", "end": "2025-01-01", **extra}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    canonical = _tree(tmp_path / "alphaforge", [_cfg(1), _cfg(2), _cfg(3)])
    assert canonical.is_dir()
    return tmp_path


def test_no_external_trees_means_the_union_is_complete(home: Path) -> None:
    result = MOD.audit(home / "alphaforge", [home], _policy(), now=NOW)
    assert result["status"] == MOD.STATUS_COMPLETE
    assert result["external_trees"] == []
    assert result["canonical"]["distinct_hypothesis_identities"] == 3
    assert result["merged_distinct_hypothesis_identities"] == 3


def test_a_clone_with_new_identities_is_reported_and_priced(home: Path) -> None:
    # Two identities the canonical tree already has, two it has never seen, one ledger under
    # artifacts/ the way legacy campaigns file them.
    clone = _tree(home / "alphac-clone", [_cfg(2), _cfg(3), _cfg(4)])
    _tree(clone, [_cfg(5)], ledger="artifacts/analysis/study/candidate/experiments.jsonl")
    result = MOD.audit(home / "alphaforge", [home], _policy(), now=NOW)
    assert result["status"] == MOD.STATUS_UNRECONCILED
    assert result["external_identities_not_in_canonical"] == 2
    assert result["merged_distinct_hypothesis_identities"] == 5
    assert result["budget_remaining_after_merge"] == 395
    (tree,) = result["external_trees"]
    assert tree["distinct_hypothesis_identities"] == 4
    assert tree["identities_not_in_canonical"] == 2
    assert tree["ledgers_holding_new_identities"] == [
        "artifacts/analysis/study/candidate/experiments.jsonl",
        "var/experiments.jsonl",
    ]


def test_window_only_remeasurements_in_a_clone_are_not_new_identities(home: Path) -> None:
    """The published arithmetic strips only start/end; a clone that re-ran an existing idea over
    a different window spent nothing, and the audit must say so."""
    _tree(home / "alphac-clone", [_cfg(1, start="2021-01-01", end="2026-01-01")])
    result = MOD.audit(home / "alphaforge", [home], _policy(), now=NOW)
    assert result["status"] == MOD.STATUS_COMPLETE
    assert result["external_identities_not_in_canonical"] == 0


def test_any_other_field_change_is_a_new_identity(home: Path) -> None:
    _tree(home / "alphac-clone", [_cfg(1, cost_multiplier=5.0)])
    result = MOD.audit(home / "alphaforge", [home], _policy(), now=NOW)
    assert result["external_identities_not_in_canonical"] == 1


def test_reaching_a_staged_review_without_a_record_fails(home: Path) -> None:
    _tree(home / "alphac-clone", [_cfg(n) for n in range(4, 10)])  # merged = 9
    result = MOD.audit(home / "alphaforge", [home], _policy(staged=[8, 12]), now=NOW)
    assert result["status"] == MOD.STATUS_REVIEW_DUE
    assert result["staged_reviews_reached"] == [8]
    assert result["staged_reviews_reached_without_record"] == [8]


def test_an_owner_record_clears_the_reached_review(home: Path) -> None:
    _tree(home / "alphac-clone", [_cfg(n) for n in range(4, 10)])
    held = {8: {"reviewed_by": "owner", "date": "2026-09-14"}}
    result = MOD.audit(home / "alphaforge", [home], _policy(staged=[8, 12], held=held), now=NOW)
    assert result["status"] == MOD.STATUS_UNRECONCILED
    assert result["staged_reviews_reached_without_record"] == []


def test_exceeding_the_budget_outranks_everything(home: Path) -> None:
    _tree(home / "alphac-clone", [_cfg(n) for n in range(4, 10)])
    result = MOD.audit(home / "alphaforge", [home], _policy(budget=8, staged=[8]), now=NOW)
    assert result["status"] == MOD.STATUS_OVER_BUDGET
    assert result["budget_remaining_after_merge"] == -1


def test_the_canonical_tree_its_worktrees_and_archives_are_handled(home: Path) -> None:
    """The canonical tree must not count itself; an agent worktree inside it must count; a
    directory named as an archive is withdrawn evidence and must not."""
    canonical = home / "alphaforge"
    _tree(canonical / ".claude" / "worktrees" / "agent-x", [_cfg(40)])
    _tree(home / "alphac-archive-2026", [_cfg(41)])
    result = MOD.audit(canonical, [home], _policy(), now=NOW)
    paths = [t["path"] for t in result["external_trees"]]
    assert paths == [str(canonical / ".claude" / "worktrees" / "agent-x")]
    assert result["external_identities_not_in_canonical"] == 1


def test_a_directory_without_an_engine_config_is_ignored(home: Path) -> None:
    other = home / "not-an-engine"
    (other / "var").mkdir(parents=True)
    ExperimentLog(other / "var" / "experiments.jsonl").record(
        _cfg(99),
        sharpe_ann=0.0,
        sharpe_per_period=0.0,
        n_obs=1,
        skew=0.0,
        kurtosis=3.0,
        now_ms=1,
    )
    result = MOD.audit(home / "alphaforge", [home], _policy(), now=NOW)
    assert result["external_trees"] == []


def test_result_is_hash_bound_and_the_cli_exit_code_reflects_the_status(
    home: Path, tmp_path: Path
) -> None:
    _tree(home / "alphac-clone", [_cfg(7)])
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "hypothesis_identity_budget": 400,
                "observed_hypothesis_identities": 3,
                "research_status": "ACTIVE",
                "prospective_v7_review": {"staged_hard_reviews": [320]},
            }
        )
    )
    out = tmp_path / "out" / "result.json"
    rc = MOD.main(
        [
            "--root",
            str(home / "alphaforge"),
            "--search",
            str(home),
            "--policy",
            str(policy_path),
            "--write",
            str(out),
            "--quiet",
        ]
    )
    assert rc == 1
    document = json.loads(out.read_text())
    content_hash = document.pop("content_hash")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == "sha256:" + MOD.hashlib.sha256(canonical).hexdigest()
    assert document["status"] == MOD.STATUS_UNRECONCILED


def test_the_real_policy_file_parses_and_names_the_staged_reviews() -> None:
    """The audit reads the owner-only policy; if its shape drifts the guard must fail loudly."""
    policy = MOD.load_policy(MOD.POLICY)
    assert policy["budget"] >= max(policy["staged_hard_reviews"])
    assert policy["staged_hard_reviews"] == sorted(policy["staged_hard_reviews"])
