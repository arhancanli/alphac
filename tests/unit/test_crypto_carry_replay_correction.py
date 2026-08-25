from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/seal_crypto_carry_replay_correction.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_replay_correction", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_correction_blocks_submission_without_erasing_history(tmp_path: Path) -> None:
    document = _module().run(tmp_path / "correction.json")
    assert document["status"] == "OPEN_CORRECTION_EXTERNAL_SUBMISSION_BLOCKED"
    assert document["historical_artifact_policy"] == "PRESERVE_DO_NOT_OVERWRITE_OR_DELETE"
    assert document["causal_findings"]["first_rebalance"]["status"] == "EXACTLY_ATTRIBUTED"
    assert document["causal_findings"]["full_path"]["status"] == (
        "SURVIVING_EVIDENCE_EXHAUSTED_EXACT_ADDITIVE_SPLIT_NOT_IDENTIFIABLE"
    )
    progress = document["remediation_progress"]
    assert progress["surviving_full_path_evidence_exhausted"] is True
    assert progress["prospective_private_input_snapshot_enforced"] is True
    assert progress["fresh_preregistered_snapshot_bound_run_completed"] is False
    assert document["publication_decision"]["external_submission_allowed"] is False
    assert document["publication_decision"]["website_may_present_historical_numbers"] is True
    assert document["trial_accounting"]["new_trials"] == 0
    assert document["content_hash"] == _module()._content_hash(document)
