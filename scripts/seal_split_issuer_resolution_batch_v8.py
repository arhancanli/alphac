#!/usr/bin/env python3
"""Seal four exact issuer share mutations without opening returns."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Final

import httpx

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CONTEXT: Final[Path] = REPO / "artifacts/audit/unresolved_split_event_context.json"
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v8.json"


def _v7_module():
    path = REPO / "scripts/seal_split_issuer_resolution_batch_v7.py"
    spec = importlib.util.spec_from_file_location("split_issuer_resolution_v7_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load issuer-resolution helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = _v7_module()

SOURCES: Final[dict[str, dict[str, Any]]] = {
    "CRGN_2000": {
        "ticker": "CRGN",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1030653/"
            "000092701600001788/0000927016-00-001788.txt"
        ),
        "required_fragments": [
            "announced a two-for-one split on both our voting common stock",
            "On March 30, 2000, our stockholders of record received one additional share",
            "for every share of voting common stock",
        ],
        "instrument_id": "XUSE:CASH:CRGNUSD",
        "issuer_distribution_date": "2000-03-30",
        "ex_date": "2000-03-31 04:00:00+04:00",
        "issuer_ratio": 2.0,
        "ratio": 2.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "OATS_1998": {
        "ticker": "OATS",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/909990/"
            "000092735698000444/0000927356-98-000444.txt"
        ),
        "required_fragments": [
            "On January 7, 1998, the Company effected a 3-for-2 stock split",
            "for securities held of record as of December 22, 1997",
        ],
        "instrument_id": "XUSE:CASH:OATSUSD",
        "issuer_distribution_date": "1998-01-07",
        "ex_date": "1998-01-08 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "OATS_1999": {
        "ticker": "OATS",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/909990/"
            "000089973300000020/0000899733-00-000020.txt"
        ),
        "required_fragments": [
            "on December 1, 1999, Wild Oats effected 3-for-2 stock splits",
            "November 17, 1999, respectively",
        ],
        "instrument_id": "XUSE:CASH:OATSUSD",
        "issuer_distribution_date": "1999-12-01",
        "ex_date": "1999-12-02 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "ICIX_1998": {
        "ticker": "ICIX",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/885067/"
            "000095014498009211/0000950144-98-009211.txt"
        ),
        "required_fragments": [
            "a two-for-one stock split of the Company's common stock on June 15, 1998",
            "paid in the form of a stock dividend",
            "to holders of record on June 1, 1998",
        ],
        "instrument_id": "XUSE:CASH:ICIXUSD",
        "issuer_distribution_date": "1998-06-15",
        "ex_date": "1998-06-16 04:00:00+04:00",
        "issuer_ratio": 2.0,
        "ratio": 2.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
}


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _fetch_sources() -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for event_id, specification in SOURCES.items():
            response = client.get(specification["url"])
            response.raise_for_status()
            HELPERS.verify_source(response.text, specification["required_fragments"])
            rows.append(
                {
                    "event_id": event_id,
                    **specification,
                    "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
                    "required_fragments_verified": specification["required_fragments"],
                }
            )
    return rows, dt.datetime.now(dt.UTC).isoformat()


def build(sources: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    context = HELPERS._load_sealed(CONTEXT)
    unresolved = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])): row
        for row in context["events"]
    }
    provided = {row["event_id"]: row for row in sources}
    if set(provided) != set(SOURCES):
        raise ValueError("exactly the four sealed issuer-event sources are required")
    verified: list[dict[str, Any]] = []
    for event_id, specification in SOURCES.items():
        source = provided[event_id]
        key = (
            specification["instrument_id"],
            specification["ex_date"],
            float(specification["ratio"]),
        )
        event = unresolved.get(key)
        if event is None:
            raise ValueError(f"issuer evidence does not bind an unresolved frozen event: {key}")
        if float(source["issuer_ratio"]) != float(specification["issuer_ratio"]):
            raise ValueError(f"{event_id} issuer ratio changed from sealed specification")
        if event["nearby_action_context"]:
            raise ValueError(f"{event_id} unexpectedly has companion action context")
        verified.append(
            {
                **source,
                "stored_ratio": float(event["stored_ratio"]),
                "ex_date_ms": int(
                    dt.datetime.fromisoformat(specification["ex_date"]).timestamp() * 1000
                ),
                "prior_context_classification": event["context_classification"],
                "market_date_binding": HELPERS._market_date_binding(
                    specification["ticker"], specification
                ),
                "authorization": "BYPASS_PRICE_GAP_HEURISTIC_FOR_THIS_EXACT_EVENT_ONLY",
            }
        )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-resolution-batch.v8",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "FOUR_EXACT_ISSUER_SHARE_MUTATIONS_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": verified,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": HELPERS._sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Merge only these four exact instrument/date/stored-ratio tuples into the "
            "fail-closed policy. Keep ALLR1 quarantined because its filing does not bind the "
            "vendor event date."
        ),
        "claim_boundary": (
            "This seal verifies four plain split events for CRGN, ICIX, and OATS. It does not "
            "open returns, authorize another event, or pass the global split gate."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    sources, retrieved_at = _fetch_sources()
    payload = build(sources, retrieved_at=retrieved_at)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
