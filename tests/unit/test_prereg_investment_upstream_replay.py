from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _module(name: str, relative: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_manifest_withholds_rows_and_keeps_replay_pending() -> None:
    seal = _module(
        "prereg_investment_seal",
        "scripts/seal_prereg_investment_upstream_replay_inputs.py",
    )
    document = seal.validate_published()

    assert document["status"].endswith("CRYPTO_MEMBERSHIP_REPLAY_PENDING")
    assert document["classification"]["not_a_sleeve"] is True
    assert document["replay_status"]["clean_workspace_completed"] is False
    assert document["replay_status"]["strategy_output_equivalence_established"] is False
    assert document["private_input_snapshot"]["raw_or_normalized_rows_redistributed"] is False
    membership = document["private_input_snapshot"]["crypto_membership"]
    assert membership["instrument_ids"] == 60
    assert membership["historical_membership_intervals_exact"] is False
    assert membership["classification"] == ("ARTIFACT_INFORMED_MINIMAL_ZERO_HELD_RECONSTRUCTION")


def test_recovered_source_patches_apply_to_pinned_predecessor() -> None:
    runner = _module(
        "prereg_investment_runner",
        "scripts/run_prereg_investment_upstream_clean_workspace.py",
    )
    lineage = _module(
        "prereg_investment_lineage_for_runner",
        "scripts/build_prereg_investment_historical_lineage.py",
    )

    with tempfile.TemporaryDirectory(prefix="test-prereg-investment-source-") as raw:
        workspace = Path(raw)
        source = runner._extract_source(workspace)
        bindings = runner._apply_recovered_patches(workspace, lineage)

    assert source["predecessor_commit"] == runner.SOURCE_COMMIT
    assert set(bindings) == {
        "configs/equity.yaml",
        "scripts/sharadar_load.py",
        "src/alphaforge/features/library/equity_fundamental.py",
    }
