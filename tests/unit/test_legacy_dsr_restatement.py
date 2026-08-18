"""The historical DSR correction is reproducible and never silently estimates missing paths."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "restate_legacy_dsr.py"
    spec = importlib.util.spec_from_file_location("legacy_dsr_restatement_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.workspace_evidence
def test_restatement_uses_current_union_and_retires_missing_return_families() -> None:
    payload = _load().build()
    summary = payload["summary"]

    assert payload["selection_context"]["n_hypotheses"] == 162
    assert summary == {
        "historical_exception_families": 12,
        "restated_families": 5,
        "restated_variants": 33,
        "retired_families": 7,
        "restated_variants_clearing_dsr_0_95": 0,
    }
    assert all(row["returns_sha256"] for row in payload["restated_variants"])
    assert all(row["status"] == "RESTATED_CURRENT_UNION" for row in payload["restated_variants"])
    assert all(
        row["status"] == "RETIRED_MISSING_RETURN_SERIES"
        for row in payload["retired_families"]
    )
