#!/usr/bin/env python3
"""Collect periodic-filing denominators for the repurchase/issuance feasibility audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sec_10k_manifest import SecClient, filing_frame
from collect_repurchase_issuance_companyfacts import (
    MANIFEST,
    MANIFEST_RESULT,
    file_sha256,
    require_manifest,
)
from collect_repurchase_issuance_companyfacts import (
    PARSER_VERSION as FACTS_PARSER_VERSION,
)

RAW_DIR: Final = Path("data/raw/repurchase_issuance_flow/submissions")
OUT_DIR: Final = Path("artifacts/feasibility/repurchase_issuance_flow/submission_parts")
RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/submissions_collection_result.json"
)
PARSER_VERSION: Final = "repurchase-issuance-submissions-v1"
START_DATE: Final = "2013-01-01"
END_DATE: Final = "2025-12-31"
FORMS: Final = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ACCESSION_PATTERN: Final = re.compile(r"^\d{10}-\d{2}-\d{6}$")
STATUS_COLUMNS: Final = (
    "cik",
    "parser_version",
    "source_pages",
    "source_pages_sha256",
    "periodic_filings",
    "error",
)
FILING_COLUMNS: Final = (
    "cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "acceptance_datetime",
    "primary_document",
    "parser_version",
)


def _page_lineage(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(
            f"{path.name}\0{path.stat().st_size}\0{file_sha256(path)}\n".encode()
        )
    return digest.hexdigest()


def periodic_filings(cik: int, frames: list[pd.DataFrame]) -> list[dict[str, Any]]:
    if not frames:
        return []
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        return []
    dates = combined["filingDate"].astype(str)
    eligible = combined[
        combined["form"].isin(FORMS)
        & dates.between(START_DATE, END_DATE)
        & combined["accessionNumber"].astype(str).map(
            lambda value: bool(ACCESSION_PATTERN.fullmatch(value))
        )
    ].copy()
    rows: list[dict[str, Any]] = []
    for row in eligible.sort_values(
        ["acceptanceDateTime", "accessionNumber", "form"]
    ).to_dict("records"):
        rows.append(
            {
                "cik": int(cik),
                "accession": str(row["accessionNumber"]),
                "form": str(row["form"]),
                "filing_date": str(row["filingDate"]),
                "report_date": str(row["reportDate"]),
                "acceptance_datetime": str(row["acceptanceDateTime"]),
                "primary_document": str(row["primaryDocument"]),
                "parser_version": PARSER_VERSION,
            }
        )
    unique = {
        (row["cik"], row["accession"], row["form"]): row for row in rows
    }
    return list(unique.values())


def process_issuer(client: SecClient, cik: int, raw_dir: Path) -> tuple[dict, list[dict]]:
    names: list[str] = []
    try:
        current_name = f"CIK{cik:010d}.json"
        current = client.json(current_name)
        names.append(current_name)
        frames = [filing_frame(current)]
        for item in current.get("filings", {}).get("files", []):
            name = str(item.get("name") or "")
            filing_from = str(item.get("filingFrom") or "")
            filing_to = str(item.get("filingTo") or "")
            if not name or (filing_to and filing_to < START_DATE) or (
                filing_from and filing_from > END_DATE
            ):
                continue
            frames.append(filing_frame(client.json(name)))
            names.append(name)
        paths = [raw_dir / name for name in names]
        filings = periodic_filings(cik, frames)
        return (
            {
                "cik": int(cik),
                "parser_version": PARSER_VERSION,
                "source_pages": len(paths),
                "source_pages_sha256": _page_lineage(paths),
                "periodic_filings": len(filings),
                "error": None,
            },
            filings,
        )
    except Exception as error:
        return (
            {
                "cik": int(cik),
                "parser_version": PARSER_VERSION,
                "source_pages": len(names),
                "source_pages_sha256": None,
                "periodic_filings": 0,
                "error": str(error),
            },
            [],
        )


def _part_number(path: Path) -> int:
    return int(path.stem.rsplit("-", 1)[-1])


def completed_ciks(out_dir: Path) -> set[int]:
    latest: dict[int, bool] = {}
    for path in sorted(out_dir.glob("issuer-status-*.parquet")):
        frame = pd.read_parquet(path, columns=["cik", "parser_version", "error"])
        for row in frame.to_dict("records"):
            latest[int(row["cik"])] = (
                pd.isna(row["error"]) and row["parser_version"] == PARSER_VERSION
            )
    return {cik for cik, complete in latest.items() if complete}


def write_parts(out_dir: Path, part: int, statuses: list[dict], filings: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / f"issuer-status-{part:05d}.parquet"
    filing_path = out_dir / f"filings-{part:05d}.parquet"
    if status_path.exists() or filing_path.exists():
        raise FileExistsError(f"refusing to overwrite submissions part {part}")
    status_tmp = status_path.with_suffix(status_path.suffix + ".tmp")
    filing_tmp = filing_path.with_suffix(filing_path.suffix + ".tmp")
    pd.DataFrame(statuses, columns=STATUS_COLUMNS).to_parquet(
        status_tmp, index=False, compression="zstd"
    )
    pd.DataFrame(filings, columns=FILING_COLUMNS).to_parquet(
        filing_tmp, index=False, compression="zstd"
    )
    status_tmp.replace(status_path)
    filing_tmp.replace(filing_path)


def parts_lineage(out_dir: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    paths = sorted(out_dir.glob("*.parquet"))
    for path in paths:
        digest.update(
            f"{path.name}\0{path.stat().st_size}\0{file_sha256(path)}\n".encode()
        )
    return len(paths), digest.hexdigest()


def summarize(
    out_dir: Path, expected_ciks: set[int], manifest: dict[str, Any]
) -> dict[str, Any]:
    status_frames = []
    for path in sorted(out_dir.glob("issuer-status-*.parquet")):
        frame = pd.read_parquet(path)
        frame["part_number"] = _part_number(path)
        status_frames.append(frame)
    status = (
        pd.concat(status_frames, ignore_index=True)
        if status_frames
        else pd.DataFrame()
    )
    if len(status):
        status = status.sort_values(["cik", "part_number"]).drop_duplicates(
            "cik", keep="last"
        )
    successful = status["error"].isna() if len(status) else pd.Series(dtype=bool)
    current = (
        status["parser_version"].eq(PARSER_VERSION)
        if len(status)
        else pd.Series(dtype=bool)
    )
    current_successes = (
        set(status.loc[successful & current, "cik"].astype(int))
        if len(status)
        else set()
    )
    missing = sorted(expected_ciks - current_successes)
    unexpected = sorted(current_successes - expected_ciks)
    exact_identity_set = not missing and not unexpected
    part_count, part_hash = parts_lineage(out_dir)
    return {
        "schema": "canli.feasibility.repurchase-issuance-submissions-collection.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_submissions_collection_no_prices_no_returns",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "parser_version": PARSER_VERSION,
        "companyfacts_parser_version": FACTS_PARSER_VERSION,
        "source_manifest_hash": manifest["content_hash"],
        "source_manifest_file_sha256": manifest["sample_sha256"],
        "expected_ciks": len(expected_ciks),
        "attempted_ciks": len(status),
        "successful_ciks": int(successful.sum()) if len(status) else 0,
        "current_parser_ciks": int(current.sum()) if len(status) else 0,
        "missing_ciks": missing,
        "unexpected_ciks": unexpected,
        "exact_manifest_identity_set": exact_identity_set,
        "periodic_filings": int(status.loc[successful, "periodic_filings"].sum())
        if len(status)
        else 0,
        "zero_periodic_filing_ciks": int(
            (successful & status["periodic_filings"].eq(0)).sum()
        )
        if len(status)
        else 0,
        "part_files": part_count,
        "parts_sha256": part_hash,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": exact_identity_set,
        "decision": (
            "READY_FOR_COVERAGE_JOIN"
            if exact_identity_set
            else "COLLECTION_INCOMPLETE"
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    manifest_result = require_manifest(Path(args.manifest_result), manifest_path)
    sample = pd.read_parquet(manifest_path).sort_values("sample_rank")
    expected_ciks = set(sample["cik"].astype(int))
    done = completed_ciks(Path(args.out_dir))
    pending = [int(cik) for cik in sample["cik"] if int(cik) not in done]
    if args.max_issuers is not None:
        pending = pending[: args.max_issuers]
    existing = sorted(Path(args.out_dir).glob("issuer-status-*.parquet"))
    next_part = _part_number(existing[-1]) + 1 if existing else 0
    statuses: list[dict] = []
    filings: list[dict] = []
    raw_dir = Path(args.raw_dir)
    client = SecClient(raw_dir)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = pool.map(lambda cik: process_issuer(client, cik, raw_dir), pending)
            for number, (status, rows) in enumerate(results, 1):
                statuses.append(status)
                filings.extend(rows)
                if len(statuses) >= args.batch_size:
                    write_parts(Path(args.out_dir), next_part, statuses, filings)
                    next_part += 1
                    statuses, filings = [], []
                if number % 50 == 0 or number == len(pending):
                    print(f"submissions {number}/{len(pending)} pending", flush=True)
            if statuses:
                write_parts(Path(args.out_dir), next_part, statuses, filings)
    finally:
        client.close()
    result = summarize(Path(args.out_dir), expected_ciks, manifest_result)
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
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-issuers", type=int)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
