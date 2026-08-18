#!/usr/bin/env python3
"""Audit public 10-K major-customer source feasibility without opening return data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
from audit_sec_filing_text_feasibility import PARSER_VERSION, html_to_text

MANIFEST: Final = Path("artifacts/ingest/earnings_narrative_change/filings_manifest.parquet")
DOCUMENTS: Final = Path("data/raw/sec_10k_narrative/documents")
OUT_DIR: Final = Path("artifacts/feasibility/customer_supplier_propagation")
START_DATE: Final = pd.Timestamp("2016-01-01")
END_DATE: Final = pd.Timestamp("2025-12-31")
YEARS: Final = tuple(range(2016, 2026))
SAMPLE_PER_YEAR: Final = 30

MARKER_TEXT: Final = (
    r"(?:(?:1\d|[2-9]\d|100)(?:\.\d+)?\s*(?:%|percent)|ten\s+percent)"
)
CONCENTRATION_RE: Final = re.compile(
    rf"(?:\bcustomer\w*\b.{{0,400}}?{MARKER_TEXT}|{MARKER_TEXT}.{{0,400}}?\bcustomer\w*\b)",
    re.IGNORECASE | re.DOTALL,
)
WINDOW_MARKER_RE: Final = re.compile(MARKER_TEXT, re.IGNORECASE)
GENERIC_NAME_RE: Final = re.compile(
    r"^(?:a|an|the|one|two|three|four|five|single|largest|major|significant|other|"
    r"customer(?:\s+[a-z0-9]+)?|customers?|government|governmental|federal|state|local|"
    r"domestic|foreign|international|public|private|related|unrelated|none|no)$",
    re.IGNORECASE,
)
PROPER_NAME: Final = r"[A-Z][A-Za-z0-9&'\-]*(?:[ \t]+[A-Z][A-Za-z0-9&'.,\-]*){0,7}"
STRICT_PATTERNS: Final = (
    re.compile(
        rf"(?P<name>{PROPER_NAME})[ \t]+(?:accounted for|represented|comprised|constituted)"
        rf"[ \t]+(?:approximately[ \t]+|about[ \t]+)?(?P<pct>\d{{1,3}}(?:\.\d+)?)\s*(?:%|percent)",
    ),
    re.compile(
        rf"(?:sales|revenue)[ \t]+(?:to|from)[ \t]+(?P<name>{PROPER_NAME}).{{0,80}}?"
        rf"(?P<pct>\d{{1,3}}(?:\.\d+)?)\s*(?:%|percent)",
        re.IGNORECASE,
    ),
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_path(cik: int, accession: str, root: Path = DOCUMENTS) -> Path:
    return root / f"{int(cik)}_{accession}.html.gz"


def prefilter_text(raw: bytes) -> str:
    """Create a recall-oriented text view without invoking the slower filing parser."""
    value = raw.decode("utf-8", errors="replace")
    value = re.sub(r"<[^>]{0,1000}>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def is_concentration_candidate(raw: bytes) -> bool:
    return CONCENTRATION_RE.search(prefilter_text(raw)) is not None


def concentration_windows(text: str, radius: int = 500) -> list[str]:
    windows: list[str] = []
    for match in WINDOW_MARKER_RE.finditer(text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        window = re.sub(r"\s+", " ", text[start:end]).strip()
        if re.search(r"\bcustomer\w*\b", window, re.IGNORECASE):
            windows.append(window)
    return list(dict.fromkeys(windows))


def _clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ,.;:-")
    value = re.sub(r"^(?:and|or|with|from|to|of|for)\s+", "", value, flags=re.IGNORECASE)
    return value


def strict_name_candidates(window: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for pattern_id, pattern in enumerate(STRICT_PATTERNS, start=1):
        for match in pattern.finditer(window):
            name = _clean_name(match.group("name"))
            pct = float(match.group("pct"))
            if pct < 10 or pct > 100 or not name or GENERIC_NAME_RE.fullmatch(name):
                continue
            if re.fullmatch(r"(?:Customer|Customers?)\s+[A-Z0-9]+", name, re.IGNORECASE):
                continue
            candidates.append({"name": name, "percent": pct, "pattern_id": pattern_id})
    unique = {(item["name"], item["percent"], item["pattern_id"]): item for item in candidates}
    return [unique[key] for key in sorted(unique)]


def _scan_one(row: dict[str, Any], documents: Path) -> dict[str, Any]:
    path = document_path(int(row["cik"]), str(row["accession"]), documents)
    base = {
        "filing_identity": row["filing_identity"],
        "cik": int(row["cik"]),
        "accession": str(row["accession"]),
        "filing_date": str(row["filing_date"]),
        "acceptance_datetime": str(row["acceptance_datetime"]),
        "document_url": str(row["document_url"]),
        "cache_path": str(path),
        "exists": path.exists(),
        "decompress_ok": False,
        "concentration_candidate": False,
    }
    if not path.exists():
        return base
    try:
        raw = gzip.decompress(path.read_bytes())
    except (OSError, EOFError):
        return base
    base["decompress_ok"] = True
    base["concentration_candidate"] = is_concentration_candidate(raw)
    return base


def _sample_rank(cik: int, accession: str) -> str:
    return hashlib.sha256(f"customer_supplier|{cik}|{accession}".encode()).hexdigest()


def _audit_sample(row: dict[str, Any], documents: Path) -> dict[str, Any]:
    path = Path(str(row["cache_path"]))
    raw = gzip.decompress(path.read_bytes())
    text = html_to_text(raw)
    windows = concentration_windows(text)
    names = [candidate for window in windows for candidate in strict_name_candidates(window)]
    unique_names = {(item["name"], item["percent"], item["pattern_id"]): item for item in names}
    ordered_names = [unique_names[key] for key in sorted(unique_names)]
    return {
        **row,
        "document_sha256": sha256_bytes(raw),
        "parser_version": PARSER_VERSION,
        "qualifying_windows": len(windows),
        "strict_name_candidates": len(ordered_names),
        "strict_names_json": json.dumps(ordered_names, sort_keys=True),
        "windows_json": json.dumps(windows, ensure_ascii=False),
    }


def run(manifest_path: Path, documents: Path, out_dir: Path, workers: int) -> dict[str, Any]:
    manifest = pd.read_parquet(manifest_path)
    filing_dates = pd.to_datetime(manifest["filing_date"], errors="coerce")
    frame = manifest[filing_dates.between(START_DATE, END_DATE)].copy()
    frame["year"] = pd.to_datetime(frame["filing_date"]).dt.year
    records = frame.to_dict("records")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        scans = list(executor.map(lambda row: _scan_one(row, documents), records))
    scan = pd.DataFrame(scans)
    scan["year"] = pd.to_datetime(scan["filing_date"]).dt.year
    candidates = scan[scan["concentration_candidate"]].copy()
    candidates["sample_rank"] = [
        _sample_rank(int(cik), str(accession))
        for cik, accession in zip(candidates["cik"], candidates["accession"], strict=True)
    ]
    candidates = candidates.sort_values(["year", "sample_rank", "cik", "accession"])
    sample = candidates.groupby("year", group_keys=False).head(SAMPLE_PER_YEAR).copy()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        audited_rows = list(
            executor.map(lambda row: _audit_sample(row, documents), sample.to_dict("records"))
        )
    audited = pd.DataFrame(audited_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = out_dir / "candidate_manifest.parquet"
    sample_path = out_dir / "document_sample.parquet"
    candidates.to_parquet(candidate_path, index=False)
    audited.to_parquet(sample_path, index=False)

    rows_by_year = {str(year): int((frame["year"] == year).sum()) for year in YEARS}
    candidates_by_year = {str(year): int((candidates["year"] == year).sum()) for year in YEARS}
    sample_by_year = {str(year): int((audited["year"] == year).sum()) for year in YEARS}
    # Both booleans are required row-wise; avoid treating separate marginal counts as coverage.
    source_ok = int((scan["exists"] & scan["decompress_ok"]).sum())
    source_coverage = source_ok / len(scan) if len(scan) else 0.0
    named_docs = int((audited["strict_name_candidates"] > 0).sum()) if len(audited) else 0
    named_rate = named_docs / len(audited) if len(audited) else 0.0
    lineage_complete = bool(
        len(audited)
        and audited[["cik", "accession", "acceptance_datetime", "document_url", "document_sha256"]]
        .notna()
        .all(axis=None)
    )
    gates = {
        "source_coverage_at_least_99pct": source_coverage >= 0.99,
        "at_least_500_concentration_candidates": len(candidates) >= 500,
        "at_least_25_candidates_each_year": all(
            value >= 25 for value in candidates_by_year.values()
        ),
        "exactly_30_sample_rows_each_year": all(
            value == SAMPLE_PER_YEAR for value in sample_by_year.values()
        ),
        "strict_named_document_rate_at_least_50pct": named_rate >= 0.50,
        "sample_lineage_complete": lineage_complete,
    }
    decision = "PASS_TO_ENTITY_RESOLUTION" if all(gates.values()) else "DATA_GATED"
    result = {
        "schema": "canli.feasibility.customer-supplier-propagation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_10k_relationship_source_no_prices_no_returns",
        "decision": decision,
        "return_data_opened": False,
        "market_data_opened": False,
        "return_hypotheses_spent": 0,
        "protocol": "docs/design/FEASIBILITY_CUSTOMER_SUPPLIER_PROPAGATION.md",
        "protocol_sha256": sha256_file(
            Path("docs/design/FEASIBILITY_CUSTOMER_SUPPLIER_PROPAGATION.md")
        ),
        "literature_review": "docs/design/LITERATURE_CUSTOMER_SUPPLIER_PROPAGATION.md",
        "manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
            "rows_in_period": len(frame),
            "rows_by_year": rows_by_year,
        },
        "source_audit": {
            "documents_present_and_decompressible": source_ok,
            "source_coverage": source_coverage,
            "concentration_candidates": len(candidates),
            "candidates_by_year": candidates_by_year,
        },
        "sample_audit": {
            "rows": len(audited),
            "rows_by_year": sample_by_year,
            "documents_with_strict_name_candidate": named_docs,
            "strict_named_document_rate": named_rate,
            "strict_name_candidates": int(audited["strict_name_candidates"].sum())
            if len(audited)
            else 0,
        },
        "gates": gates,
        "artifacts": {
            "candidate_manifest": {
                "path": str(candidate_path),
                "sha256": sha256_file(candidate_path),
                "rows": len(candidates),
            },
            "document_sample": {
                "path": str(sample_path),
                "sha256": sha256_file(sample_path),
                "rows": len(audited),
            },
        },
        "remaining_gates": [
            "blind_human_extraction_accuracy",
            "historical_public_issuer_resolution",
            "relationship_expiry_and_amendment_lineage",
            "customer_event_identity_preregistration",
            "market_data_and_execution_validation",
        ],
        "claim_boundary": (
            "No relationship-resolution, sign, horizon, return, Sharpe, drawdown, correlation, "
            "capacity, or sleeve-admission claim is authorized."
        ),
    }
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--documents", type=Path, default=DOCUMENTS)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.manifest, args.documents, args.out_dir, args.workers)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
