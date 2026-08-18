#!/usr/bin/env python3
"""Collect the sealed repurchase/issuance Company Facts sample without market data."""

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

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sec_10k_manifest import SecClient

MANIFEST: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/issuer_schema_sample.parquet"
)
MANIFEST_RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/manifest_result.json"
)
RAW_DIR: Final = Path("data/raw/repurchase_issuance_flow/companyfacts")
OUT_DIR: Final = Path("artifacts/feasibility/repurchase_issuance_flow/companyfacts_parts")
RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/companyfacts_collection_result.json"
)
PARSER_VERSION: Final = "repurchase-issuance-companyfacts-v3"
FACTS_URL: Final = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
START_FILED: Final = "2013-01-01"
END_FILED: Final = "2025-12-31"
FORMS: Final = {"10-K", "10-K/A", "10-Q", "10-Q/A"}

TAG_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "repurchase_cash": (
        "PaymentsForRepurchaseOfCommonStock",
    ),
    "issuance_cash": (
        "ProceedsFromIssuanceOfCommonStock",
    ),
    "contamination_preferred_mixed": (
        "PaymentsForRepurchaseOfCommonAndPreferredStock",
        "ProceedsFromIssuanceOfCommonAndPreferredStock",
    ),
    "contamination_stock_compensation": (
        "ProceedsFromIssuanceOfSharesUnderIncentiveAndShareBasedCompensationPlansIncludingStockOptions",
        "ProceedsFromStockOptionsExercised",
        "StockIssuedDuringPeriodSharesStockOptionsExercised",
        "ShareBasedCompensation",
    ),
    "repurchase_shares": (
        "StockRepurchasedAndRetiredDuringPeriodShares",
        "TreasuryStockSharesAcquired",
    ),
    "issuance_shares": (
        "StockIssuedDuringPeriodSharesNewIssues",
    ),
    "contamination_acquisition": (
        "StockIssuedDuringPeriodSharesAcquisitions",
        "StockIssuedDuringPeriodValueAcquisitions",
    ),
    "contamination_stock_split": (
        "StockholdersEquityNoteStockSplitConversionRatio1",
        "StockholdersEquityNoteStockSplitConversionRatio2",
    ),
    "authorization_not_completion": (
        "StockRepurchaseProgramAuthorizedAmount",
        "StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount",
    ),
    "reconciliation": (
        "CommonStockSharesIssued",
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}
TAG_TO_FAMILY: Final = {
    tag: family for family, tags in TAG_FAMILIES.items() for tag in tags
}
STATUS_COLUMNS: Final = (
    "cik",
    "parser_version",
    "source_status",
    "raw_sha256",
    "raw_bytes",
    "raw_from_cache",
    "relevant_fact_rows",
    "relevant_tags",
    "custom_namespaces",
    "custom_tags",
    "custom_fact_rows",
    "error",
)
FACT_COLUMNS: Final = (
    "cik",
    "namespace",
    "tag_family",
    "tag",
    "label",
    "description",
    "unit",
    "value",
    "accession",
    "start",
    "end",
    "filed",
    "form",
    "fiscal_year",
    "fiscal_period",
    "frame",
    "parser_version",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def content_hash_valid(payload: dict[str, Any]) -> bool:
    claimed = payload.get("content_hash")
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return claimed == f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def gzip_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    temporary.replace(path)


def gzip_read(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def require_manifest(result_path: Path, manifest_path: Path) -> dict[str, Any]:
    if not result_path.exists() or not manifest_path.exists():
        raise RuntimeError("sealed issuer manifest and result are required")
    result = json.loads(result_path.read_text())
    if (
        result.get("schema") != "canli.feasibility.repurchase-issuance-manifest.v1"
        or result.get("complete") is not True
        or result.get("return_data_opened") is not False
        or result.get("return_hypotheses_spent") != 0
        or result.get("sample_sha256") != file_sha256(manifest_path)
        or not content_hash_valid(result)
    ):
        raise RuntimeError("issuer manifest is incomplete, stale, or not return-sealed")
    frame = pd.read_parquet(manifest_path)
    if len(frame) != int(result["sample_size"]) or frame["cik"].nunique() != len(frame):
        raise RuntimeError("issuer manifest cardinality does not match its seal")
    return result


def parse_companyfacts(cik: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    gaap = payload.get("facts", {}).get("us-gaap", {})
    rows: list[dict[str, Any]] = []
    for tag, node in gaap.items():
        family = TAG_TO_FAMILY.get(tag)
        if family is None:
            continue
        for unit, facts in node.get("units", {}).items():
            for fact in facts:
                form = str(fact.get("form") or "")
                filed = str(fact.get("filed") or "")
                if form not in FORMS or not (START_FILED <= filed <= END_FILED):
                    continue
                rows.append(
                    {
                        "cik": int(cik),
                        "namespace": "us-gaap",
                        "tag_family": family,
                        "tag": tag,
                        "label": node.get("label"),
                        "description": node.get("description"),
                        "unit": unit,
                        "value": fact.get("val"),
                        "accession": fact.get("accn"),
                        "start": fact.get("start"),
                        "end": fact.get("end"),
                        "filed": filed,
                        "form": form,
                        "fiscal_year": fact.get("fy"),
                        "fiscal_period": fact.get("fp"),
                        "frame": fact.get("frame"),
                        "parser_version": PARSER_VERSION,
                    }
                )
    return sorted(
        rows,
        key=lambda row: (
            str(row["filed"]),
            str(row["accession"]),
            str(row["tag"]),
            str(row["unit"]),
            str(row["start"]),
            str(row["end"]),
        ),
    )


def custom_fact_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    namespaces = {
        namespace: facts
        for namespace, facts in payload.get("facts", {}).items()
        if namespace not in {"us-gaap", "dei"}
    }
    rows = 0
    tags = 0
    for facts in namespaces.values():
        for node in facts.values():
            eligible = 0
            for values in node.get("units", {}).values():
                eligible += sum(
                    str(fact.get("form") or "") in FORMS
                    and START_FILED <= str(fact.get("filed") or "") <= END_FILED
                    for fact in values
                )
            if eligible:
                tags += 1
                rows += eligible
    return {
        "custom_namespaces": json.dumps(sorted(namespaces), separators=(",", ":")),
        "custom_tags": tags,
        "custom_fact_rows": rows,
    }


def cached_companyfacts(client: SecClient, cik: int, raw_dir: Path) -> tuple[bytes, bool]:
    path = raw_dir / f"CIK{cik:010d}.json.gz"
    if path.exists():
        try:
            return gzip_read(path), True
        except (EOFError, OSError):
            path.unlink()
    raw = client.get_bytes(FACTS_URL.format(cik=cik))
    gzip_write(path, raw)
    return raw, False


def process_issuer(client: SecClient, cik: int, raw_dir: Path) -> tuple[dict, list[dict]]:
    base = {"cik": int(cik), "parser_version": PARSER_VERSION}
    try:
        raw, cached = cached_companyfacts(client, cik, raw_dir)
        payload = json.loads(raw)
        facts = parse_companyfacts(cik, payload)
        custom = custom_fact_inventory(payload)
        return (
            {
                **base,
                "source_status": "fetched",
                "raw_sha256": sha256_bytes(raw),
                "raw_bytes": len(raw),
                "raw_from_cache": cached,
                "relevant_fact_rows": len(facts),
                "relevant_tags": len({row["tag"] for row in facts}),
                **custom,
                "error": None,
            },
            facts,
        )
    except httpx.HTTPStatusError as error:
        is_terminal_absence = error.response.status_code == 404
        return (
            {
                **base,
                "source_status": (
                    "not_available_404" if is_terminal_absence else "error"
                ),
                "raw_sha256": None,
                "raw_bytes": 0,
                "raw_from_cache": False,
                "relevant_fact_rows": 0,
                "relevant_tags": 0,
                "custom_namespaces": "[]",
                "custom_tags": 0,
                "custom_fact_rows": 0,
                "error": None if is_terminal_absence else str(error),
            },
            [],
        )
    except Exception as error:
        return (
            {
                **base,
                "source_status": "error",
                "raw_sha256": None,
                "raw_bytes": 0,
                "raw_from_cache": False,
                "relevant_fact_rows": 0,
                "relevant_tags": 0,
                "custom_namespaces": "[]",
                "custom_tags": 0,
                "custom_fact_rows": 0,
                "error": str(error),
            },
            [],
        )


def _part_number(path: Path) -> int:
    return int(path.stem.rsplit("-", 1)[-1])


def completed_ciks(out_dir: Path) -> set[int]:
    latest: dict[int, tuple[int, bool]] = {}
    for path in sorted(out_dir.glob("issuer-status-*.parquet")):
        part = _part_number(path)
        frame = pd.read_parquet(path)
        for row in frame.to_dict("records"):
            source_status = row.get("source_status")
            latest[int(row["cik"])] = (
                part,
                pd.isna(row["error"])
                and row["parser_version"] == PARSER_VERSION
                and (
                    pd.isna(source_status)
                    or source_status in {"fetched", "not_available_404"}
                ),
            )
    return {cik for cik, (_, complete) in latest.items() if complete}


def write_parts(out_dir: Path, part: int, statuses: list[dict], facts: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / f"issuer-status-{part:05d}.parquet"
    fact_path = out_dir / f"facts-{part:05d}.parquet"
    if status_path.exists() or fact_path.exists():
        raise FileExistsError(f"refusing to overwrite collection part {part}")
    status_tmp = status_path.with_suffix(status_path.suffix + ".tmp")
    fact_tmp = fact_path.with_suffix(fact_path.suffix + ".tmp")
    pd.DataFrame(statuses, columns=STATUS_COLUMNS).to_parquet(
        status_tmp, index=False, compression="zstd"
    )
    pd.DataFrame(facts, columns=FACT_COLUMNS).to_parquet(
        fact_tmp, index=False, compression="zstd"
    )
    status_tmp.replace(status_path)
    fact_tmp.replace(fact_path)


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
    statuses = []
    for path in sorted(out_dir.glob("issuer-status-*.parquet")):
        frame = pd.read_parquet(path)
        frame["part_number"] = _part_number(path)
        statuses.append(frame)
    status = pd.concat(statuses, ignore_index=True) if statuses else pd.DataFrame()
    if len(status):
        status = status.sort_values(["cik", "part_number"]).drop_duplicates(
            "cik", keep="last"
        )
    source_status = (
        status.get("source_status", pd.Series(index=status.index, dtype=object))
        if len(status)
        else pd.Series(dtype=object)
    )
    terminal = (
        status["error"].isna()
        & source_status.isin({"fetched", "not_available_404"})
        if len(status)
        else pd.Series(dtype=bool)
    )
    fetched = (
        terminal & source_status.eq("fetched")
        if len(status)
        else pd.Series(dtype=bool)
    )
    unavailable = (
        terminal & source_status.eq("not_available_404")
        if len(status)
        else pd.Series(dtype=bool)
    )
    current = (
        status["parser_version"].eq(PARSER_VERSION)
        if len(status)
        else pd.Series(dtype=bool)
    )
    current_terminal = (
        set(status.loc[terminal & current, "cik"].astype(int))
        if len(status)
        else set()
    )
    missing = sorted(expected_ciks - current_terminal)
    unexpected = sorted(current_terminal - expected_ciks)
    exact_identity_set = not missing and not unexpected
    part_count, part_hash = parts_lineage(out_dir)
    return {
        "schema": "canli.feasibility.repurchase-issuance-companyfacts-collection.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_companyfacts_collection_no_prices_no_returns",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "parser_version": PARSER_VERSION,
        "source_manifest_hash": manifest["content_hash"],
        "source_manifest_file_sha256": manifest["sample_sha256"],
        "expected_ciks": len(expected_ciks),
        "attempted_ciks": len(status),
        "successful_ciks": int(fetched.sum()) if len(status) else 0,
        "terminal_unavailable_404_ciks": int(unavailable.sum()) if len(status) else 0,
        "terminal_accounted_ciks": int(terminal.sum()) if len(status) else 0,
        "collection_error_ciks": int((current & ~terminal).sum()) if len(status) else 0,
        "current_parser_ciks": int(current.sum()) if len(status) else 0,
        "missing_ciks": missing,
        "unexpected_ciks": unexpected,
        "exact_manifest_identity_set": exact_identity_set,
        "relevant_fact_rows": int(status.loc[fetched, "relevant_fact_rows"].sum())
        if len(status)
        else 0,
        "zero_relevant_fact_ciks": int(
            (fetched & status["relevant_fact_rows"].eq(0)).sum()
        )
        if len(status)
        else 0,
        "custom_fact_rows": int(status.loc[fetched, "custom_fact_rows"].sum())
        if len(status)
        else 0,
        "custom_tags": int(status.loc[fetched, "custom_tags"].sum())
        if len(status)
        else 0,
        "part_files": part_count,
        "parts_sha256": part_hash,
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": exact_identity_set,
        "decision": (
            "READY_FOR_COMPANYFACTS_AUDIT"
            if exact_identity_set
            else "COLLECTION_INCOMPLETE"
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest)
    manifest_result = require_manifest(Path(args.manifest_result), manifest_path)
    sample = pd.read_parquet(manifest_path).sort_values("sample_rank")
    expected_ciks = set(sample["cik"].astype(int))
    completed = completed_ciks(Path(args.out_dir))
    pending = [int(cik) for cik in sample["cik"] if int(cik) not in completed]
    if args.max_issuers is not None:
        pending = pending[: args.max_issuers]
    existing = sorted(Path(args.out_dir).glob("issuer-status-*.parquet"))
    next_part = _part_number(existing[-1]) + 1 if existing else 0
    status_buffer: list[dict] = []
    fact_buffer: list[dict] = []
    client = SecClient(Path(args.raw_dir) / "network_metadata_cache")
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = pool.map(
                lambda cik: process_issuer(client, cik, Path(args.raw_dir)), pending
            )
            for number, (status, facts) in enumerate(results, 1):
                status_buffer.append(status)
                fact_buffer.extend(facts)
                if len(status_buffer) >= args.batch_size:
                    write_parts(Path(args.out_dir), next_part, status_buffer, fact_buffer)
                    next_part += 1
                    status_buffer, fact_buffer = [], []
                if number % 50 == 0 or number == len(pending):
                    print(f"companyfacts {number}/{len(pending)} pending", flush=True)
            if status_buffer:
                write_parts(Path(args.out_dir), next_part, status_buffer, fact_buffer)
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
