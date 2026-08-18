#!/usr/bin/env python3
"""Audit locked SC 14D9 document extraction without loading prices or returns."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_sec_filing_text_feasibility import (
    FLAGS,
    PARSER_VERSION,
    PREFIX,
    _span,
    html_to_text,
    sha256_bytes,
    sha256_text,
)
from build_sec_10k_manifest import SecClient

SAMPLE: Final = Path("artifacts/feasibility/merger_arbitrage/locked_document_sample.csv")
OUT: Final = Path("artifacts/feasibility/tender_offer_spread")
RAW: Final = Path("data/raw/sec_tender_offer_sample")
PROTOCOL: Final = "docs/design/FEASIBILITY_TENDER_OFFER_SPREAD.md"
ITEM4_START: Final = (
    re.compile(
        PREFIX
        + r"item\s+4\s*[.\-:\u2013\u2014]*\s*(?:the\s+)?solicitation\s+or\s+recommendation\b",
        FLAGS,
    ),
)
ITEM4_END: Final = tuple(
    re.compile(PREFIX + rf"item\s+{number}\s*[.\-:\u2013\u2014]", FLAGS)
    for number in range(5, 10)
)
STRICT_PRICE: Final = re.compile(
    r"(?i)(?:offer\s+price|purchase\s+price|cash\s+consideration|consideration|price\s+of)"
    r"[^$\n]{0,180}?\$\s*([0-9]{1,4}(?:\.[0-9]{1,2})?)"
    r"[^.\n]{0,100}(?:per\s+(?:share|common\s+share)|a\s+share)"
)
ACCEPT_PATTERNS: Final = (
    re.compile(
        r"(?i)board[^.]{0,180}\brecommends?\b(?!\s+against\b)"
        r"[^.]{0,180}\b(?:accept|tender)\b"
    ),
    re.compile(
        r"(?i)unanimously\s+recommends?\b(?!\s+against\b)"
        r"[^.]{0,180}\b(?:accept|tender)\b"
    ),
)
REJECT_PATTERNS: Final = (
    re.compile(r"(?i)board[^.]{0,180}\brecommends?\b[^.]{0,180}\b(?:reject|not\s+tender)"),
    re.compile(r"(?i)recommends?\s+against\s+(?:accepting|tendering)"),
)
NEUTRAL_PATTERNS: Final = (
    re.compile(r"(?i)express(?:es|ed)?\s+no\s+(?:opinion|position)"),
    re.compile(r"(?i)(?:unable|remain(?:s|ed)?\s+unable)\s+to\s+make\s+a\s+recommendation"),
    re.compile(r"(?i)remain(?:s|ed)?\s+neutral"),
)


def extract_item4(text: str) -> str | None:
    return _span(text, ITEM4_START, ITEM4_END, minimum_words=50)


def price_candidates(section: str) -> list[float]:
    values = {
        round(float(match.group(1)), 2)
        for match in STRICT_PRICE.finditer(section)
        if 1.0 <= float(match.group(1)) <= 1000.0
    }
    return sorted(values)


def recommendation(section: str) -> str:
    found = {
        label
        for label, patterns in (
            ("recommend_accept", ACCEPT_PATTERNS),
            ("recommend_reject", REJECT_PATTERNS),
            ("neutral_or_unable", NEUTRAL_PATTERNS),
        )
        if any(pattern.search(section) for pattern in patterns)
    }
    return next(iter(found)) if len(found) == 1 else "unresolved"


def load_locked_sample(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame = frame[frame["form"].eq("SC 14D9")].copy()
    frame["year"] = pd.to_datetime(frame["filing_date"]).dt.year
    counts = frame.groupby("year").size().to_dict()
    expected = dict.fromkeys(range(2016, 2026), 10)
    if counts != expected or len(frame) != 100:
        raise RuntimeError(f"locked tender sample changed: {counts}")
    return frame.sort_values(["year", "sample_rank", "cik", "accession"]).reset_index(drop=True)


def frozen_audit_set(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.groupby("year", group_keys=False).head(3).reset_index(drop=True)


def read_or_fetch(client: SecClient, url: str, path: Path) -> tuple[bytes, bool]:
    if path.exists():
        return gzip.decompress(path.read_bytes()), True
    raw = client.get_bytes(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    return raw, False


def build_audit_labels(rows: pd.DataFrame, path: Path) -> None:
    if path.exists():
        return
    audit_ids = set(frozen_audit_set(load_locked_sample(SAMPLE))["accession"].astype(str))
    labels = rows[rows["accession"].astype(str).isin(audit_ids)][
        ["cik", "accession", "year", "source_url", "document_sha256"]
    ].copy()
    labels["human_unique_cash_price"] = ""
    labels["human_recommendation"] = ""
    labels["human_notes"] = ""
    labels.to_csv(path, index=False)


def score_labels(rows: pd.DataFrame, path: Path) -> dict:
    if not path.exists():
        return {"complete": False, "labeled": 0, "required": 30}
    labels = pd.read_csv(path, keep_default_na=False)
    valid_postures = {"recommend_accept", "recommend_reject", "neutral_or_unable", "ineligible"}
    complete = labels["human_unique_cash_price"].ne("") & labels["human_recommendation"].isin(
        valid_postures
    )
    if not complete.all():
        return {"complete": False, "labeled": int(complete.sum()), "required": len(labels)}
    merged = labels.merge(
        rows[["accession", "unique_price", "recommendation"]], on="accession", validate="one_to_one"
    )
    expected_price = pd.to_numeric(merged["human_unique_cash_price"], errors="coerce")
    predicted_price = pd.to_numeric(merged["unique_price"], errors="coerce")
    human_ineligible = merged["human_recommendation"].eq("ineligible")
    price_match = (human_ineligible & predicted_price.isna()) | (
        ~human_ineligible & expected_price.eq(predicted_price)
    )
    posture_match = human_ineligible | merged["human_recommendation"].eq(
        merged["recommendation"]
    )
    return {
        "complete": True,
        "labeled": len(merged),
        "required": len(merged),
        "price_or_ineligibility_exact_rate": float(price_match.mean()),
        "recommendation_exact_rate": float(posture_match.mean()),
    }


def run(args: argparse.Namespace) -> dict:
    sample = load_locked_sample(Path(args.sample))
    out = Path(args.out)
    raw_dir = Path(args.raw)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    client = SecClient(raw_dir / "network_metadata_cache")
    try:
        records = sample.to_dict("records")
        for index, record in enumerate(records, 1):
            cache = raw_dir / f"{int(record['cik'])}_{record['accession']}.html.gz"
            try:
                raw, cached = read_or_fetch(client, str(record["source_url"]), cache)
                if not cached and args.uncached_delay > 0:
                    time.sleep(args.uncached_delay)
                text = html_to_text(raw)
                section = extract_item4(text)
                candidates = price_candidates(section or "")
                rows.append(
                    {
                        **record,
                        "parser_version": PARSER_VERSION,
                        "document_cache_path": str(cache),
                        "document_sha256": sha256_bytes(raw),
                        "document_bytes": len(raw),
                        "document_from_cache": cached,
                        "document_words": len(text.split()),
                        "item4_extracted": section is not None,
                        "item4_words": len(section.split()) if section else 0,
                        "item4_sha256": sha256_text(section) if section else None,
                        "strict_price_candidates": candidates,
                        "strict_price_count": len(candidates),
                        "unique_price": candidates[0] if len(candidates) == 1 else None,
                        "recommendation": recommendation(section or ""),
                        "item4_text": section,
                        "error": None,
                    }
                )
            except Exception as error:
                rows.append({**record, "error": str(error), "item4_extracted": False})
            if index % 10 == 0 or index == len(records):
                print(f"tender documents {index}/{len(records)}", flush=True)
    finally:
        client.close()

    frame = pd.DataFrame(rows)
    frame.to_parquet(out / "document_audit.parquet", index=False, compression="zstd")
    labels_path = out / "frozen_human_labels.csv"
    build_audit_labels(frame, labels_path)
    successful = frame["error"].isna()
    extracted = successful & frame["item4_extracted"].fillna(False)
    extracted_frame = frame[extracted]
    gates = {
        "documents_100_of_100": int(successful.sum()) == 100,
        "item4_extraction_rate_gte_0_90": float(extracted.mean()) >= 0.90,
        "strict_clause_rate_gte_0_85": (
            float(extracted_frame["strict_price_count"].gt(0).mean()) >= 0.85
            if len(extracted_frame)
            else False
        ),
        "unique_price_rate_gte_0_80": (
            float(extracted_frame["strict_price_count"].eq(1).mean()) >= 0.80
            if len(extracted_frame)
            else False
        ),
        "ambiguous_price_rate_lte_0_10": (
            float(extracted_frame["strict_price_count"].gt(1).mean()) <= 0.10
            if len(extracted_frame)
            else False
        ),
        "recommendation_resolution_rate_gte_0_80": (
            float(extracted_frame["recommendation"].ne("unresolved").mean()) >= 0.80
            if len(extracted_frame)
            else False
        ),
    }
    accuracy = score_labels(frame, labels_path)
    machine_pass = all(gates.values())
    accuracy_pass = bool(
        accuracy.get("complete")
        and accuracy.get("price_or_ineligibility_exact_rate", 0) >= 0.95
        and accuracy.get("recommendation_exact_rate", 0) >= 0.90
    )
    decision = (
        "PASS_TO_RETURN_PREREGISTRATION"
        if machine_pass and accuracy_pass
        else "HUMAN_AUDIT_REQUIRED"
        if machine_pass and not accuracy.get("complete")
        else "DATA_GATED"
    )
    result = {
        "schema": "canli.feasibility.tender-offer-document.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": "official_document_feasibility_no_prices_no_returns",
        "protocol": PROTOCOL,
        "hypothesis_identities_spent": 0,
        "sample_rows": len(frame),
        "successful_downloads": int(successful.sum()),
        "item4_extracted": int(extracted.sum()),
        "item4_extraction_rate": float(extracted.mean()),
        "strict_clause_rate_of_extracted": float(
            extracted_frame["strict_price_count"].gt(0).mean()
        ) if len(extracted_frame) else 0.0,
        "unique_price_rate_of_extracted": float(
            extracted_frame["strict_price_count"].eq(1).mean()
        ) if len(extracted_frame) else 0.0,
        "ambiguous_price_rate_of_extracted": float(
            extracted_frame["strict_price_count"].gt(1).mean()
        ) if len(extracted_frame) else 0.0,
        "recommendation_resolution_rate": float(
            extracted_frame["recommendation"].ne("unresolved").mean()
        ) if len(extracted_frame) else 0.0,
        "gates": gates,
        "human_accuracy_audit": accuracy,
        "decision": decision,
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", default=str(SAMPLE))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--raw", default=str(RAW))
    parser.add_argument("--uncached-delay", type=float, default=0.8)
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
