from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_publication_clean_checkout.py"


def _module():
    spec = importlib.util.spec_from_file_location("publication_clean_checkout", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracked_publication_bundles_pass_without_overstating_reproduction() -> None:
    module = _module()
    report = module.build()
    assert report["passes"] is True
    assert report["status"] == ("PASS_TRACKED_PREPARATION_BUNDLE_INTEGRITY_NOT_RESULT_REPRODUCTION")
    assert report["counts"]["bundles"] == 16
    assert report["counts"]["full_clean_result_reproductions"] == 0
    assert report["counts"]["independent_human_reproductions"] == 0
    assert report["counts"]["external_submissions"] == 0
    assert report["counts"]["data_license_reviews_complete"] == 0
    assert report["failures"] == []
    assert all(record["status"] == "BUNDLE_INCOMPLETE" for record in report["records"])
    assert report["content_hash"] == module._content_hash(report)


def test_claim_boundary_preserves_the_return_and_review_limits() -> None:
    boundary = _module().build()["claim_boundary"].lower()
    assert "does not regenerate strategy returns" in boundary
    assert "independent replication or peer review" in boundary
    assert "every bundle remains bundle_incomplete" in boundary


def test_archival_resolution_is_visible_without_rebinding_old_receipts() -> None:
    report = _module().build()
    assert report["passes"] is True
    for record in report["records"]:
        archived = [
            r for r in record["environment_resolution"] if r["status"] == "HISTORICAL_ARCHIVE_ONLY"
        ]
        assert len(archived) == 1
        assert archived[0]["original_path"] == "uv.lock"
        assert archived[0]["sha256"] != archived[0]["active_sha256"]
        assert record["active_environment_replay_established"] is False


def test_code_drift_cannot_resolve_via_environment_archive(tmp_path: Path) -> None:
    module = _module()
    module.ROOT = tmp_path
    (tmp_path / "code.py").write_text("changed code")
    with pytest.raises(ValueError, match="stale code binding"):
        module._verify_bindings(
            {"code_bindings": {"code.py": "0" * 64}, "environment_bindings": {"uv.lock": "0" * 64}},
            {"code.py", "uv.lock"},
            tmp_path / "reproduction.json",
        )
