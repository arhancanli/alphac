#!/usr/bin/env python3
"""Create deterministic, raw-row-free Wave 1 archive candidates and verify extraction."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
PLAN: Final = ROOT / "artifacts" / "publication" / "external_submission_plan.json"
RIGHTS_AUDIT: Final = ROOT / "artifacts" / "publication" / "wave1_data_rights_audit.json"
OUTPUT_DIR: Final = ROOT / "artifacts" / "publication" / "wave1_release_candidates"
RECEIPT: Final = ROOT / "artifacts" / "publication" / "wave1_release_candidates.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _archive_bytes(bundle_dir: Path) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(bundle_dir.name) / path.relative_to(bundle_dir)
            info = tarfile.TarInfo(str(relative))
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


def _verify_archive(archive_path: Path, bundle_name: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="alphac-wave1-") as value:
        workspace = Path(value)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            unsafe = [
                member.name
                for member in members
                if member.name.startswith("/") or ".." in Path(member.name).parts
            ]
            if unsafe:
                raise RuntimeError(f"Unsafe archive members: {unsafe}")
            archive.extractall(workspace, filter="data")
        extracted = workspace / bundle_name
        process = subprocess.run(
            ["sha256sum", "-c", "SHA256SUMS"],
            cwd=extracted,
            check=False,
            capture_output=True,
            text=True,
        )
        return {
            "workspace_outside_repository": not workspace.is_relative_to(ROOT),
            "archive_member_count": len(members),
            "unsafe_archive_members": unsafe,
            "checksum_exit_code": process.returncode,
            "checksum_files_verified": process.stdout.count(": OK"),
            "checksum_stderr": process.stderr.strip(),
            "paper_pdf_present": (extracted / "paper.pdf").is_file(),
            "reproduction_manifest_present": (extracted / "reproduction.json").is_file(),
        }


def build() -> dict[str, Any]:
    plan = json.loads(PLAN.read_text())
    rights = json.loads(RIGHTS_AUDIT.read_text())
    if rights.get("status") != "PASS_CONSERVATIVE_EXCLUSION":
        raise RuntimeError("Wave 1 data-rights exclusion audit must pass")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for paper in (record for record in plan["records"] if record["wave"] == 1):
        manifest = ROOT / paper["source_objects"]["bundle_manifest"]["path"]
        bundle_dir = manifest.parent
        archive_name = f"{paper['bundle_slug']}-v{paper['version']}-preparation-bundle.tar.gz"
        archive_path = OUTPUT_DIR / archive_name
        payload = _archive_bytes(bundle_dir)
        archive_path.write_bytes(payload)
        # A second in-memory build proves deterministic construction in this environment.
        deterministic = payload == _archive_bytes(bundle_dir)
        verification = _verify_archive(archive_path, bundle_dir.name)
        passed = (
            deterministic
            and verification["workspace_outside_repository"]
            and verification["checksum_exit_code"] == 0
            and not verification["unsafe_archive_members"]
            and verification["paper_pdf_present"]
            and verification["reproduction_manifest_present"]
        )
        if not passed:
            failures.append(f"{paper['registry_key']}:ARCHIVE_VERIFICATION_FAILED")
        records.append(
            {
                "registry_key": paper["registry_key"],
                "archive": str(archive_path.relative_to(ROOT)),
                "public_path": f"/release-candidates/{archive_name}",
                "sha256": _sha256(archive_path),
                "bytes": archive_path.stat().st_size,
                "deterministic_second_build_identical": deterministic,
                "verification": verification,
                "passed": passed,
            }
        )

    document: dict[str, Any] = {
        "schema": "canli.alphac-wave1-release-candidates.v1",
        "author": "Arhan Canli",
        "status": "PASS_PORTABLE_ARCHIVE_INTEGRITY_ONLY" if not failures else "FAIL",
        "archives": len(records),
        "records": records,
        "failures": failures,
        "source_bindings": {
            "submission_plan": {"path": str(PLAN.relative_to(ROOT)), "sha256": _sha256(PLAN)},
            "data_rights_audit": {
                "path": str(RIGHTS_AUDIT.relative_to(ROOT)),
                "sha256": _sha256(RIGHTS_AUDIT),
                "content_hash": rights["content_hash"],
            },
        },
        "result_generation_replayed": False,
        "independent_replication": False,
        "submission_claimed": False,
        "claim_boundary": (
            "This proves deterministic archive construction, safe extraction and internal file "
            "checksum integrity in a temporary workspace outside the repository. It does not "
            "recompute returns, establish raw-input portability, constitute independent "
            "replication, or claim external submission."
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
