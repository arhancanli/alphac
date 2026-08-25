#!/usr/bin/env python3
"""Seal issuer verification for the two split events exposed in the historical path."""

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
EXPOSURE: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_unresolved_split_exposure.json"
)
CROSSCHECK: Final[Path] = REPO / "artifacts" / "audit" / "polygon_split_crosscheck.json"
OUTPUT: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_exposed_split_issuer_resolution.json"
)
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "ADTX": {
        "url": "https://www.sec.gov/Archives/edgar/data/1726711/000121390022061276/ea166672-8k_aditxt.htm",
        "required_fragments": [
            "one-for-fifty (1-for-50) reverse split",
            "began trading on a split-adjusted basis on September 14, 2022",
        ],
        "instrument_id": "XUSE:CASH:ADTXUSD",
        "ex_date": "2022-09-14 04:00:00+04:00",
        "ratio": 0.02,
    },
    "SPCE": {
        "url": "https://www.sec.gov/Archives/edgar/data/1706946/000119312524159991/d829568d8k.htm",
        "required_fragments": [
            "1-for-20 reverse stock split",
            "commence trading on a split-adjusted basis when the market opens on June 17, 2024",
        ],
        "instrument_id": "XUSE:CASH:SPCEUSD",
        "ex_date": "2024-06-17 04:00:00+04:00",
        "ratio": 0.05,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def verify_source(text: str, fragments: list[str]) -> None:
    normalized = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(text)).split()).lower()
    normalized = normalized.translate(
        str.maketrans({"\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-"})
    ).replace("-", " ")
    missing = [
        fragment
        for fragment in fragments
        if " ".join(fragment.lower().replace("-", " ").split()) not in normalized
    ]
    if missing:
        raise ValueError(f"issuer source is missing required fragments: {missing}")


def _fetch_sources() -> tuple[list[dict[str, Any]], str]:
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for ticker, source in SOURCES.items():
            response = client.get(source["url"])
            response.raise_for_status()
            verify_source(response.text, source["required_fragments"])
            rows.append(
                {
                    "ticker": ticker,
                    **source,
                    "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
                    "required_fragments_verified": source["required_fragments"],
                }
            )
    return rows, dt.datetime.now(dt.UTC).isoformat()


def build(sources: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    exposure = json.loads(EXPOSURE.read_text(encoding="utf-8"))
    crosscheck = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
    held = {
        (row["instrument_id"], row["ex_date"]): row
        for row in exposure["events"]
        if row["exposure_classification"] == "OBSERVED_HELD_PRE_BOUNDARY"
    }
    if len(held) != 2:
        raise ValueError("sealed path no longer has exactly two exposed split exceptions")
    verified_events: list[dict[str, Any]] = []
    for source in sources:
        key = (source["instrument_id"], source["ex_date"])
        event = held[key]
        if float(event["stored_ratio"]) != float(source["ratio"]):
            raise ValueError("issuer ratio does not exactly match the frozen stored ratio")
        if event["provider_classification"] != "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO":
            raise ValueError("exposed event lacks independent provider confirmation")
        verified_events.append(
            {
                **source,
                "ex_date_ms": int(dt.datetime.fromisoformat(source["ex_date"]).timestamp() * 1000),
                "historical_position_evidence": event["held_evidence"],
                "authorization": "BYPASS_PRICE_GAP_HEURISTIC_FOR_THIS_EXACT_EVENT_ONLY",
            }
        )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-operating-margin-exposed-split-issuer-resolution.v1",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "EXACT_EXPOSED_SPLIT_VERIFICATION_AUTHORIZED_FOR_FAIL_CLOSED_REPLAY",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": verified_events,
        "lineage": {
            "exposure_path": str(EXPOSURE.relative_to(REPO)),
            "exposure_sha256": _sha256(EXPOSURE),
            "exposure_content_hash": exposure["content_hash"],
            "provider_crosscheck_path": str(CROSSCHECK.relative_to(REPO)),
            "provider_crosscheck_sha256": _sha256(CROSSCHECK),
            "provider_crosscheck_content_hash": crosscheck["content_hash"],
        },
        "required_next_action": (
            "Teach the engine to accept an explicit content-addressed exact-event verification "
            "map. Every non-matching event must continue through the existing price sanity guard."
        ),
        "claim_boundary": (
            "This authorizes bypassing only the price-gap heuristic for the named event, date, "
            "and ratio tuples. It does not authorize a broad tolerance change, a different ratio, "
            "a replay result, or any performance claim."
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
