from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_alphavintage_publication_bundle.py"


def _module():
    spec = importlib.util.spec_from_file_location("alphavintage_publication_bundle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_is_honest_sanitized_and_attributed(tmp_path: Path) -> None:
    module = _module()
    out = module.build(tmp_path / "bundle")
    paper = json.loads((out / "paper.json").read_text())
    broker = json.loads((out / "alpaca_paper_evidence.json").read_text())
    manifest = json.loads((out / "bundle_manifest.json").read_text())
    reproduction = json.loads((out / "reproduction.json").read_text())

    assert paper["authors"][0]["full_name"] == "Arhan Canli"
    assert paper["primary_decision"] == "KILLED"
    assert paper["peer_reviewed"] is False
    assert broker["capital_kind"] == "PAPER_ONLY"
    assert "account_identity" not in broker
    assert "current_equity" not in broker
    assert "holdings" not in broker
    assert manifest["status"] == "BUNDLE_INCOMPLETE"
    assert manifest["external_submission_claimed"] is False
    assert manifest["remaining_blockers"]
    assert reproduction["core_clean_environment_reproduction_completed"] is True
    assert reproduction["full_decision_clean_environment_reproduction_completed"] is True
    assert reproduction["full_pipeline_clean_environment_reproduction_completed"] is False
    assert reproduction["portable_core_reproduction"]["status"].startswith("PASS_")
    assert (out / "core_portable_reproduction_receipt.json").is_file()
    assert (out / "rtdsm_portable_fetch_receipt.json").is_file()
    full_decision = reproduction["portable_full_decision_reproduction"]
    assert full_decision["all_four_preregistered_decision_gates_replayed"] is True
    assert full_decision["upstream_benchmark_strategies_regenerated_from_raw_inputs"] is False
    assert full_decision["attempt_ledger"]["attempts_disclosed"] == 2
    assert (out / "full_decision_clean_workspace_receipt.json").is_file()
    assert (out / "full_decision_replay_attempt_ledger.json").is_file()
    upstream = reproduction["upstream_benchmark_strategy_reproduction"]
    assert upstream["benchmark_strategies_total"] == 3
    assert upstream["completed_author_run_strategy_replays"] == 3
    assert upstream["historical_strategy_output_equivalence_established"] == 2
    assert upstream["all_benchmark_replay_attempts_completed"] is True
    assert upstream["all_historical_benchmark_outputs_exact"] is False
    assert upstream["alphatrend_mf_live_fwd"]["equity_curve_byte_exact"] is True
    assert upstream["alphatrend_mf_live_fwd"]["byte_exact_output_files"] == 466
    assert upstream["alphamax_k30_dn_63"]["fresh_vendor_strategy_replay_completed"] is True
    assert (
        upstream["alphamax_k30_dn_63"]["historical_strategy_output_equivalence_established"]
        is False
    )
    assert upstream["alphamax_k30_dn_63"]["stored_historical_result_regraded"] is False
    assert upstream["prereg_investment"]["not_a_sleeve"] is True
    assert upstream["prereg_investment"]["strategy_curve_regenerated"] is True
    assert upstream["prereg_investment"]["lineage_status"] == (
        "HISTORICAL_LINEAGE_RECOVERED_UPSTREAM_REPLAY_PENDING"
    )
    assert upstream["prereg_investment"]["historical_source_tree_exact"] is False
    assert upstream["prereg_investment"]["input_manifest_status"].endswith(
        "CRYPTO_MEMBERSHIP_REPLAY_PENDING"
    )
    assert upstream["prereg_investment"]["raw_archive_normalization_replay_adjudicated"] is True
    assert upstream["prereg_investment"]["historical_full_artifact_byte_exact"] is True
    assert upstream["prereg_investment"]["byte_exact_output_files"] == 779
    assert (out / "alphatrend_upstream_replay_manifest.json").is_file()
    assert (out / "alphatrend_upstream_clean_workspace_receipt.json").is_file()
    assert (out / "alphamax_upstream_replay_manifest.json").is_file()
    assert (out / "alphamax_upstream_clean_workspace_receipt.json").is_file()
    assert (out / "prereg_investment_historical_lineage.json").is_file()
    assert (out / "prereg_investment_upstream_replay_manifest.json").is_file()
    assert (out / "prereg_investment_upstream_clean_workspace_receipt.json").is_file()


def test_checksums_bind_every_other_released_file(tmp_path: Path) -> None:
    module = _module()
    out = module.build(tmp_path / "bundle")
    rows = {}
    for line in (out / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        rows[name] = digest

    expected = {path.name for path in out.iterdir() if path.name != "SHA256SUMS"}
    assert set(rows) == expected
    for name, digest in rows.items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest


def test_bundle_build_is_byte_deterministic(tmp_path: Path) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    out = module.build(bundle)
    first = {path.name: path.read_bytes() for path in out.iterdir()}
    out = module.build(bundle)
    second = {path.name: path.read_bytes() for path in out.iterdir()}
    assert first == second
