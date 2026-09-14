#!/usr/bin/env python3
"""Bring experiment ledgers recorded in another checkout into the canonical union, with a receipt.

WHY. `audit_external_experiment_ledgers.py` found 118 hypothesis identities ledgered in a clone of
this repository that the public trial ledger could not see. The policy's definition of a trial is
"one append-only, config-hash-unique measurement row", wherever it was run, so the honest union
includes them. Copying directories by hand would leave no record of what moved, what was left
behind, or what the union read before and after; this importer writes that record.

What it copies: for every top-level directory under `<source>/artifacts/analysis/` that holds at
least one `experiments.jsonl` and does not yet exist in the canonical tree, the EVIDENCE files:
ledgers, reservations, protocols, results, reports, manifests, source scripts and small tabular
inputs (`EVIDENCE_SUFFIXES`, at most `MAX_EVIDENCE_BYTES` each), skipping replay workspaces,
virtual environments and bulk data (`SKIP_PARTS`), which stay at the source and are listed in the
receipt by directory with file counts and bytes. The source directory is never modified.

What it refuses: a target directory that already exists (an import never merges into or
overwrites canonical evidence), and a source `var/experiments.jsonl` that differs from the
canonical one (two diverging active ledgers need a human, not a copy).

The receipt (`artifacts/audit/external_ledger_import_<stamp>.json`) is hash-bound and records the
union count before and after, so the importer's own arithmetic can be checked against the audit
that motivated it: after == before + the audit's `identities_not_in_canonical` for that tree.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion, hypothesis_hash

REPO = Path(__file__).resolve().parents[1]
RECEIPT_DIR = REPO / "artifacts" / "audit"
SCHEMA = "canli.alphac-external-ledger-import.v1"
AUTHOR = "Arhan Canli"

EVIDENCE_SUFFIXES = frozenset(
    {".jsonl", ".json", ".md", ".py", ".yaml", ".yml", ".txt", ".csv", ".toml", ".cff"}
)
MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
SKIP_PARTS = frozenset({".venv", "workspace", "node_modules", "__pycache__", ".git"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def union_identities(tree: Path) -> int:
    union = ExperimentUnion.discover(tree / "var" / "experiments.jsonl", tree)
    keys: set[str] = set()
    for path in union.paths:
        if path.exists():
            keys.update(hypothesis_hash(r.config) for r in ExperimentLog(path).all())
    return len(keys)


def is_evidence(relative: Path, size: int) -> bool:
    if any(part in SKIP_PARTS for part in relative.parts):
        return False
    return relative.suffix in EVIDENCE_SUFFIXES and size <= MAX_EVIDENCE_BYTES


def ledger_directories(source: Path, canonical: Path) -> tuple[list[Path], list[Path]]:
    """(importable, refused_because_present) top-level analysis directories at the source."""
    importable: list[Path] = []
    present: list[Path] = []
    analysis = source / "artifacts" / "analysis"
    if not analysis.is_dir():
        return importable, present
    for entry in sorted(analysis.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if not any(entry.rglob("experiments.jsonl")):
            continue
        if (canonical / "artifacts" / "analysis" / entry.name).exists():
            present.append(entry)
        else:
            importable.append(entry)
    return importable, present


def plan_directory(entry: Path) -> tuple[list[Path], dict[str, dict[str, int]]]:
    """Files to copy (relative to entry) and what is skipped, by first path component."""
    copy: list[Path] = []
    skipped: dict[str, dict[str, int]] = {}
    for path in sorted(entry.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(entry)
        size = path.stat().st_size
        if is_evidence(relative, size):
            copy.append(relative)
        else:
            bucket = relative.parts[0] if len(relative.parts) > 1 else "."
            row = skipped.setdefault(bucket, {"files": 0, "bytes": 0})
            row["files"] += 1
            row["bytes"] += size
    return copy, skipped


def run(
    source: Path,
    canonical: Path,
    *,
    dry_run: bool,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    source = source.resolve()
    canonical = canonical.resolve()
    if source == canonical:
        raise SystemExit("source and canonical tree are the same directory")
    if not (source / "configs" / "base.yaml").is_file():
        raise SystemExit(f"source is not an engine checkout: {source}")
    source_active = source / "var" / "experiments.jsonl"
    canonical_active = canonical / "var" / "experiments.jsonl"
    both_active = source_active.exists() and canonical_active.exists()
    if both_active and _sha256(source_active) != _sha256(canonical_active):
        raise SystemExit(
            "source var/experiments.jsonl differs from the canonical active ledger; "
            "two diverging active ledgers need a human reconciliation, not a copy"
        )
    before = union_identities(canonical)
    importable, present = ledger_directories(source, canonical)
    directories: list[dict[str, Any]] = []
    copied_files = 0
    copied_bytes = 0
    for entry in importable:
        copy, skipped = plan_directory(entry)
        target = canonical / "artifacts" / "analysis" / entry.name
        files: list[dict[str, Any]] = []
        for relative in copy:
            src = entry / relative
            files.append(
                {"path": str(relative), "bytes": src.stat().st_size, "sha256": _sha256(src)}
            )
            copied_bytes += src.stat().st_size
            if not dry_run:
                dst = target / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        copied_files += len(files)
        directories.append(
            {
                "name": entry.name,
                "source": str(entry),
                "target": str(target),
                "ledgers": sorted(
                    str(p.relative_to(entry)) for p in entry.rglob("experiments.jsonl")
                ),
                "copied_files": files,
                "skipped": skipped,
            }
        )
    after = before if dry_run else union_identities(canonical)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "author": AUTHOR,
        "generated_at": (now or dt.datetime.now(dt.UTC)).isoformat(),
        "claim_boundary": (
            "This receipt records which evidence files were copied from another checkout into "
            "the canonical union and what the union counted before and after. It does not "
            "judge the measurements, does not reserve or admit anything, and does not change "
            "a published number until the publish pipeline regenerates the ledger."
        ),
        "dry_run": dry_run,
        "source_tree": str(source),
        "canonical_tree": str(canonical),
        "active_ledger_identical": bool(source_active.exists() and canonical_active.exists()),
        "directories_imported": directories,
        "directories_refused_already_present": [str(p) for p in present],
        "copied_files": copied_files,
        "copied_bytes": copied_bytes,
        "union_identities_before": before,
        "union_identities_after": after,
        "union_identities_added": after - before,
    }
    canonical_json = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["content_hash"] = "sha256:" + hashlib.sha256(canonical_json).hexdigest()
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, required=True, help="the other engine checkout")
    ap.add_argument("--root", type=Path, default=REPO, help="canonical engine tree")
    ap.add_argument("--receipt", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    receipt = run(args.source, args.root, dry_run=args.dry_run)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    path = args.receipt or (
        args.root / "artifacts" / "audit" / f"external_ledger_import_{stamp}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{'DRY RUN: ' if args.dry_run else ''}{len(receipt['directories_imported'])} "
        f"directories, {receipt['copied_files']} files, {receipt['copied_bytes']:,} bytes; "
        f"refused (already present): {len(receipt['directories_refused_already_present'])}; "
        f"union {receipt['union_identities_before']} -> {receipt['union_identities_after']}"
    )
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
