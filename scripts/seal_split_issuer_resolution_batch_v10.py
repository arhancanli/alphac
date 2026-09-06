#!/usr/bin/env python3
"""Seal three exact McLeodUSA and Metzler share mutations without opening returns."""

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
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v10.json"


def _helpers():
    path = REPO / "scripts/seal_split_issuer_resolution_batch_v7.py"
    spec = importlib.util.spec_from_file_location("split_issuer_resolution_v10_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load issuer-resolution helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = _helpers()
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "MCLDQ_1999": {
        "ticker": "MCLDQ",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/919943/"
            "000092838599002618/0000928385-99-002618.txt"
        ),
        "required_fragments": [
            "announced a two-for-one stock split in the form of a stock dividend",
            "the distribution of the additional shares took place on July 26, 1999",
            "The record date for the stock split was July 12, 1999",
        ],
        "instrument_id": "XUSE:CASH:MCLDQUSD",
        "issuer_distribution_date": "1999-07-26",
        "ex_date": "1999-07-27 04:00:00+04:00",
        "issuer_ratio": 2.0,
        "ratio": 2.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "MCLDQ_2000": {
        "ticker": "MCLDQ",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/919943/"
            "000092838500001564/0000928385-00-001564.txt"
        ),
        "required_fragments": [
            "three-for-one stock split effected in the form of a stock dividend",
            "effective April 24, 2000",
        ],
        "instrument_id": "XUSE:CASH:MCLDQUSD",
        "issuer_distribution_date": "2000-04-24",
        "ex_date": "2000-04-25 04:00:00+04:00",
        "issuer_ratio": 3.0,
        "ratio": 3.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "NCI1_1998": {
        "ticker": "NCI1",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1019737/"
            "000095013198002261/0000950131-98-002261.txt"
        ),
        "required_fragments": [
            "a 3-2 stock split being effected in the form of a stock dividend",
            "payable on or about April 1, 1998",
            "to the owners of record at the close of business on March 18, 1998",
        ],
        "instrument_id": "XUSE:CASH:NCI1USD",
        "issuer_effective_date": "1998-04-01",
        "ex_date": "1998-04-01 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
        "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
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
        raise ValueError("exactly the three sealed issuer-event sources are required")
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
        "schema": "canli.alphac-split-issuer-resolution-batch.v10",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "THREE_EXACT_ISSUER_SHARE_MUTATIONS_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": verified,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": HELPERS._sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Merge only these three exact tuples. Keep NCI1 on 1998-04-02 quarantined as a "
            "duplicate issuer-date conflict."
        ),
        "claim_boundary": (
            "This seal verifies two McLeodUSA splits and the issuer-effective NCI1 split. It "
            "does not authorize NCI1's duplicate next-day event, open returns, or pass the "
            "global split gate."
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
