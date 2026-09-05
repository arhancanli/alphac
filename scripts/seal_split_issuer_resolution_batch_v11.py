#!/usr/bin/env python3
"""Seal five exact issuer share mutations without opening returns."""

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
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v11.json"


def _helpers():
    path = REPO / "scripts/seal_split_issuer_resolution_batch_v7.py"
    spec = importlib.util.spec_from_file_location("split_issuer_resolution_v11_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load issuer-resolution helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = _helpers()
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "BYNDQ_2001": {
        "ticker": "BYNDQ",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1060531/"
            "000109581101504316/f74865e10-q.htm"
        ),
        "required_fragments": [
            "On July 2, 2001, the Company completed a reverse stock split",
            "fifteen shares of common stock outstanding were converted into one share",
        ],
        "instrument_id": "XUSE:CASH:BYNDQUSD",
        "issuer_effective_date": "2001-07-02",
        "ex_date": "2001-07-02 04:00:00+04:00",
        "issuer_ratio": 1 / 15,
        "ratio": 0.06667,
        "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
    },
    "NWKC_2001": {
        "ticker": "NWKC",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1087879/"
            "000113724301500051/form10qnci.txt"
        ),
        "required_fragments": [
            "completed a 1-for-15 reverse split of the Company's outstanding common stock",
            "effective and applied to shareholders of record immediately prior to the opening",
            "on Monday, June 18, 2001",
        ],
        "instrument_id": "XUSE:CASH:NWKCUSD",
        "issuer_effective_date": "2001-06-18",
        "ex_date": "2001-06-18 04:00:00+04:00",
        "issuer_ratio": 1 / 15,
        "ratio": 0.06667,
        "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
    },
    "XCEDQ_2001": {
        "ticker": "XCEDQ",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/721176/"
            "000091205701508952/a2045655z10-q.txt"
        ),
        "required_fragments": [
            "approved a 10-for-1 reverse stock split of the Common Stock",
            "made effective March 21, 2001",
            "Fractional shares resulting from the reverse stock split were rounded up",
        ],
        "instrument_id": "XUSE:CASH:XCEDQUSD",
        "issuer_effective_date": "2001-03-21",
        "ex_date": "2001-03-21 04:00:00+04:00",
        "issuer_ratio": 0.1,
        "ratio": 0.1,
        "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
    },
    "CB_1998": {
        "ticker": "CB",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/896159/"
            "000090256198000175/0000902561-98-000175.txt"
        ),
        "required_fragments": [
            "On March 2, 1998 the Company effected a three for one split",
            "Certificates representing the additional shares of stock were mailed on March 2",
            "All share and per share amounts have been restated",
        ],
        "instrument_id": "XUSE:CASH:CBUSD",
        "issuer_distribution_date": "1998-03-02",
        "ex_date": "1998-03-03 04:00:00+04:00",
        "issuer_ratio": 3.0,
        "ratio": 3.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "CCIL_1998": {
        "ticker": "CCIL",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/870762/"
            "000087076298000021/0000870762-98-000021.txt"
        ),
        "required_fragments": [
            "declared a 3-for-2 stock split by way of stock dividend",
            "The record date for this dividend is April 1, 1998",
            "the payment date is April 14, 1998",
        ],
        "instrument_id": "XUSE:CASH:CCILUSD",
        "issuer_distribution_date": "1998-04-14",
        "ex_date": "1998-04-15 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
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
        raise ValueError("exactly the five sealed issuer-event sources are required")
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
        if round(float(specification["issuer_ratio"]), 5) != float(specification["ratio"]):
            raise ValueError(f"{event_id} issuer ratio does not match frozen precision")
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
        "schema": "canli.alphac-split-issuer-resolution-batch.v11",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "FIVE_EXACT_ISSUER_SHARE_MUTATIONS_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": verified,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": HELPERS._sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": "Merge only these five exact instrument/date/stored-ratio tuples.",
        "claim_boundary": (
            "This seal verifies the exact BYNDQ, NWKC, XCEDQ, CB, and CCIL share mutations. It "
            "does not authorize another event, open returns, or pass the global split gate."
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
