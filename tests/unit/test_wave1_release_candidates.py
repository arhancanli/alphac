from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "package_wave1_release_candidates.py"


def _module():
    spec = importlib.util.spec_from_file_location("wave1_release_candidates", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wave1_archives_are_deterministic_and_verify_outside_repository() -> None:
    module = _module()
    report = module.build()
    assert report["status"] == "PASS_PORTABLE_ARCHIVE_INTEGRITY_ONLY"
    assert report["archives"] == 5
    assert report["failures"] == []
    assert report["result_generation_replayed"] is False
    assert report["independent_replication"] is False
    assert report["submission_claimed"] is False
    assert all(record["passed"] for record in report["records"])
    assert all(record["deterministic_second_build_identical"] for record in report["records"])
    assert all(
        record["verification"]["workspace_outside_repository"] for record in report["records"]
    )
    assert report["content_hash"] == module._content_hash(report)


def test_published_wave1_archive_receipt_matches_current_sources() -> None:
    module = _module()
    assert json.loads(module.RECEIPT.read_text()) == module.build()
