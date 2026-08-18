#!/usr/bin/env python3
"""Build a no-return, point-in-time Treasury coupon-auction feasibility manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

API: Final = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v1/accounting/od/auctions_query"
)
RAW: Final = Path("data/raw/treasury_auction_concession/auctions_query.json")
OUT_DIR: Final = Path("artifacts/feasibility/treasury_auction_concession")
FIELDS: Final = [
    "record_date",
    "cusip",
    "security_type",
    "security_term",
    "floating_rate",
    "auction_date",
    "issue_date",
    "maturity_date",
    "announcemt_date",
    "announcemtd_cusip",
    "auction_format",
    "closing_time_comp",
    "offering_amt",
    "original_cusip",
    "original_issue_date",
    "original_security_term",
    "pdf_filenm_announcemt",
    "reopening",
]
SAFE_EVENT_FIELDS: Final = [
    "event_identity",
    "source_record_date",
    "announcement_date",
    "auction_date",
    "issue_date",
    "maturity_date",
    "cusip",
    "announced_cusip",
    "security_type",
    "security_term",
    "floating_rate",
    "auction_format",
    "competitive_close_et",
    "offering_amount_usd",
    "reopening",
    "original_cusip",
    "original_issue_date",
    "original_security_term",
    "announcement_pdf_filename",
    "source_url",
]
MIN_EVENTS: Final = 1_000
MIN_POST_PUBLICATION_EVENTS: Final = 500
MIN_COMPLETENESS: Final = 0.99
PUBLICATION_DATE: Final = pd.Timestamp("2013-01-01")


def canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch_payload(start_date: str) -> dict[str, Any]:
    params = {
        "fields": ",".join(FIELDS),
        "filter": f"auction_date:gte:{start_date}",
        "page[size]": "10000",
        "sort": "auction_date,cusip",
    }
    headers = {"User-Agent": "Canli Capital research research@canlicapital.com"}
    with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
        response = client.get(API, params=params)
        response.raise_for_status()
        payload = response.json()
    total = int(payload.get("meta", {}).get("total-count", -1))
    if total < 0 or len(payload.get("data", [])) != total:
        raise RuntimeError(
            f"Fiscal Data response was truncated: rows={len(payload.get('data', []))} total={total}"
        )
    return payload


def parse_nullable(value: Any) -> Any:
    return None if value in (None, "", "null") else value


def build_manifest(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        security_type = str(parse_nullable(record.get("security_type")) or "")
        if security_type not in {"Note", "Bond"}:
            continue
        auction_date = parse_nullable(record.get("auction_date"))
        cusip = parse_nullable(record.get("cusip"))
        if auction_date is None or cusip is None:
            event_identity = None
        else:
            event_identity = f"{auction_date}|{cusip}"
        amount = parse_nullable(record.get("offering_amt"))
        rows.append(
            {
                "event_identity": event_identity,
                "source_record_date": parse_nullable(record.get("record_date")),
                "announcement_date": parse_nullable(record.get("announcemt_date")),
                "auction_date": auction_date,
                "issue_date": parse_nullable(record.get("issue_date")),
                "maturity_date": parse_nullable(record.get("maturity_date")),
                "cusip": cusip,
                "announced_cusip": parse_nullable(record.get("announcemtd_cusip")),
                "security_type": security_type,
                "security_term": parse_nullable(record.get("security_term")),
                "floating_rate": parse_nullable(record.get("floating_rate")),
                "auction_format": parse_nullable(record.get("auction_format")),
                "competitive_close_et": parse_nullable(record.get("closing_time_comp")),
                "offering_amount_usd": float(amount) if amount is not None else None,
                "reopening": parse_nullable(record.get("reopening")),
                "original_cusip": parse_nullable(record.get("original_cusip")),
                "original_issue_date": parse_nullable(record.get("original_issue_date")),
                "original_security_term": parse_nullable(record.get("original_security_term")),
                "announcement_pdf_filename": parse_nullable(
                    record.get("pdf_filenm_announcemt")
                ),
                "source_url": API,
            }
        )
    frame = pd.DataFrame(rows, columns=SAFE_EVENT_FIELDS)
    for column in [
        "source_record_date",
        "announcement_date",
        "auction_date",
        "issue_date",
        "maturity_date",
        "original_issue_date",
    ]:
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame.sort_values(["auction_date", "cusip"], na_position="last").reset_index(drop=True)


def summarize(frame: pd.DataFrame, raw_sha256: str, source_rows: int) -> dict[str, Any]:
    rows = len(frame)
    core_fields = [
        "event_identity",
        "announcement_date",
        "auction_date",
        "issue_date",
        "cusip",
        "security_type",
        "security_term",
        "floating_rate",
        "offering_amount_usd",
        "reopening",
    ]
    completeness = {
        field: float(frame[field].notna().mean()) if rows else 0.0 for field in core_fields
    }
    lead_days = (frame["auction_date"] - frame["announcement_date"]).dt.days
    nonnegative_lead_rate = float(lead_days.ge(0).mean()) if rows else 0.0
    one_day_lead_rate = float(lead_days.ge(1).mean()) if rows else 0.0
    unique_identity_rate = (
        float(frame["event_identity"].nunique(dropna=True) / rows) if rows else 0.0
    )
    post_publication_events = int(frame["auction_date"].ge(PUBLICATION_DATE).sum())
    gates = {
        "minimum_events": rows >= MIN_EVENTS,
        "minimum_post_publication_events": post_publication_events
        >= MIN_POST_PUBLICATION_EVENTS,
        "core_field_completeness": min(completeness.values(), default=0.0)
        >= MIN_COMPLETENESS,
        "announcement_not_after_auction": nonnegative_lead_rate >= MIN_COMPLETENESS,
        "at_least_one_day_notice": one_day_lead_rate >= MIN_COMPLETENESS,
        "unique_event_identity": unique_identity_rate == 1.0,
    }
    decision = "PASS_TO_RETURN_PREREGISTRATION" if all(gates.values()) else "FAIL_FEASIBILITY"
    return {
        "schema": "canli.feasibility.treasury-auction-concession.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_metadata_only_no_prices_no_returns",
        "source_url": API,
        "source_rows": source_rows,
        "raw_sha256": raw_sha256,
        "coupon_auction_events": rows,
        "post_2013_events": post_publication_events,
        "first_auction_date": frame["auction_date"].min().date().isoformat() if rows else None,
        "last_auction_date": frame["auction_date"].max().date().isoformat() if rows else None,
        "security_type_counts": {
            str(key): int(value) for key, value in frame["security_type"].value_counts().items()
        },
        "floating_rate_counts": {
            str(key): int(value) for key, value in frame["floating_rate"].value_counts().items()
        },
        "core_field_completeness": completeness,
        "announcement_not_after_auction_rate": nonnegative_lead_rate,
        "at_least_one_day_notice_rate": one_day_lead_rate,
        "unique_event_identity_rate": unique_identity_rate,
        "announcement_pdf_filename_rate": float(
            frame["announcement_pdf_filename"].notna().mean()
        )
        if rows
        else 0.0,
        "gates": gates,
        "decision": decision,
        "return_hypotheses_spent": 0,
    }


def run(start_date: str, raw_path: Path, out_dir: Path) -> dict[str, Any]:
    payload = fetch_payload(start_date)
    raw_bytes = canonical_json(payload)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_raw = raw_path.with_suffix(raw_path.suffix + ".tmp")
    temporary_raw.write_bytes(raw_bytes)
    temporary_raw.replace(raw_path)

    frame = build_manifest(payload["data"])
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "events.parquet"
    temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    frame.to_parquet(temporary_manifest, index=False, compression="zstd")
    temporary_manifest.replace(manifest_path)

    result = summarize(frame, sha256_bytes(raw_bytes), len(payload["data"]))
    result["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    result_path = out_dir / "result.json"
    temporary_result = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary_result.write_text(json.dumps(result, indent=2) + "\n")
    temporary_result.replace(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2000-01-01")
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    print(json.dumps(run(args.start_date, args.raw, args.out_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
