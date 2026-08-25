#!/usr/bin/env python3
"""Build fail-closed repository worksheets without performing account actions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
PLAN: Final = ROOT / "artifacts" / "publication" / "external_submission_plan.json"
REQUIREMENTS: Final = ROOT / "config" / "scholarly_repository_requirements.json"
ARCHIVES: Final = ROOT / "artifacts" / "publication" / "all_sleeve_review_archives.json"
DATA_RIGHTS: Final = ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
CLEAN_REPRODUCTION: Final = (
    ROOT / "artifacts" / "publication" / "clean_workspace_reproduction_audit.json"
)
OUTPUT: Final = ROOT / "artifacts" / "publication" / "repository_submission_worksheets.json"
WORKSHEET_ROOT: Final = ROOT / "artifacts" / "publication" / "repository_metadata"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _finish(document: dict[str, Any]) -> dict[str, Any]:
    document["content_hash"] = _content_hash(document)
    return document


def _zenodo_paper(record: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    return _finish(
        {
            "schema": "canli.alphac-zenodo-paper-worksheet.v1",
            "platform": "ZENODO",
            "object_identity": "PAPER_PREPRINT",
            "registry_key": record["registry_key"],
            "state": "BLOCKED_LOCAL_WORKSHEET_NOT_A_DEPOSIT",
            "metadata": {
                "title": record["title"],
                "resource_type_ui_selection": "Publication / Preprint",
                "publication_date": None,
                "local_preparation_date_not_publication_date": paper.get("date"),
                "creators": [
                    {
                        "name": "Arhan Canli",
                        "affiliation": record["affiliation"],
                        "orcid": None,
                    }
                ],
                "description": record["abstract"],
                "version": record["version"],
                "language": "eng",
                "keywords": record["keywords"],
                "license_selection": None,
                "visibility_selection": None,
                "related_identifiers": [],
                "doi": None,
                "doi_reserved": False,
            },
            "files": [record["source_objects"]["paper_pdf"]],
            "blockers": sorted(
                {
                    *record["blockers"],
                    "ZENODO_LICENSE_OWNER_CONFIRMATION_REQUIRED",
                    "ZENODO_PUBLICATION_DATE_REQUIRED_AT_REAL_PUBLICATION",
                    "ZENODO_VISIBILITY_OWNER_CONFIRMATION_REQUIRED",
                    "ZENODO_FINAL_PREVIEW_AND_ACCOUNT_ACTION_REQUIRED",
                }
            ),
            "submission_claimed": False,
            "doi_claimed": False,
            "claim_boundary": (
                "This is a local metadata worksheet. It is not a Zenodo draft, DOI reservation, "
                "deposit, publication, moderation outcome, citation, or peer review."
            ),
        }
    )


def _zenodo_bundle(record: dict[str, Any], archive: dict[str, Any] | None) -> dict[str, Any]:
    blockers = [
        *record["blockers"],
        "ZENODO_BUNDLE_RESOURCE_TYPE_FINAL_SELECTION_REQUIRED",
        "ZENODO_MIXED_LICENSE_OWNER_CONFIRMATION_REQUIRED",
        "ZENODO_PUBLICATION_DATE_REQUIRED_AT_REAL_PUBLICATION",
        "ZENODO_VISIBILITY_OWNER_CONFIRMATION_REQUIRED",
        "ZENODO_FINAL_PREVIEW_AND_ACCOUNT_ACTION_REQUIRED",
        "PAPER_AND_BUNDLE_DOI_RELATION_MUST_BE_SET_AFTER_REAL_IDENTIFIERS_EXIST",
    ]
    files: list[dict[str, Any]] = []
    if archive is None:
        blockers.append("DETERMINISTIC_DEPOSIT_ARCHIVE_NOT_YET_PACKAGED")
    else:
        files.append(
            {
                "path": archive["archive"],
                "sha256": archive["sha256"],
                "bytes": archive["bytes"],
                "archive_integrity_passed": archive["passed"],
            }
        )
    return _finish(
        {
            "schema": "canli.alphac-zenodo-reproducibility-worksheet.v1",
            "platform": "ZENODO",
            "object_identity": "REPRODUCIBILITY_BUNDLE",
            "registry_key": record["registry_key"],
            "state": "BLOCKED_LOCAL_WORKSHEET_NOT_A_DEPOSIT",
            "metadata": {
                "title": f"{record['title']}: Reproducibility Preparation Bundle",
                "resource_type_ui_selection": None,
                "resource_type_decision": (
                    "Select the dominant type only after final code/data composition review; "
                    "Zenodo permits splitting significant mixed types."
                ),
                "publication_date": None,
                "creators": [
                    {
                        "name": "Arhan Canli",
                        "affiliation": record["affiliation"],
                        "orcid": None,
                    }
                ],
                "description": (
                    "Checksum-bound preparation bundle for the associated working paper. "
                    "Known blockers and evidence limitations remain inside the archive."
                ),
                "version": record["version"],
                "language": "eng",
                "keywords": [*record["keywords"], "reproducibility bundle"],
                "license_selections": [],
                "visibility_selection": None,
                "related_identifiers": [],
                "doi": None,
                "doi_reserved": False,
            },
            "files": files,
            "blockers": sorted(set(blockers)),
            "submission_claimed": False,
            "doi_claimed": False,
            "claim_boundary": (
                "This is a local metadata worksheet. Archive integrity does not establish result "
                "reproduction, redistribution rights, independent replication, or a Zenodo record."
            ),
        }
    )


def _ssrn(record: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    return _finish(
        {
            "schema": "canli.alphac-ssrn-submission-worksheet.v1",
            "platform": "SSRN",
            "object_identity": "FINANCE_WORKING_PAPER",
            "registry_key": record["registry_key"],
            "state": "BLOCKED_LOCAL_WORKSHEET_NOT_A_SUBMISSION",
            "metadata": {
                "title_english": record["title"],
                "date_written": paper.get("date"),
                "abstract_english": record["abstract"],
                "authors": [
                    {
                        "name": "Arhan Canli",
                        "affiliation": record["affiliation"],
                        "email": None,
                    }
                ],
                "keywords": record["keywords"],
                "copyright_holder": None,
                "copyright_permission_confirmed": False,
                "classifications": [],
                "external_identifier": None,
            },
            "files": [record["source_objects"]["paper_pdf"]],
            "blockers": sorted(
                {
                    *record["blockers"],
                    "SSRN_OWNER_ACCOUNT_ACTION_REQUIRED",
                    "SSRN_AUTHOR_EMAIL_REQUIRED",
                    "SSRN_COPYRIGHT_HOLDER_AND_PERMISSION_CONFIRMATION_REQUIRED",
                    "SSRN_CLASSIFICATION_SELECTION_REQUIRED",
                    "SSRN_FINAL_PDF_AND_METADATA_PREVIEW_REQUIRED",
                }
            ),
            "submission_claimed": False,
            "external_identifier_claimed": False,
            "claim_boundary": (
                "This is a local checklist worksheet. It is not an SSRN submission, screening "
                "outcome, acceptance, public working-paper record, citation, or peer review."
            ),
        }
    )


def build() -> dict[str, Any]:
    plan = json.loads(PLAN.read_text())
    requirements = json.loads(REQUIREMENTS.read_text())
    archives = json.loads(ARCHIVES.read_text())
    data_rights = json.loads(DATA_RIGHTS.read_text())
    clean_reproduction = json.loads(CLEAN_REPRODUCTION.read_text())
    archive_by_key = {row["registry_key"]: row for row in archives["records"]}
    rights_by_key = {row["registry_key"]: row for row in data_rights["records"]}
    replay_by_key = {row["registry_key"]: row for row in clean_reproduction["records"]}
    failures: list[str] = []
    records: list[dict[str, Any]] = []

    if plan.get("status") != "PREPARATION_ONLY_NO_EXTERNAL_SUBMISSIONS_CLAIMED":
        failures.append("SUBMISSION_PLAN_STATUS_OVERSTATED")
    if requirements.get("observed_on") != "2026-08-24":
        failures.append("REPOSITORY_REQUIREMENTS_OBSERVATION_DATE_UNEXPECTED")
    if (
        requirements["repositories"]["OSF_PREPRINTS"]["project_policy"].get(
            "default_route_permitted"
        )
        is not False
    ):
        failures.append("OSF_DEFAULT_ROUTE_MUST_REMAIN_EXCLUDED")
    if (
        requirements["repositories"]["SSRN"]["project_policy"].get(
            "current_sleeve_records_targeted"
        )
        != 0
    ):
        failures.append("SSRN_CURRENT_SLEEVE_ROUTE_MUST_REMAIN_EXCLUDED")

    for record in plan["records"]:
        rights = rights_by_key.get(record["registry_key"])
        replay = replay_by_key.get(record["registry_key"])
        if rights is None:
            failures.append(f"{record['registry_key']}:DATA_RIGHTS_RECORD_MISSING")
        elif (
            rights.get("source_mapping_complete") is not True
            or rights.get("raw_third_party_rows_released") is not False
            or rights.get("data_manifest_license_review_complete") is not False
        ):
            failures.append(f"{record['registry_key']}:DATA_RIGHTS_STATE_UNEXPECTED")
        if replay is None:
            failures.append(f"{record['registry_key']}:REPRODUCTION_AUDIT_RECORD_MISSING")
        elif (
            replay.get("archive_standalone_reproduction_executable") is not False
            or replay.get("manifest_full_clean_workspace_reproduction_claimed") is not False
            or replay.get("independent_human_reproduction_completed") is not False
        ):
            failures.append(f"{record['registry_key']}:REPRODUCTION_STATE_UNEXPECTED")
        paper_path = ROOT / record["source_objects"]["paper_json"]["path"]
        paper = json.loads(paper_path.read_text())
        archive = archive_by_key.get(record["registry_key"])
        if archive is not None:
            archive_path = ROOT / archive["archive"]
            if not archive_path.is_file() or _sha256(archive_path) != archive["sha256"]:
                failures.append(f"{record['registry_key']}:ARCHIVE_BINDING_INVALID")
        worksheets: dict[str, dict[str, Any]] = {
            "zenodo_paper": _zenodo_paper(record, paper),
            "zenodo_reproducibility_bundle": _zenodo_bundle(record, archive),
        }
        if any(target["platform"] == "SSRN" for target in record["planned_targets"]):
            worksheets["ssrn_working_paper"] = _ssrn(record, paper)
        records.append(
            {
                "registry_key": record["registry_key"],
                "bundle_slug": record["bundle_slug"],
                "wave": record["wave"],
                "worksheets": worksheets,
            }
        )

    all_worksheets = [
        worksheet for record in records for worksheet in record["worksheets"].values()
    ]
    if len(all_worksheets) != 32:
        failures.append("PLANNED_WORKSHEET_COUNT_NOT_32")
    if any(worksheet.get("submission_claimed") for worksheet in all_worksheets):
        failures.append("UNVERIFIED_SUBMISSION_CLAIM_PRESENT")
    if any(
        worksheet.get("doi_claimed") or worksheet.get("external_identifier_claimed")
        for worksheet in all_worksheets
    ):
        failures.append("UNVERIFIED_IDENTIFIER_CLAIM_PRESENT")

    document: dict[str, Any] = {
        "schema": "canli.alphac-repository-submission-worksheets.v1",
        "generated_on": "2026-08-24",
        "author": "Arhan Canli",
        "status": (
            "PASS_LOCAL_WORKSHEETS_BLOCKED_NO_SUBMISSION_CLAIMED" if not failures else "FAIL"
        ),
        "passes": not failures,
        "counts": {
            "sleeve_papers": len(records),
            "zenodo_paper_worksheets": sum(
                "zenodo_paper" in record["worksheets"] for record in records
            ),
            "zenodo_bundle_worksheets": sum(
                "zenodo_reproducibility_bundle" in record["worksheets"] for record in records
            ),
            "ssrn_worksheets": sum(
                "ssrn_working_paper" in record["worksheets"] for record in records
            ),
            "planned_external_records": len(all_worksheets),
            "submission_ready": 0,
            "external_identifiers_claimed": 0,
        },
        "venue_decisions": {
            "ZENODO": "PLANNED_AFTER_EVIDENCE_AND_OWNER_METADATA_BLOCKERS_CLOSE",
            "SSRN": requirements["repositories"]["SSRN"]["route"],
            "ARXIV": "NO_CURRENT_SLEEVE_RECORDS_SEPARATE_METHODOLOGY_FLAGSHIP_NOT_AUTHORED",
            "OSF_PREPRINTS": requirements["repositories"]["OSF_PREPRINTS"]["route"],
        },
        "human_authorship_boundary": {
            "author_of_record": "Arhan Canli",
            "ai_assistance_disclosed_in_repository_readme": True,
            "paper_specific_human_authorship_audit_for_osf_completed": False,
            "claim": (
                "Authorship credit follows the existing paper contribution statements. This "
                "worksheet does not independently verify conception or writing percentages."
            ),
        },
        "records": records,
        "failures": failures,
        "source_bindings": {
            "submission_plan": {"path": str(PLAN.relative_to(ROOT)), "sha256": _sha256(PLAN)},
            "repository_requirements": {
                "path": str(REQUIREMENTS.relative_to(ROOT)),
                "sha256": _sha256(REQUIREMENTS),
                "observed_on": requirements["observed_on"],
            },
            "all_sleeve_review_archives": {
                "path": str(ARCHIVES.relative_to(ROOT)),
                "sha256": _sha256(ARCHIVES),
                "content_hash": archives["content_hash"],
            },
            "all_sleeve_data_rights_audit": {
                "path": str(DATA_RIGHTS.relative_to(ROOT)),
                "sha256": _sha256(DATA_RIGHTS),
                "content_hash": data_rights["content_hash"],
                "source_mappings_complete": data_rights["counts"][
                    "source_mapping_complete"
                ],
                "data_license_reviews_complete": data_rights["counts"][
                    "data_license_reviews_complete"
                ],
            },
            "clean_workspace_reproduction_audit": {
                "path": str(CLEAN_REPRODUCTION.relative_to(ROOT)),
                "sha256": _sha256(CLEAN_REPRODUCTION),
                "content_hash": clean_reproduction["content_hash"],
                "full_clean_workspace_reproductions_completed": clean_reproduction[
                    "counts"
                ]["full_clean_workspace_reproductions_completed"],
                "independent_human_reproductions_completed": clean_reproduction[
                    "counts"
                ]["independent_human_reproductions_completed"],
            },
        },
        "claim_boundary": (
            "These are local, blocked metadata worksheets. No external account was accessed; no "
            "draft, DOI, submission, screening, acceptance, publication, peer review, citation, "
            "or independent replication is claimed."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    WORKSHEET_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    for record in document["records"]:
        out = WORKSHEET_ROOT / record["bundle_slug"]
        out.mkdir(parents=True, exist_ok=True)
        stale_ssrn = out / "ssrn_working_paper.json"
        if "ssrn_working_paper" not in record["worksheets"] and stale_ssrn.exists():
            stale_ssrn.unlink()
        for name, worksheet in record["worksheets"].items():
            (out / f"{name}.json").write_text(
                json.dumps(worksheet, indent=2, sort_keys=True) + "\n"
            )
    print(f"{document['status']}: {OUTPUT}")
    print(f"content_hash: {document['content_hash']}")
    if document["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
