#!/usr/bin/env python3
"""Collect the sealed Item 703 filing sample without parsing documents or returns."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_repurchase_item703_manifest import MANIFEST, content_hash_valid
from build_repurchase_item703_manifest import RESULT as MANIFEST_RESULT
from build_sec_10k_manifest import SecClient
from collect_repurchase_issuance_companyfacts import file_sha256

RAW_DIR: Final = Path("data/raw/repurchase_issuance_flow/item703_documents")
OUT_DIR: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/document_parts"
)
RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/item703/documents_result.json"
)
COLLECTOR_VERSION: Final = "repurchase-item703-document-collector-v1"
STATUS_COLUMNS: Final = (
    "cik",
    "accession",
    "filing_year",
    "form",
    "document_url",
    "collector_version",
    "raw_cache_path",
    "raw_sha256",
    "raw_bytes",
    "raw_from_cache",
    "error",
)


def gzip_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    temporary.replace(path)


def gzip_read(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def require_manifest(result_path: Path, manifest_path: Path) -> dict[str, Any]:
    if not result_path.exists() or not manifest_path.exists():
        raise RuntimeError("sealed Item 703 manifest and result are required")
    result = json.loads(result_path.read_text())
    frame = pd.read_parquet(manifest_path)
    if (
        result.get("schema")
        != "canli.feasibility.repurchase-issuance-item703-manifest.v1"
        or result.get("complete") is not True
        or result.get("return_data_opened") is not False
        or result.get("return_hypotheses_spent") != 0
        or result.get("document_manifest_sha256") != file_sha256(manifest_path)
        or result.get("document_sample_size") != len(frame)
        or frame["accession"].nunique() != len(frame)
        or not content_hash_valid(result)
    ):
        raise RuntimeError("Item 703 manifest is incomplete, stale, or not return-sealed")
    return result


def cached_document(
    client: SecClient, accession: str, url: str, raw_dir: Path
) -> tuple[bytes, bool, Path]:
    path = raw_dir / f"{accession}.html.gz"
    if path.exists():
        try:
            return gzip_read(path), True, path
        except (EOFError, OSError):
            path.unlink()
    raw = client.get_bytes(url)
    gzip_write(path, raw)
    return raw, False, path


def process_document(client: SecClient, raw_dir: Path, row: dict) -> dict:
    base = {
        key: row[key]
        for key in ("cik", "accession", "filing_year", "form", "document_url")
    }
    base["collector_version"] = COLLECTOR_VERSION
    try:
        raw, cached, path = cached_document(
            client, str(row["accession"]), str(row["document_url"]), raw_dir
        )
        return {
            **base,
            "raw_cache_path": str(path),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_bytes": len(raw),
            "raw_from_cache": cached,
            "error": None,
        }
    except Exception as error:
        return {
            **base,
            "raw_cache_path": str(raw_dir / f"{row['accession']}.html.gz"),
            "raw_sha256": None,
            "raw_bytes": 0,
            "raw_from_cache": False,
            "error": str(error),
        }


def _part_number(path: Path) -> int:
    return int(path.stem.rsplit("-", 1)[-1])


def completed_accessions(out_dir: Path) -> set[str]:
    latest: dict[str, bool] = {}
    for path in sorted(out_dir.glob("status-*.parquet")):
        frame = pd.read_parquet(
            path, columns=["accession", "collector_version", "error"]
        )
        for row in frame.to_dict("records"):
            latest[str(row["accession"])] = (
                pd.isna(row["error"])
                and row["collector_version"] == COLLECTOR_VERSION
            )
    return {accession for accession, complete in latest.items() if complete}


def write_part(out_dir: Path, part: int, rows: list[dict]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"status-{part:05d}.parquet"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite Item 703 collection part {part}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(rows, columns=STATUS_COLUMNS).to_parquet(
        temporary, index=False, compression="zstd"
    )
    temporary.replace(path)
    return path


def parts_lineage(out_dir: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    paths = sorted(out_dir.glob("status-*.parquet"))
    for path in paths:
        digest.update(
            f"{path.name}\0{path.stat().st_size}\0{file_sha256(path)}\n".encode()
        )
    return len(paths), digest.hexdigest()


def summarize(
    out_dir: Path, expected_accessions: set[str], manifest: dict[str, Any]
) -> dict[str, Any]:
    frames = []
    for path in sorted(out_dir.glob("status-*.parquet")):
        frame = pd.read_parquet(path)
        frame["part_number"] = _part_number(path)
        frames.append(frame)
    status = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(status):
        status = status.sort_values(["accession", "part_number"]).drop_duplicates(
            "accession", keep="last"
        )
    successful = status["error"].isna() if len(status) else pd.Series(dtype=bool)
    current = (
        status["collector_version"].eq(COLLECTOR_VERSION)
        if len(status)
        else pd.Series(dtype=bool)
    )
    current_successes = set(
        status.loc[successful & current, "accession"].astype(str)
    ) if len(status) else set()
    missing = sorted(expected_accessions - current_successes)
    unexpected = sorted(current_successes - expected_accessions)
    exact_identity_set = not missing and not unexpected
    count, digest = parts_lineage(out_dir)
    return {
        "schema": "canli.feasibility.repurchase-issuance-item703-documents.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "raw_item703_documents_no_parsing_no_returns",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "collector_version": COLLECTOR_VERSION,
        "source_manifest_hash": manifest["content_hash"],
        "source_manifest_sha256": manifest["document_manifest_sha256"],
        "expected_documents": len(expected_accessions),
        "attempted_documents": len(status),
        "successful_documents": int(successful.sum()) if len(status) else 0,
        "current_collector_documents": int(current.sum()) if len(status) else 0,
        "missing_accessions": missing,
        "unexpected_accessions": unexpected,
        "exact_manifest_identity_set": exact_identity_set,
        "part_count": count,
        "parts_sha256": digest,
        "documents_parsed": 0,
        "labels_opened": False,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": exact_identity_set,
        "decision": "READY_FOR_BLIND_LABELING"
        if exact_identity_set
        else "COLLECTION_INCOMPLETE",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    manifest_result = require_manifest(Path(args.manifest_result), manifest_path)
    sample = pd.read_parquet(manifest_path).sort_values(
        ["filing_year", "sample_rank", "accession"]
    )
    done = completed_accessions(Path(args.out_dir))
    pending = [row for row in sample.to_dict("records") if row["accession"] not in done]
    if args.max_documents is not None:
        pending = pending[: args.max_documents]
    existing = sorted(Path(args.out_dir).glob("status-*.parquet"))
    next_part = _part_number(existing[-1]) + 1 if existing else 0
    buffer: list[dict] = []
    client = SecClient(Path(args.raw_dir) / "network_metadata_cache")
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = pool.map(
                lambda row: process_document(client, Path(args.raw_dir), row), pending
            )
            for number, row in enumerate(results, 1):
                buffer.append(row)
                if len(buffer) >= args.batch_size:
                    write_part(Path(args.out_dir), next_part, buffer)
                    next_part += 1
                    buffer = []
                if number % 40 == 0 or number == len(pending):
                    print(f"Item 703 documents {number}/{len(pending)} pending", flush=True)
            if buffer:
                write_part(Path(args.out_dir), next_part, buffer)
    finally:
        client.close()
    result = summarize(
        Path(args.out_dir), set(sample["accession"].astype(str)), manifest_result
    )
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--manifest-result", default=str(MANIFEST_RESULT))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--max-documents", type=int)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
