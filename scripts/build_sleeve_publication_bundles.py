#!/usr/bin/env python3
"""Build deterministic, fail-closed preparation bundles for every sleeve lineage.

These are inventory-complete source bundles, not submission-ready research releases. They make
the missing result, data, bibliography, replay, and independent-replication work explicit
without manufacturing evidence. AlphaVintage has a richer dedicated builder and is skipped here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
EVIDENCE_CATALOG: Final = ROOT / "config/sleeve_publication_evidence.json"
TRIAL_ACCOUNTING: Final = ROOT / "config/trial_accounting.json"
TRIAL_PACKET_MANIFEST: Final = ROOT / "artifacts/research/trial_packet_manifest.json"
INTERNAL_REPLAY_RECEIPT: Final = (
    ROOT / "artifacts/audit/sleeve_publication_replay_verification.json"
)
ISOLATED_REPLAY_RECEIPT: Final = (
    ROOT / "artifacts/audit/sleeve_publication_isolated_replay_verification.json"
)
VERSION: Final = "0.1.0"
RELEASE_DATE: Final = "2026-08-23"
DEDICATED_BUILDERS: Final = {"alphavintage_macro_surprise"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _abstract(markdown: str) -> str:
    lines = markdown.splitlines()
    start = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if line.strip().lower() in {"## abstract", "## finding and boundary"}
        ),
        None,
    )
    if start is None:
        return "Sleeve trial-lineage record with an explicit evidence and publication boundary."
    paragraphs: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped and not stripped.startswith("**"):
            paragraphs.append(stripped)
    text = " ".join(paragraphs)
    if not text:
        return "Sleeve trial-lineage record with an explicit evidence boundary."
    if len(text) <= 2000:
        return text

    # Repository metadata must never end in a sliced word or unfinished claim. Prefer the
    # longest complete sentence within the field limit; retain a word-safe ellipsis only for
    # pathological source text that contains no sentence boundary in the first 2,000 characters.
    bounded = text[:2000]
    sentence_ends = [match.end() for match in re.finditer(r"[.!?](?=\s|$)", bounded)]
    if sentence_ends:
        return bounded[: sentence_ends[-1]].strip()
    return bounded[:1999].rsplit(" ", maxsplit=1)[0].rstrip() + "…"


def _citation(item: dict[str, Any]) -> str:
    title = str(item["title"]).replace("'", "''")
    slug = item["bundle_slug"]
    return f"""cff-version: 1.2.0
message: "If you use this preparation bundle, please cite Arhan Canli."
title: '{title}'
type: article
version: "{VERSION}"
date-released: "{RELEASE_DATE}"
authors:
  - family-names: "Canli"
    given-names: "Arhan"
repository-code: "https://github.com/arhancanli/alphac"
url: "https://canlicapital.com/research/{slug}.html"
abstract: >-
  Incomplete working-paper preparation bundle. Not peer reviewed; no external submission,
  DOI, independent replication, or investment-performance claim.
"""


def _spdx(item: dict[str, Any]) -> dict[str, Any]:
    slug = item["bundle_slug"]
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{slug}-publication-preparation-v{VERSION}",
        "documentNamespace": f"https://canlicapital.com/spdx/{slug}-v{VERSION}",
        "creationInfo": {
            "created": f"{RELEASE_DATE}T00:00:00Z",
            "creators": ["Person: Arhan Canli", "Tool: ALPHAC sleeve bundle builder"],
        },
        "packages": [
            {
                "name": f"{slug}-publication-preparation",
                "SPDXID": "SPDXRef-Package",
                "versionInfo": VERSION,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "MIT",
                "copyrightText": "Copyright 2026 Arhan Canli",
            }
        ],
    }


def _ro_crate(out: Path, item: dict[str, Any]) -> dict[str, Any]:
    files = sorted(
        str(path.relative_to(out))
        for path in out.rglob("*")
        if path.is_file() and path.name != "ro-crate-metadata.json"
    )
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": item["title"],
            "version": VERSION,
            "datePublished": RELEASE_DATE,
            "author": {"@id": "#arhan-canli"},
            "hasPart": [{"@id": name} for name in files],
        },
        {"@id": "#arhan-canli", "@type": "Person", "name": "Arhan Canli"},
    ]
    graph.extend({"@id": name, "@type": "File", "sha256": _sha256(out / name)} for name in files)
    return {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}


def build_one(item: dict[str, Any], evidence: dict[str, Any], out_root: Path | None = None) -> Path:
    source = ROOT / item["source_paper"]
    if not source.is_file():
        raise FileNotFoundError(source)
    text = source.read_text()
    if "Arhan Canli" not in text or "not peer reviewed" not in text.lower():
        raise ValueError(f"source paper lacks authorship or review boundary: {source}")

    publication_root = out_root if out_root is not None else ROOT / "publication"
    out = publication_root / str(item["bundle_slug"]) / f"v{VERSION}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    evidence_dir = out / "evidence"
    evidence_dir.mkdir()
    shutil.copyfile(source, out / "paper.md")
    shutil.copyfile(ROOT / "LICENSE", out / "LICENSE")
    if not INTERNAL_REPLAY_RECEIPT.is_file():
        raise FileNotFoundError(INTERNAL_REPLAY_RECEIPT)
    if not ISOLATED_REPLAY_RECEIPT.is_file():
        raise FileNotFoundError(ISOLATED_REPLAY_RECEIPT)
    shutil.copyfile(INTERNAL_REPLAY_RECEIPT, out / "internal_replay_receipt.json")
    shutil.copyfile(ISOLATED_REPLAY_RECEIPT, out / "isolated_replay_receipt.json")
    replay_receipt = json.loads(INTERNAL_REPLAY_RECEIPT.read_text())
    isolated_replay_receipt = json.loads(ISOLATED_REPLAY_RECEIPT.read_text())

    _write_json(
        out / "paper.json",
        {
            "schema": "canli.alphac-sleeve-paper.v1",
            "registry_key": item["key"],
            "title": item["title"],
            "version": VERSION,
            "date": RELEASE_DATE,
            "language": "en",
            "type": "WORKING_PAPER_PREPRINT_NOT_PEER_REVIEWED",
            "authors": [
                {
                    "full_name": "Arhan Canli",
                    "affiliation": "Canli Capital / AlphaC Algorithms",
                    "roles": [
                        "CONCEPTUALIZATION",
                        "METHODOLOGY",
                        "SOFTWARE",
                        "VALIDATION",
                        "INVESTIGATION",
                        "WRITING",
                        "PROJECT_ADMINISTRATION",
                    ],
                }
            ],
            "abstract": _abstract(text),
            "capital_kind": item["capital_kind"],
            "external_identifiers": [],
            "peer_reviewed": False,
            "result_release_complete": True,
            "claim_boundary": (
                "This is an incomplete preparation bundle. It proves no external submission, "
                "DOI, peer review, independent replication, funded performance, or future return."
            ),
        },
    )
    released_results: list[dict[str, Any]] = []
    for result in evidence["result_objects"]:
        source_result = ROOT / result["source"]
        if not source_result.is_file():
            raise FileNotFoundError(source_result)
        release_path = evidence_dir / result["release_name"]
        shutil.copyfile(source_result, release_path)
        released_results.append(
            {
                "source_path": result["source"],
                "bundle_path": str(release_path.relative_to(out)),
                "role": result["role"],
                "sha256": _sha256(source_result),
                "byte_identical_to_source": True,
            }
        )

    _write_json(
        out / "data_manifest.json",
        {
            "schema": "canli.alphac-publication-data-manifest.v1",
            "registry_key": item["key"],
            "source_paper": {
                "path": item["source_paper"],
                "sha256": _sha256(source),
            },
            "released_result_objects": released_results,
            "released_data_objects": [],
            "license_review_complete": False,
            "status": "RESULT_OBJECTS_RELEASED_RAW_INPUT_INVENTORY_INCOMPLETE",
        },
    )

    trial_manifest = json.loads(TRIAL_PACKET_MANIFEST.read_text())
    family_key = evidence["trial_family_key"]
    identities = [
        identity
        for identity in trial_manifest["identities"]
        if identity["research_family_key"] == family_key
    ]
    if not identities:
        raise ValueError(f"no recorded identities for {item['key']} / {family_key}")
    for result in released_results:
        if result["bundle_path"].endswith("family_result.json"):
            family_result = json.loads((out / result["bundle_path"]).read_text())
            declared_count = family_result["summary"]["distinct_hypothesis_identities"]
            if declared_count != len(identities):
                raise ValueError(
                    f"family result/union count mismatch for {item['key']}: "
                    f"{declared_count} != {len(identities)}"
                )
    _write_json(
        out / "trial_accounting.json",
        {
            "schema": "canli.alphac-publication-trial-accounting-binding.v2",
            "registry_key": item["key"],
            "global_ledger": {
                "path": str(TRIAL_ACCOUNTING.relative_to(ROOT)),
                "sha256": _sha256(TRIAL_ACCOUNTING),
            },
            "trial_packet_manifest": {
                "path": str(TRIAL_PACKET_MANIFEST.relative_to(ROOT)),
                "sha256": _sha256(TRIAL_PACKET_MANIFEST),
                "content_hash": trial_manifest["content_hash"],
            },
            "research_family_key": family_key,
            "distinct_recorded_hypothesis_identities": len(identities),
            "identities": identities,
            "complete_recorded_union_extracted": True,
            "every_identity_packet_complete": all(
                identity["identity_packet_status"] == "COMPLETE" for identity in identities
            ),
            "status": "COMPLETE_RECORDED_UNION_EXTRACTED_IDENTITY_PACKETS_MAY_BE_INCOMPLETE",
        },
    )

    code_bindings: dict[str, str] = {}
    for relative in evidence["code_bindings"]:
        code_path = ROOT / relative
        if not code_path.is_file():
            raise FileNotFoundError(code_path)
        code_bindings[relative] = _sha256(code_path)
    _write_json(
        out / "reproduction.json",
        {
            "schema": "canli.alphac-publication-reproduction.v2",
            "registry_key": item["key"],
            "environment_bindings": {
                "pyproject.toml": _sha256(ROOT / "pyproject.toml"),
                "uv.lock": _sha256(ROOT / "uv.lock"),
            },
            "bundle_integrity_command": "sha256sum -c SHA256SUMS",
            "code_bindings": code_bindings,
            "result_reproduction_commands": evidence["reproduction_commands"],
            "expected_result_hashes": {
                result["source_path"]: result["sha256"] for result in released_results
            },
            "result_reproduction_mapping_complete": True,
            "internal_audit_replay": {
                "bundle_path": "internal_replay_receipt.json",
                "sha256": _sha256(INTERNAL_REPLAY_RECEIPT),
                "content_hash": replay_receipt["content_hash"],
                "sleeve_status": replay_receipt["sleeve_status"][item["key"]],
                "audit_command_executed": (item["key"] not in replay_receipt["sleeves_deferred"]),
            },
            "isolated_frozen_dependency_replay": {
                "bundle_path": "isolated_replay_receipt.json",
                "sha256": _sha256(ISOLATED_REPLAY_RECEIPT),
                "content_hash": isolated_replay_receipt["content_hash"],
                "dependency_environment": isolated_replay_receipt["dependency_environment"],
                "sleeve_status": isolated_replay_receipt["sleeve_status"][item["key"]],
                "audit_command_executed": (
                    item["key"] not in isolated_replay_receipt["sleeves_deferred"]
                ),
                "portable_clean_workspace_replay_completed": False,
                "raw_input_portability_established": False,
            },
            "clean_environment_reproduction_completed": False,
            "independent_human_reproduction_completed": False,
            "status": "MAPPED_NOT_CLEAN_ENVIRONMENT_REPLAYED",
        },
    )
    _write_json(
        out / "codemeta.json",
        {
            "@context": "https://doi.org/10.5063/schema/codemeta-2.0",
            "@type": "SoftwareSourceCode",
            "name": f"ALPHAC {item['bundle_slug']} publication preparation",
            "version": VERSION,
            "datePublished": RELEASE_DATE,
            "author": {"@type": "Person", "givenName": "Arhan", "familyName": "Canli"},
            "codeRepository": "https://github.com/arhancanli/alphac",
            "license": "https://spdx.org/licenses/MIT.html",
            "programmingLanguage": "Python 3.12",
            "applicationCategory": "Quantitative research reproducibility",
        },
    )
    _write_json(out / "sbom.spdx.json", _spdx(item))
    (out / "CITATION.cff").write_text(_citation(item))
    corrections = evidence.get("bundle_corrections", [])
    corrections_text = f"# {item['title']} — corrections ledger\n\n"
    if corrections:
        for correction in corrections:
            corrections_text += (
                f"## {correction['date']} — {correction['status']}\n\n"
                f"{correction['summary']}\n\n"
                "Evidence:\n\n" + "".join(f"- `{path}`\n" for path in correction["evidence"]) + "\n"
            )
    else:
        corrections_text += (
            "No bundle-version correction has been recorded. This empty ledger is not a claim "
            "that the underlying research lineage contains no corrections; those remain in "
            "`paper.md`.\n"
        )
    (out / "CORRECTIONS.md").write_text(corrections_text)
    (out / "README.md").write_text(
        f"# {item['title']} — preparation bundle v{VERSION}\n\n"
        "**Author:** Arhan Canli  \n"
        "**State:** BUNDLE_INCOMPLETE  \n"
        "**Review:** not peer reviewed  \n\n"
        "This checksum-bound source bundle establishes citation identity, authorship, trial-ledger "
        "binding, a complete recorded-union extract, exact released result objects, environment "
        "binding, and an explicit gap inventory. It is not submission-ready. Raw-input licensing "
        "and inventory, clean replay, and independent human replication remain unresolved. "
        "Normalized bibliography and archival PDF/HTML/LaTeX assets, with their separate "
        "inspection receipt, are added by the publication-rendering stages.\n"
    )
    manifest = {
        "schema": "canli.alphac-publication-bundle-manifest.v2",
        "registry_key": item["key"],
        "sleeve": item["bundle_slug"],
        "version": VERSION,
        "status": "BUNDLE_INCOMPLETE",
        "author": "Arhan Canli",
        "remaining_blockers": item["submission_blockers"],
        "external_submission_claimed": False,
        "doi_claimed": False,
        "peer_review_claimed": False,
        "independent_replication_claimed": False,
    }
    _write_json(out / "bundle_manifest.json", manifest)
    _write_json(out / "ro-crate-metadata.json", _ro_crate(out, item))
    checksum_files = sorted(
        path for path in out.rglob("*") if path.is_file() and path.name != "SHA256SUMS"
    )
    (out / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(out)}\n" for path in checksum_files)
    )
    return out


def build_all(out_root: Path | None = None) -> list[Path]:
    registry = json.loads(REGISTRY.read_text())
    catalog = json.loads(EVIDENCE_CATALOG.read_text())["sleeves"]
    expected = {
        item["key"] for item in registry["sleeves"] if item["key"] not in DEDICATED_BUILDERS
    }
    if set(catalog) != expected:
        raise ValueError("evidence catalog does not exactly cover every generic sleeve bundle")
    return [
        build_one(item, catalog[item["key"]], out_root)
        for item in registry["sleeves"]
        if item["key"] not in DEDICATED_BUILDERS
    ]


def main() -> int:
    outputs = build_all()
    print(f"built {len(outputs)} deterministic incomplete sleeve bundles")
    for output in outputs:
        print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
