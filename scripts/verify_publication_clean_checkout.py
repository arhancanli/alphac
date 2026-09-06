#!/usr/bin/env python3
"""Verify every tracked publication bundle from a clean Git checkout.

This verifier intentionally uses only the Python standard library and committed files. It proves
archive integrity, source-code/environment bindings, authorship metadata, and fail-closed release
claims before the project environment is installed. It does not regenerate returns or clear data
rights, independent review, or submission gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
AUTHOR: Final = "Arhan Canli"
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
HIGH_CONFIDENCE_SECRET_PATTERNS: Final[dict[str, re.Pattern[bytes]]] = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "stripe_secret": re.compile(rb"sk_(?:live|test)_[A-Za-z0-9]{16,}"),
    "alpaca_literal_assignment": re.compile(
        rb"(?:APCA_API_KEY_ID|APCA_API_SECRET_KEY|APCA-API-KEY-ID|"
        rb"APCA-API-SECRET-KEY)[^\r\n]{0,20}[=:][ \t]*['\"]?"
        rb"[A-Za-z0-9+/=_-]{16,}"
    ),
}
RAW_ROW_SUFFIXES: Final = {
    ".arrow",
    ".csv",
    ".db",
    ".feather",
    ".parquet",
    ".sqlite",
    ".sqlite3",
    ".tsv",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()


def _safe_relative(raw: str) -> PurePosixPath:
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe bundle path: {raw}")
    return relative


def _tracked_paths() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {item.decode() for item in completed.stdout.split(b"\0") if item}


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _checksum_inventory(bundle: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for line in (bundle / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, separator, raw = line.partition("  ")
        if not separator or not HEX64.fullmatch(digest):
            raise ValueError(f"invalid SHA256SUMS row in {bundle}: {line!r}")
        relative = _safe_relative(raw).as_posix()
        if relative in inventory:
            raise ValueError(f"duplicate checksum member in {bundle}: {relative}")
        inventory[relative] = digest
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(inventory) != actual:
        raise ValueError(
            f"checksum inventory mismatch in {bundle}: "
            f"missing={sorted(actual - set(inventory))}, extra={sorted(set(inventory) - actual)}"
        )
    for relative, expected in inventory.items():
        path = bundle / relative
        if path.is_symlink() or _sha256(path) != expected:
            raise ValueError(f"checksum mismatch or symlink in {bundle}: {relative}")
    return inventory


def _assert_false(document: dict[str, Any], field: str, source: Path) -> None:
    if document.get(field) is not False:
        raise ValueError(f"{source}: {field} must be explicitly false")


def _verify_bindings(
    reproduction: dict[str, Any], tracked: set[str], source: Path
) -> tuple[int, int]:
    code_bindings = reproduction.get("code_bindings", {})
    environment_bindings = reproduction.get("environment_bindings", {})
    for collection, label in (
        (code_bindings, "code"),
        (environment_bindings, "environment"),
    ):
        if not isinstance(collection, dict) or not collection:
            raise ValueError(f"{source}: missing {label} bindings")
        for raw, expected in collection.items():
            relative = _safe_relative(str(raw)).as_posix()
            path = ROOT / relative
            if relative not in tracked or not path.is_file() or path.is_symlink():
                raise ValueError(f"{source}: untracked or missing {label} binding {relative}")
            if not isinstance(expected, str) or _sha256(path) != expected:
                raise ValueError(f"{source}: stale {label} binding {relative}")
    return len(code_bindings), len(environment_bindings)


def _verify_result_copies(bundle: Path, data_manifest: dict[str, Any]) -> int:
    count = 0
    for record in data_manifest.get("released_result_objects", []):
        relative = _safe_relative(str(record["bundle_path"])).as_posix()
        path = bundle / relative
        if not path.is_file() or path.is_symlink() or _sha256(path) != record.get("sha256"):
            raise ValueError(f"{bundle}: released result binding failed for {relative}")
        if record.get("byte_identical_to_source") is not True:
            raise ValueError(f"{bundle}: result copy is not declared byte-identical: {relative}")
        count += 1
    return count


def _verify_no_secrets_or_raw_rows(bundle: Path) -> int:
    scanned = 0
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        if path.suffix.lower() in RAW_ROW_SUFFIXES:
            raise ValueError(f"raw-row file is forbidden in preparation bundle: {path}")
        payload = path.read_bytes()
        for label, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            if pattern.search(payload):
                raise ValueError(f"{label} detected in preparation bundle: {path}")
        scanned += 1
    return scanned


def build() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    tracked = _tracked_paths()
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    totals = {
        "checksum_bound_files": 0,
        "code_bindings": 0,
        "environment_bindings": 0,
        "released_result_copies": 0,
        "files_secret_scanned": 0,
        "recorded_hypothesis_identities": 0,
        "machine_validated_pdf_pages": 0,
    }
    for item in registry.get("sleeves", []):
        key = str(item["key"])
        try:
            manifest_path = ROOT / _safe_relative(str(item["bundle_manifest"]))
            bundle = manifest_path.parent
            inventory = _checksum_inventory(bundle)
            bundle_files = {
                path.relative_to(ROOT).as_posix()
                for path in bundle.rglob("*")
                if path.is_file()
            }
            untracked = sorted(bundle_files - tracked)
            if untracked:
                raise ValueError(f"untracked bundle members: {untracked}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("registry_key") != key or manifest.get("author") != AUTHOR:
                raise ValueError("manifest identity or author mismatch")
            if manifest.get("status") != "BUNDLE_INCOMPLETE" or not manifest.get(
                "remaining_blockers"
            ):
                raise ValueError("bundle must remain blocked with explicit blockers")
            for field in (
                "doi_claimed",
                "external_submission_claimed",
                "independent_replication_claimed",
                "peer_review_claimed",
            ):
                _assert_false(manifest, field, manifest_path)

            paper_path = bundle / "paper.json"
            paper = json.loads(paper_path.read_text(encoding="utf-8"))
            authors = paper.get("authors", [])
            if not any(author.get("full_name") == AUTHOR for author in authors):
                raise ValueError("paper author metadata does not name Arhan Canli")
            _assert_false(paper, "peer_reviewed", paper_path)
            if paper.get("external_identifiers") != []:
                raise ValueError("external identifier claimed before publication")

            reproduction_path = bundle / "reproduction.json"
            reproduction = json.loads(reproduction_path.read_text(encoding="utf-8"))
            code_count, env_count = _verify_bindings(
                reproduction, tracked, reproduction_path
            )
            _assert_false(
                reproduction,
                "independent_human_reproduction_completed",
                reproduction_path,
            )
            full_pipeline = reproduction.get(
                "full_pipeline_clean_environment_reproduction_completed",
                reproduction.get("clean_environment_reproduction_completed"),
            )
            if full_pipeline is not False:
                raise ValueError("full clean result reproduction must remain false")

            data_manifest = json.loads(
                (bundle / "data_manifest.json").read_text(encoding="utf-8")
            )
            if data_manifest.get("license_review_complete") is True:
                raise ValueError("unexpected data-rights clearance claim")
            result_copies = _verify_result_copies(bundle, data_manifest)

            trial = json.loads(
                (bundle / "trial_accounting.json").read_text(encoding="utf-8")
            )
            union_complete = trial.get(
                "complete_recorded_union_extracted",
                trial.get("sleeve_complete_union_extracted"),
            )
            if union_complete is not True:
                raise ValueError("recorded sleeve union is not completely extracted")
            identities = int(trial.get("distinct_recorded_hypothesis_identities", 0))

            pdf = json.loads((bundle / "pdf_validation.json").read_text(encoding="utf-8"))
            if pdf.get("passes") is not True or pdf.get("failures") != []:
                raise ValueError("machine PDF validation does not pass")

            scanned = _verify_no_secrets_or_raw_rows(bundle)
            totals["checksum_bound_files"] += len(inventory)
            totals["code_bindings"] += code_count
            totals["environment_bindings"] += env_count
            totals["released_result_copies"] += result_copies
            totals["files_secret_scanned"] += scanned
            totals["recorded_hypothesis_identities"] += identities
            totals["machine_validated_pdf_pages"] += int(pdf["pages"])
            records.append(
                {
                    "registry_key": key,
                    "bundle": manifest_path.parent.relative_to(ROOT).as_posix(),
                    "version": manifest["version"],
                    "status": manifest["status"],
                    "checksum_bound_files": len(inventory),
                    "code_bindings": code_count,
                    "environment_bindings": env_count,
                    "released_result_copies": result_copies,
                    "recorded_hypothesis_identities": identities,
                    "pdf_pages": int(pdf["pages"]),
                    "passes": True,
                }
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"{key}:{type(error).__name__}:{error}")

    document: dict[str, Any] = {
        "schema": "canli.alphac-publication-clean-checkout-integrity.v1",
        "author": AUTHOR,
        "git_commit": _git_head(),
        "status": (
            "PASS_TRACKED_PREPARATION_BUNDLE_INTEGRITY_NOT_RESULT_REPRODUCTION"
            if not failures and len(records) == len(registry.get("sleeves", []))
            else "FAIL"
        ),
        "passes": not failures and len(records) == len(registry.get("sleeves", [])),
        "counts": {
            "bundles": len(records),
            **totals,
            "full_clean_result_reproductions": 0,
            "independent_human_reproductions": 0,
            "external_submissions": 0,
            "data_license_reviews_complete": 0,
        },
        "records": records,
        "failures": failures,
        "source_bindings": {
            "registry": {
                "path": REGISTRY.relative_to(ROOT).as_posix(),
                "sha256": _sha256(REGISTRY),
            },
            "verifier": {
                "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
                "sha256": _sha256(Path(__file__).resolve()),
            },
        },
        "claim_boundary": (
            "This standard-library verifier ran against files tracked by the named Git commit. "
            "It proves checksum-complete preparation bundles, current code and environment "
            "bindings, byte-bound released result copies, machine-validated PDFs, complete "
            "recorded-union extracts, authorship metadata, and the absence of high-confidence "
            "credential patterns or raw-row file formats in those bundles. It does not regenerate "
            "strategy returns, establish raw-input portability or data rights, constitute "
            "independent replication or peer review, authorize outreach, or claim an external "
            "submission. Every bundle remains BUNDLE_INCOMPLETE."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    document = build()
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "status": document["status"],
                "passes": document["passes"],
                "counts": document["counts"],
                "failures": document["failures"],
                "content_hash": document["content_hash"],
                "receipt": str(args.receipt) if args.receipt else None,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if document["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
