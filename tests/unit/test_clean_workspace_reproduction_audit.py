from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "audit_clean_workspace_reproduction_contracts.py"


def _module():
    spec = importlib.util.spec_from_file_location("clean_workspace_reproduction", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_reproduction_contracts_are_present_without_overstating_portability() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == (
        "PASS_CONTRACT_AUDIT_ONE_FULL_DECISION_THREE_UPSTREAM_STRATEGY_REPLAYS_"
        "NO_FULL_PIPELINE_REPLAYS"
    )
    assert report["counts"] == {
        "sleeves": 16,
        "repository_command_contracts_present_and_bound": 16,
        "archive_standalone_reproductions_executable": 0,
        "full_clean_workspace_reproductions_completed": 0,
        "portable_core_only_reproductions_completed": 0,
        "portable_full_decision_reproductions_completed": 1,
        "upstream_strategy_curve_replays_completed": 3,
        "upstream_historical_strategy_output_equivalences": 2,
        "failed_upstream_strategy_replay_attempts_completed": 1,
        "independent_human_reproductions_completed": 0,
    }
    assert report["failures"] == []
    assert all(
        record["repository_command_targets_present_and_bound"]
        and record["repository_environment_files_present_and_bound"]
        for record in report["records"]
    )
    assert all(
        record["archive_standalone_reproduction_executable"] is False
        and record["raw_input_portability_established"] is False
        for record in report["records"]
    )
    assert report["content_hash"] == module._content_hash(report)


def test_command_semantics_distinguish_core_audit_and_deferred_work() -> None:
    report = _module().build()
    by_key = {record["registry_key"]: record for record in report["records"]}
    assert by_key["alphavintage_macro_surprise"]["command_semantics"] == (
        "PORTABLE_FULL_DECISION_REPLAY_ALL_THREE_UPSTREAM_REPLAYS_COMPLETE_"
        "TWO_EXACT_ONE_DIVERGENT"
    )
    assert by_key["alphamax_equity_momentum"]["command_semantics"] == (
        "AUTHOR_RUN_UPSTREAM_STRATEGY_REPLAY_FAILED_EXACT_EQUIVALENCE"
    )
    assert by_key["alphamax_equity_momentum"]["author_upstream_strategy_replay"][
        "passes_strategy_reproduction"
    ] is False
    assert by_key["energy_inventory"]["command_semantics"] == (
        "AUDIT_ONLY_REBUILD_OR_CORRECTION_NOT_FULL_RESULT_GENERATION"
    )


def test_persisted_clean_workspace_audit_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.OUTPUT.read_text()) == module.build()
