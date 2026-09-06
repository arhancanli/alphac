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


def test_build_with_temp_output_root_leaves_real_archives_untouched(tmp_path) -> None:
    """build() computes/verifies archive bytes to compare against persisted evidence; it must
    not mutate the tracked, human-attested archives just because a caller wants that
    comparison. Every other test in this file therefore also builds into tmp_path -- this
    test is the one that pins the safety property directly."""
    module = _module()
    real_dir = module.OUTPUT_DIR
    before = {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(real_dir.glob("*.tar.gz"))
    }
    assert before, "expected pre-existing real archives to compare against"

    module.build(output_root=tmp_path)

    after = {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(real_dir.glob("*.tar.gz"))
    }
    assert after == before


def test_wave1_archives_are_deterministic_and_verify_outside_repository(tmp_path) -> None:
    module = _module()
    report = module.build(output_root=tmp_path)
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


def test_published_wave1_archive_receipt_matches_current_sources(tmp_path) -> None:
    module = _module()
    assert json.loads(module.RECEIPT.read_text()) == module.build(output_root=tmp_path)
