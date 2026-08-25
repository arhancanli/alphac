#!/usr/bin/env python3
"""Seal issuer evidence for BMNR, ACHC, and JHG split-provider exceptions."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Final

import httpx

REPO: Final[Path] = Path(__file__).resolve().parents[1]
LIFECYCLE: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_split_lifecycle_scope.json"
CROSSCHECK: Final[Path] = REPO / "artifacts" / "audit" / "polygon_split_crosscheck.json"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "split_exception_issuer_resolution.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "BMNR": {
        "url": "https://www.sec.gov/Archives/edgar/data/1829311/000168316822005159/bitmine_s1.htm",
        "required_fragments": ["net 1 for 200 reverse-split", "effective as of April 27, 2021"],
        "event_date": "2021-04-27",
        "issuer_ratio": 0.005,
        "stored_ratio": 0.005,
        "provider_ratio": 200.0,
        "resolution": "ISSUER_CONFIRMS_STORED_RATIO_PROVIDER_DIRECTION_REJECTED",
    },
    "ACHC": {
        "url": "https://www.sec.gov/Archives/edgar/data/1520697/000119312511340742/d258032ds1a.htm",
        "required_fragments": ["one-to-four conversion rate", "November 1, 2011"],
        "event_date": "2011-11-01",
        "issuer_ratio": 0.25,
        "stored_ratio": 1.7633,
        "provider_ratio": 0.25,
        "resolution": "STORED_ROW_IS_NOT_ISSUER_MARKET_CONVERSION_KEEP_NONEXECUTABLE",
    },
    "JHG": {
        "url": "https://www.sec.gov/Archives/edgar/data/1274173/000110465917050025/a17-14663_110q.htm",
        "required_fragments": ["10-to-1 share consolidation", "took effect on May 30, 2017"],
        "event_date": "2017-05-30",
        "issuer_ratio": 0.1,
        "stored_ratio": 0.5,
        "provider_ratio": 0.1,
        "resolution": "STORED_ROW_IS_NOT_ISSUER_MARKET_CONSOLIDATION_KEEP_NONEXECUTABLE",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def verify_source(text: str, required_fragments: list[str]) -> None:
    normalized = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(text)).split()).lower()
    normalized = normalized.translate(
        str.maketrans({"\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-"})
    ).replace("-", " ")
    missing = [
        fragment
        for fragment in required_fragments
        if " ".join(fragment.lower().replace("-", " ").split()) not in normalized
    ]
    if missing:
        raise ValueError(f"issuer source is missing required fragments: {missing}")


def _fetch_sources() -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for ticker, source in SOURCES.items():
            response = client.get(source["url"])
            response.raise_for_status()
            verify_source(response.text, source["required_fragments"])
            rows.append(
                {
                    "ticker": ticker,
                    "url": source["url"],
                    "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
                    "required_fragments_verified": source["required_fragments"],
                    "event_date": source["event_date"],
                    "issuer_ratio": source["issuer_ratio"],
                    "stored_ratio": source["stored_ratio"],
                    "provider_ratio": source["provider_ratio"],
                    "resolution": source["resolution"],
                }
            )
    return rows, dt.datetime.now(dt.UTC).isoformat()


def build(sources: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
    crosscheck = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
    lifecycle_by_key = {
        (row["ticker"], str(row["ex_date"])[:10]): row for row in lifecycle["events"]
    }
    resolutions: list[dict[str, Any]] = []
    for source in sources:
        row = lifecycle_by_key[(source["ticker"], source["event_date"])]
        if row["lifecycle_classification"] not in {
            "BEFORE_FIRST_PRICE_NON_EXECUTABLE",
            "FIRST_PRICE_BOUNDARY_NO_PREEXISTING_EXPOSURE",
        }:
            raise ValueError("issuer exception is not outside pre-existing exposure scope")
        resolutions.append(
            {
                **source,
                "lifecycle_classification": row["lifecycle_classification"],
                "first_price_date": row["first_price_date"],
                "executable_action": False,
                "source_row_deleted": False,
                "ratio_repair_authorized": False,
            }
        )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-exception-issuer-resolution.v1",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "ISSUER_EXCEPTIONS_RESOLVED_AS_NONEXECUTABLE_LIFECYCLE_METADATA",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "resolutions": resolutions,
        "lineage": {
            "lifecycle_path": str(LIFECYCLE.relative_to(REPO)),
            "lifecycle_sha256": _sha256(LIFECYCLE),
            "lifecycle_content_hash": lifecycle["content_hash"],
            "provider_crosscheck_path": str(CROSSCHECK.relative_to(REPO)),
            "provider_crosscheck_sha256": _sha256(CROSSCHECK),
            "provider_crosscheck_content_hash": crosscheck["content_hash"],
        },
        "required_next_action": (
            "Implement and test fail-closed lifecycle scoping: source rows outside possible "
            "pre-existing exposure remain in lineage but are not executable share mutations. "
            "Do not infer a general provider precedence rule from these three cases."
        ),
        "claim_boundary": (
            "Issuer evidence resolves only these named exceptions. It does not authorize a "
            "strategy replay, alter a historical result, or validate performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    sources, retrieved_at = _fetch_sources()
    payload = build(sources, retrieved_at=retrieved_at)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    for host in HOSTS:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text(rendered, encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
