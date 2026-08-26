from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "build_fundamental_single_curve_evidence.py"
    spec = importlib.util.spec_from_file_location("fundamental_single_curve_evidence_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_curve_evidence_reconciles_and_is_fail_closed() -> None:
    evidence, diversification = _module().build_evidence()
    assert evidence["hypothesis_key"] == "1d2924f28fe31a9a"
    assert evidence["verdict"] == "KILL"
    assert evidence["metrics"]["observations"] == 5_384
    assert evidence["metrics"]["annualized_sharpe"] < 0
    assert evidence["metrics"]["current_union_trials"] == 228
    assert diversification["report"]["bootstrap_samples"] == 2_000
    assert diversification["report"]["bootstrap_block_size"] == 21
    assert diversification["alignment"]["internal_missing_by_series"] == {}
    assert "remain separate required evidence" in evidence["claim_boundary"]
