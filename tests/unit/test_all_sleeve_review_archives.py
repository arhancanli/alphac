from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "package_all_sleeve_review_archives.py"


def _module():
    spec = importlib.util.spec_from_file_location("all_sleeve_review_archives", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_sleeve_archives_are_deterministic_raw_row_free_and_fail_closed() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == "PASS_ARCHIVE_INTEGRITY_ONLY_RIGHTS_AND_REPLAY_BLOCKED"
    assert report["counts"] == {
        "planned_sleeves": 16,
        "archives_built": 16,
        "archives_passed": 16,
        "raw_input_members": 0,
    }
    assert report["failures"] == []
    assert report["result_generation_replayed"] is False
    assert report["clean_environment_replay_completed"] is False
    assert report["independent_replication"] is False
    assert report["redistribution_rights_cleared_for_all_sleeves"] is False
    assert report["submission_claimed"] is False
    assert all(record["passed"] for record in report["records"])
    assert all(record["external_publication_url"] is None for record in report["records"])
    assert all(record["deterministic_second_build_identical"] for record in report["records"])
    assert all(
        not record["verification"]["raw_input_archive_members"]
        for record in report["records"]
    )
    assert all(
        record["verification"]["workspace_outside_repository"]
        for record in report["records"]
    )
    assert report["content_hash"] == module._content_hash(report)


def test_archive_roots_are_sleeve_specific_not_ambiguous_version_directories() -> None:
    report = _module().build()
    roots = [record["archive_root"] for record in report["records"]]
    assert len(roots) == len(set(roots)) == 16
    assert all(not root.startswith("v") for root in roots)


def test_persisted_all_sleeve_archive_receipt_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.RECEIPT.read_text()) == module.build()
