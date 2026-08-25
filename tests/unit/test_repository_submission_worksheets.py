from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_repository_submission_worksheets.py"


def _module():
    spec = importlib.util.spec_from_file_location("repository_submission_worksheets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worksheets_cover_the_plan_and_fail_closed() -> None:
    module = _module()
    report = module.build()
    assert report["passes"] is True
    assert report["counts"] == {
        "sleeve_papers": 16,
        "zenodo_paper_worksheets": 16,
        "zenodo_bundle_worksheets": 16,
        "ssrn_worksheets": 0,
        "planned_external_records": 32,
        "submission_ready": 0,
        "external_identifiers_claimed": 0,
    }
    worksheets = [
        worksheet for record in report["records"] for worksheet in record["worksheets"].values()
    ]
    assert all(worksheet["blockers"] for worksheet in worksheets)
    assert all(worksheet["submission_claimed"] is False for worksheet in worksheets)
    assert all(worksheet["state"].startswith("BLOCKED_LOCAL_WORKSHEET") for worksheet in worksheets)
    assert all(
        worksheet["content_hash"] == module._content_hash(worksheet) for worksheet in worksheets
    )
    assert report["content_hash"] == module._content_hash(report)
    rights = report["source_bindings"]["all_sleeve_data_rights_audit"]
    assert rights["source_mappings_complete"] == 16
    assert rights["data_license_reviews_complete"] == 0
    replay = report["source_bindings"]["clean_workspace_reproduction_audit"]
    assert replay["full_clean_workspace_reproductions_completed"] == 0
    assert replay["independent_human_reproductions_completed"] == 0


def test_unverified_identifiers_and_owner_fields_remain_unset() -> None:
    report = _module().build()
    for record in report["records"]:
        paper = record["worksheets"]["zenodo_paper"]
        bundle = record["worksheets"]["zenodo_reproducibility_bundle"]
        for worksheet in (paper, bundle):
            assert worksheet["metadata"]["publication_date"] is None
            assert worksheet["metadata"]["doi"] is None
            assert worksheet["metadata"]["doi_reserved"] is False
        assert paper["metadata"]["license_selection"] is None
        assert bundle["metadata"]["license_selections"] == []
        if "ssrn_working_paper" in record["worksheets"]:
            ssrn = record["worksheets"]["ssrn_working_paper"]
            assert ssrn["metadata"]["authors"][0]["email"] is None
            assert ssrn["metadata"]["copyright_holder"] is None
            assert ssrn["metadata"]["external_identifier"] is None


def test_published_receipt_and_per_sleeve_files_match_current_sources() -> None:
    module = _module()
    report = module.build()
    assert json.loads(module.OUTPUT.read_text()) == report
    for record in report["records"]:
        out = module.WORKSHEET_ROOT / record["bundle_slug"]
        for name, worksheet in record["worksheets"].items():
            assert json.loads((out / f"{name}.json").read_text()) == worksheet


def test_repository_requirement_snapshot_uses_only_official_sources() -> None:
    requirements = json.loads(
        (ROOT / "config" / "scholarly_repository_requirements.json").read_text()
    )
    allowed_hosts = {
        "help.zenodo.org",
        "www.elsevier.support",
        "www.ssrn.com",
        "blog.ssrn.com",
        "info.arxiv.org",
        "help.osf.io",
    }
    urls = [
        url
        for repository in requirements["repositories"].values()
        for url in repository["official_sources"]
    ]
    assert urls
    assert {urlparse(url).hostname for url in urls} <= allowed_hosts
    assert (
        requirements["repositories"]["OSF_PREPRINTS"]["project_policy"]["default_route_permitted"]
        is False
    )
    assert (
        requirements["repositories"]["ARXIV"]["project_policy"]["current_sleeve_records_targeted"]
        == 0
    )
    assert (
        requirements["repositories"]["SSRN"]["project_policy"]["current_sleeve_records_targeted"]
        == 0
    )
