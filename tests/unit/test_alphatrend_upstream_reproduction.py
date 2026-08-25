from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEALER = ROOT / "scripts/seal_alphatrend_upstream_replay_inputs.py"
RUNNER = ROOT / "scripts/run_alphatrend_upstream_clean_workspace.py"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_input_and_reference_manifest_is_hash_bound() -> None:
    module = _module(SEALER, "alphatrend_upstream_manifest")
    manifest = module.validate_published()
    assert manifest["private_input_snapshot"]["files"] == 410
    assert manifest["private_input_snapshot"]["market_lake_files"] == 408
    assert manifest["private_reference_output"]["files"] == 467
    assert manifest["rights_and_release"]["private_snapshot_may_be_published"] is False
    assert manifest["content_hash"] == module._content_hash(manifest)


def test_published_alphatrend_upstream_receipt_is_precise() -> None:
    module = _module(RUNNER, "alphatrend_upstream_runner")
    receipt = module.validate_published()
    assert receipt["passes_strategy_reproduction"] is True
    assert (
        receipt["alphavintage_benchmark_curve_regenerated_from_declared_strategy_inputs"]
        is True
    )
    assert receipt["historical_full_artifact_byte_exact"] is False
    assert receipt["historical_dsr_selection_context_reproduced"] is False
    assert receipt["author_clean_workspace_run_not_independent"] is True
    assert receipt["comparison"]["output_tree"]["different_files"] == [
        "walkforward.json"
    ]
    assert receipt["comparison"]["output_tree"]["byte_exact_files"] == 466
    assert receipt["comparison"]["equity_curve"]["bytes_exact"] is True
    assert receipt["comparison"]["equity_curve"]["max_absolute_equity_difference"] == 0.0
    assert receipt["comparison"]["walkforward_json"]["config_exact"] is True
    assert receipt["comparison"]["walkforward_json"]["summary_exact"] is True
    assert (
        receipt["comparison"]["walkforward_json"]["historical_validation_context_exact"]
        is False
    )
    assert receipt["content_hash"] == module._content_hash(receipt)
