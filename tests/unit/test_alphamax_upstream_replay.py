from __future__ import annotations

import importlib.util
import json
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


def test_pinned_source_archive_is_safe_and_reproducible() -> None:
    runner = _module(
        "alphamax_upstream_runner_source",
        "scripts/run_alphamax_upstream_clean_workspace.py",
    )

    with tempfile.TemporaryDirectory(prefix="test-alphamax-source-") as raw:
        first = runner._safe_extract_git_archive(Path(raw))
    with tempfile.TemporaryDirectory(prefix="test-alphamax-source-") as raw:
        second = runner._safe_extract_git_archive(Path(raw))

    assert first == second
    assert first["commit"] == runner.SOURCE_COMMIT
    assert first["full_dirty_historical_source_tree_recovered"] is False


def test_failure_receipt_is_fail_closed_and_self_hashing() -> None:
    runner = _module(
        "alphamax_upstream_runner_failure",
        "scripts/run_alphamax_upstream_clean_workspace.py",
    )
    record = {
        "command": "uv run af research walkforward",
        "exit_code": 2,
        "stdout_sha256": "0" * 64,
        "stderr_sha256": "1" * 64,
        "stdout_tail": "",
        "stderr_tail": "synthetic test failure",
    }

    document = runner._failure_document(runner.ReplayCommandError(record))

    assert document["status"] == "FAIL_UPSTREAM_STRATEGY_REPLAY"
    assert document["passes_strategy_reproduction"] is False
    assert document["strategy_sufficient_fresh_vendor_reacquisition_completed"] is False
    assert document["full_historical_universe_lookback_reacquired"] is False
    assert document["failure"]["command_record"] == record
    assert document["content_hash"] == runner._content_hash(document)


def test_published_fresh_vendor_replay_preserves_the_failed_exact_comparison() -> None:
    runner = _module(
        "alphamax_upstream_runner_published",
        "scripts/run_alphamax_upstream_clean_workspace.py",
    )
    document = json.loads(runner.OUTPUT.read_text())

    assert document["status"] == "FAIL_UPSTREAM_STRATEGY_REPLAY_FRESH_VENDOR_INPUTS_DIFFER"
    assert document["passes_strategy_reproduction"] is False
    assert document["comparison"]["walkforward_json"]["config_exact"] is True
    assert document["comparison"]["equity_curve"]["timestamps_exact"] is True
    assert document["comparison"]["equity_curve"]["log_returns_exact"] is False
    assert document["comparison"]["equity_curve"]["max_absolute_equity_difference"] == (
        574.6900212383189
    )
    historical = document["comparison"]["walkforward_json"]["historical_validation"]
    replay = document["comparison"]["walkforward_json"]["replay_validation"]
    assert historical["sr_ann"] == 0.9070840668515086
    assert replay["sr_ann"] == 0.9213246144999775
    assert historical["clears_dsr_gate"] is False
    assert replay["clears_dsr_gate"] is False
    assert document["content_hash"] == runner._content_hash(document)
