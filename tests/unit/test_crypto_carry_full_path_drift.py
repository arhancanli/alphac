from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_crypto_carry_full_path_drift.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_full_path_drift", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_path_audit_exhausts_evidence_without_false_causal_precision(
    tmp_path: Path,
) -> None:
    module = _module()
    document = module.run(tmp_path / "full_path.json")
    assert document["status"] == (
        "PASS_SURVIVING_EVIDENCE_EXHAUSTED_EXACT_ADDITIVE_CAUSAL_SPLIT_NOT_IDENTIFIABLE"
    )
    assert document["declared_run_alignment"]["leg_count"] == 25
    assert document["declared_run_alignment"]["n_rebalances_source"] == 224
    assert document["declared_run_alignment"]["n_rebalances_replay"] == 224
    observed = document["observed_path"]
    assert observed["equity"]["timestamps_exactly_equal"] is True
    assert observed["equity"]["rows"] == 37_776
    assert observed["orders"]["columns"]["decision_price"]["all_finite_pairs_exact"] is True
    assert observed["funding"]["columns"]["rate"]["all_finite_pairs_exact"] is True
    assert observed["positions"]["columns"]["mark"]["all_finite_pairs_exact"] is True
    decision = document["decision"]
    assert decision["full_path_drift_quantified"] is True
    assert decision["surviving_evidence_exhausted"] is True
    assert decision["exact_additive_causal_decomposition_possible"] is False
    assert decision["repeat_current_state_replay_would_resolve_missing_history"] is False
    assert document["trial_accounting"]["new_trials"] == 0
    assert document["content_hash"] == module._content_hash(document)


def test_artifact_bindings_cover_every_surviving_leg_ledger(tmp_path: Path) -> None:
    document = _module().run(tmp_path / "full_path.json")
    bindings = document["bindings"]
    assert bindings["historical_artifact"]["files"] == 127
    assert bindings["current_state_replay"]["files"] == 177
    assert (
        bindings["historical_artifact"]["root_sha256"]
        != bindings["current_state_replay"]["root_sha256"]
    )
    archaeology = document["code_archaeology"]
    assert archaeology["historical_run_exact_commit_bound"] is False
    assert archaeology["repository_state_candidate_not_run_authority"]["commit"].startswith(
        "fd3e930"
    )
