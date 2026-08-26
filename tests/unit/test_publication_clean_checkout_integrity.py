from __future__ import annotations

import importlib.util
from pathlib import Path

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
    assert report["status"] == (
        "PASS_TRACKED_PREPARATION_BUNDLE_INTEGRITY_NOT_RESULT_REPRODUCTION"
    )
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
