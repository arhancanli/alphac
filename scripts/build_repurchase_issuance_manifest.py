#!/usr/bin/env python3
"""Build the sealed 600-CIK SEC schema sample without opening prices or returns."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sec_10k_manifest import SecClient

SOURCE_URL: Final = "https://www.sec.gov/files/company_tickers.json"
RAW: Final = Path("data/raw/repurchase_issuance_flow/company_tickers.json")
OUT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/issuer_schema_sample.parquet"
)
RESULT: Final = Path(
    "artifacts/feasibility/repurchase_issuance_flow/manifest_result.json"
)
SEED: Final = "repurchase_issuance_flow_v1"
SAMPLE_SIZE: Final = 600


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def canonical_issuers(payload: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for value in payload.values():
        try:
            cik = int(value["cik_str"])
            ticker = str(value["ticker"]).strip().upper()
            title = str(value["title"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if cik <= 0 or not ticker or not title:
            continue
        rows.append({"cik": cik, "ticker": ticker, "title": title})
    if not rows:
        raise ValueError("official SEC ticker payload produced no valid issuers")
    frame = pd.DataFrame(rows).drop_duplicates(["cik", "ticker", "title"])
    issuers: list[dict[str, Any]] = []
    for cik, group in frame.groupby("cik", sort=True):
        issuers.append(
            {
                "cik": int(cik),
                "cik_padded": f"CIK{int(cik):010d}",
                "tickers": "|".join(sorted(group["ticker"].unique())),
                "title": sorted(group["title"].unique())[0],
            }
        )
    return pd.DataFrame(issuers).sort_values("cik").reset_index(drop=True)


def locked_sample(issuers: pd.DataFrame, size: int = SAMPLE_SIZE) -> pd.DataFrame:
    if size <= 0 or len(issuers) < size:
        raise ValueError(f"sample size {size} is invalid for {len(issuers)} issuers")
    frame = issuers.copy()
    frame["sample_rank"] = frame["cik"].map(
        lambda cik: hashlib.sha256(
            f"{SEED}|CIK{int(cik):010d}".encode()
        ).hexdigest()
    )
    return frame.sort_values(["sample_rank", "cik"]).head(size).reset_index(drop=True)


def build_manifest(raw: bytes, out: Path, size: int) -> dict[str, Any]:
    payload = json.loads(raw)
    issuers = canonical_issuers(payload)
    sample = locked_sample(issuers, size)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    sample.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(out)
    return {
        "schema": "canli.feasibility.repurchase-issuance-manifest.v1",
        "stage": "official_sec_schema_sample_no_prices_no_returns",
        "protocol": "docs/design/FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md",
        "source_url": SOURCE_URL,
        "source_sha256": sha256_bytes(raw),
        "canonical_issuers": len(issuers),
        "sample_seed": SEED,
        "sample_size": len(sample),
        "sample_file": str(out),
        "sample_sha256": sha256_file(out),
        "unique_ciks": int(sample["cik"].nunique()),
        "return_data_opened": False,
        "return_hypotheses_spent": 0,
        "complete": len(sample) == size and int(sample["cik"].nunique()) == size,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_path = Path(args.raw)
    source_from_cache = raw_path.exists()
    if source_from_cache:
        raw = raw_path.read_bytes()
    else:
        client = SecClient(raw_path.parent / "network_metadata_cache")
        try:
            raw = client.get_bytes(SOURCE_URL)
        finally:
            client.close()
        atomic_write(raw_path, raw)
    result = build_manifest(raw, Path(args.out), args.sample_size)
    result["source_from_cache"] = source_from_cache
    result["generated_at"] = datetime.now(UTC).isoformat()
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["content_hash"] = f"sha256:{sha256_bytes(canonical)}"
    result_path = Path(args.result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--result", default=str(RESULT))
    parser.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
