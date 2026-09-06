from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module(name: str):
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_active_ownership_is_selected_without_return_access() -> None:
    module = _module("seal_next_sleeve_selection")
    payload = module.build()
    assert payload["selected_candidate"]["id"] == "active_ownership_escalation"
    assert payload["selected_candidate"]["return_trial_authorized"] is False
    assert payload["selected_candidate"]["blind_labels_completed"] == 0
    assert payload["selected_candidate"]["blind_labels_required"] == 48
    assert payload["return_data_opened"] is False
    assert payload["hypotheses_spent"] == 0
    assert json.loads(module.OUTPUT.read_text(encoding="utf-8")) == payload
    for relative, expected_sha256 in payload["lineage"].items():
        assert hashlib.sha256((REPO / relative).read_bytes()).hexdigest() == expected_sha256


def test_external_review_archive_is_deterministic_and_prediction_blind() -> None:
    module = _module("package_active_ownership_blind_review")
    archive_a, receipt_a = module.build_archive()
    archive_b, receipt_b = module.build_archive()
    assert archive_a == archive_b
    assert receipt_a == receipt_b
    assert receipt_a["files"] == 54
    assert receipt_a["documents"] == 48
    assert receipt_a["labels_completed"] == 0
    assert receipt_a["prediction_blind"] is True
    assert receipt_a["archive_sha256"] == module._sha256_bytes(archive_a)
    assert receipt_a["public_archive_path"] == (
        "/glassbox/active_ownership_13d_item4_v3_blind.tar.gz"
    )
    with tarfile.open(fileobj=io.BytesIO(archive_a), mode="r:gz") as handoff:
        names = handoff.getnames()
    assert len(names) == 54
    assert "active_ownership_13d_item4_v3_blind/verify_review.py" in names
    assert sum(name.endswith(".txt") for name in names) == 48
