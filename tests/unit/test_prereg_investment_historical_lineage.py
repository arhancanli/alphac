from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_prereg_investment_historical_lineage.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prereg_investment_lineage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prereg_investment_lineage_is_fail_closed_and_not_a_sleeve() -> None:
    document = _module().validate_published()

    assert document["status"] == "HISTORICAL_LINEAGE_RECOVERED_UPSTREAM_REPLAY_PENDING"
    assert document["classification"] == {
        "admitted_sleeve": False,
        "artifact_role": "HISTORICAL_GATE_INPUT_ONLY",
        "not_a_sleeve": True,
        "reason": (
            "The run dynamically resolved 6,880 ids and predates the later declaration; "
            "it cannot be relabeled as prospective evidence."
        ),
        "valid_execution_of_later_preregistration": False,
    }
    assert document["replay_gate"]["status"] == "PENDING"
    assert document["replay_gate"]["clean_workspace_replay_completed"] is False
    assert document["replay_gate"]["artifact_equivalence_established"] is False
    assert document["source"]["full_historical_dirty_source_tree_exactly_recovered"] is False
    assert document["preserved_raw_vendor_archives"]["files"] == 4
    assert (
        document["preserved_raw_vendor_archives"]["hashes_were_precommitted_before_historical_run"]
        is False
    )
    assert (
        document["surviving_market_data_state"]["corporate_actions"][
            "exact_historical_normalized_input_claimed"
        ]
        is False
    )


def test_prereg_investment_lineage_withholds_private_inputs_and_binds_artifact() -> None:
    document = _module().validate_published()

    assert document["private_execution_record"]["redistributed"] is False
    assert document["surviving_market_data_state"]["raw_rows_redistributed"] is False
    assert document["rights_and_release"]["raw_or_normalized_rows_publication_authorized"] is False
    assert document["rights_and_release"]["private_conversation_publication_authorized"] is False
    assert document["artifact"]["root_file_sha256"]["equity.parquet"] == (
        "e81f22c716da8590ee0a7129760ffa65f56b6967f8ef8c3c2ed86845cdf1645b"
    )
    assert document["historical_experiment_context"]["distinct_trials_through_target"] == 75
    assert document["historical_experiment_context"]["target_config_hash"] == ("e8c9b78fb4f7c195")
