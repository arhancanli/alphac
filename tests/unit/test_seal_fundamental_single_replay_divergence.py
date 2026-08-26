from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "seal_fundamental_single_replay_divergence.py"
)
SPEC = importlib.util.spec_from_file_location("replay_divergence_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_curve_comparison_reports_exact_divergence(tmp_path: Path) -> None:
    original = tmp_path / "original.parquet"
    replay = tmp_path / "replay.parquet"
    pd.DataFrame({"ts": [1, 2, 3], "equity": [100.0, 101.0, 99.0]}).to_parquet(original)
    pd.DataFrame({"ts": [1, 2, 3], "equity": [100.0, 102.0, 98.0]}).to_parquet(replay)
    result = MODULE._curve_comparison(original, replay)
    assert result["timestamps_equal"] is True
    assert result["equity_mismatch_count"] == 2
    assert result["first_mismatch_row"] == 1
    assert result["original_equity_at_first_mismatch"] == 101.0
    assert result["replay_equity_at_first_mismatch"] == 102.0


def test_curve_comparison_refuses_to_seal_equal_curves(tmp_path: Path) -> None:
    original = tmp_path / "original.parquet"
    replay = tmp_path / "replay.parquet"
    frame = pd.DataFrame({"ts": [1, 2], "equity": [100.0, 101.0]})
    frame.to_parquet(original)
    frame.to_parquet(replay)
    with pytest.raises(ValueError, match="match exactly"):
        MODULE._curve_comparison(original, replay)
