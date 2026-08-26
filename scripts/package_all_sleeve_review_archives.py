#!/usr/bin/env python3
"""Build deterministic raw-row-free review archives for all sleeve papers."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config" / "external_publication_registry.json"
RIGHTS_AUDIT: Final = ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
OUTPUT_DIR: Final = ROOT / "artifacts" / "publication" / "all_sleeve_review_archives"
RECEIPT: Final = ROOT / "artifacts" / "publication" / "all_sleeve_review_archives.json"
FIRST_WAVE: Final = frozenset(
    {
        "alphavintage_macro_surprise",
        "alphaforge_crypto_carry",
        "alphamax_equity_momentum",
        "alphatrend_managed_futures",
        "crypto_multifactor_engine",
    }
)
RAW_INPUT_EXTENSIONS: Final = {
    ".arrow",
    ".csv",
    ".db",
    ".duckdb",
    ".feather",
    ".jsonl",
    ".parquet",
    ".sqlite",
    ".tsv",
    ".xls",
    ".xlsx",
    ".zip",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _archive_bytes(bundle_dir: Path, archive_root: str) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(archive_root) / path.relative_to(bundle_dir)
            info = tarfile.TarInfo(relative.as_posix())
            info.size = path.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as zipper:
        zipper.write(raw.getvalue())
    return compressed.getvalue()


def _verify_checksums(extracted: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    verified = 0
    for line in (extracted / "SHA256SUMS").read_text().splitlines():
        if not line.strip():
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError:
            failures.append(f"MALFORMED_CHECKSUM_LINE:{line}")
            continue
        path = extracted / relative
        if not path.is_file():
            failures.append(f"MISSING:{relative}")
        elif _sha256(path) != expected:
            failures.append(f"HASH_MISMATCH:{relative}")
        else:
            verified += 1
    return verified, failures


def _verify_archive(archive_path: Path, archive_root: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="alphac-all-sleeve-review-") as value:
        workspace = Path(value)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            unsafe = [
                member.name
                for member in members
                if member.name.startswith("/")
                or ".." in Path(member.name).parts
                or not member.isfile()
            ]
            raw_members = [
                member.name
                for member in members
                if Path(member.name).suffix.lower() in RAW_INPUT_EXTENSIONS
            ]
            if unsafe:
                raise RuntimeError(f"Unsafe or non-file archive members: {unsafe}")
            archive.extractall(workspace, filter="data")
        extracted = workspace / archive_root
        verified, checksum_failures = _verify_checksums(extracted)
        return {
            "workspace_outside_repository": not workspace.is_relative_to(ROOT),
            "archive_member_count": len(members),
            "unsafe_or_non_file_archive_members": unsafe,
            "raw_input_archive_members": raw_members,
            "checksum_files_verified": verified,
            "checksum_failures": checksum_failures,
            "paper_pdf_present": (extracted / "paper.pdf").is_file(),
            "reproduction_manifest_present": (extracted / "reproduction.json").is_file(),
            "data_manifest_present": (extracted / "data_manifest.json").is_file(),
        }


def build() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text())
    rights = json.loads(RIGHTS_AUDIT.read_text())
    expected_rights_status = (
        "PASS_RAW_ROW_EXCLUSION_PUBLIC_TERMS_REVIEW_COMPLETE_CLEARANCE_INCOMPLETE"
    )
    if rights.get("status") != expected_rights_status:
        raise RuntimeError("All-sleeve raw-row exclusion audit must pass")
    if rights["counts"]["raw_row_free_bundles"] != len(registry["sleeves"]):
        raise RuntimeError("Every planned sleeve must be audited raw-row-free")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for paper in registry["sleeves"]:
        manifest = ROOT / paper["bundle_manifest"]
        bundle_dir = manifest.parent
        metadata = json.loads((bundle_dir / "paper.json").read_text())
        archive_root = f"{paper['bundle_slug']}-v{metadata['version']}"
        archive_name = f"{archive_root}-external-review-preparation.tar.gz"
        archive_path = OUTPUT_DIR / archive_name
        payload = _archive_bytes(bundle_dir, archive_root)
        archive_path.write_bytes(payload)
        deterministic = payload == _archive_bytes(bundle_dir, archive_root)
        verification = _verify_archive(archive_path, archive_root)
        passed = (
            deterministic
            and verification["workspace_outside_repository"]
            and not verification["unsafe_or_non_file_archive_members"]
            and not verification["raw_input_archive_members"]
            and not verification["checksum_failures"]
            and verification["paper_pdf_present"]
            and verification["reproduction_manifest_present"]
            and verification["data_manifest_present"]
        )
        if not passed:
            failures.append(f"{paper['registry_key']}:ARCHIVE_VERIFICATION_FAILED")
        records.append(
            {
                "registry_key": paper["key"],
                "wave": 1 if paper["key"] in FIRST_WAVE else 2,
                "archive": str(archive_path.relative_to(ROOT)),
                "archive_root": archive_root,
                "sha256": _sha256(archive_path),
                "bytes": archive_path.stat().st_size,
                "deterministic_second_build_identical": deterministic,
                "verification": verification,
                "passed": passed,
                "external_publication_url": None,
            }
        )

    if len(records) != 16:
        failures.append("EXPECTED_EXACTLY_16_ARCHIVES")
    document: dict[str, Any] = {
        "schema": "canli.alphac-all-sleeve-review-archives.v1",
        "author": "Arhan Canli",
        "status": (
            "PASS_ARCHIVE_INTEGRITY_ONLY_RIGHTS_AND_REPLAY_BLOCKED" if not failures else "FAIL"
        ),
        "counts": {
            "planned_sleeves": len(registry["sleeves"]),
            "archives_built": len(records),
            "archives_passed": sum(record["passed"] for record in records),
            "raw_input_members": sum(
                len(record["verification"]["raw_input_archive_members"]) for record in records
            ),
        },
        "records": records,
        "failures": failures,
        "result_generation_replayed": False,
        "clean_environment_replay_completed": False,
        "independent_replication": False,
        "redistribution_rights_cleared_for_all_sleeves": False,
        "submission_claimed": False,
        "source_bindings": {
            "publication_registry": {
                "path": str(REGISTRY.relative_to(ROOT)),
                "sha256": _sha256(REGISTRY),
            },
            "all_sleeve_data_rights_audit": {
                "path": str(RIGHTS_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(RIGHTS_AUDIT),
                "content_hash": rights["content_hash"],
            },
        },
        "claim_boundary": (
            "This proves deterministic archive construction, safe extraction, exclusion of the "
            "declared raw-input file types, and internal checksum integrity in a temporary "
            "workspace outside the repository. It does not recompute results, establish complete "
            "input portability or redistribution rights, constitute independent replication, or "
            "claim an external deposit or publication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    document = build()
    RECEIPT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {RECEIPT}")
    print(f"content_hash: {document['content_hash']}")
    if document["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
