#!/usr/bin/env python3
"""Seal the exact UTI Energy stock split without opening returns."""

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
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v9.json"


def _helpers():
    path = REPO / "scripts/seal_split_issuer_resolution_batch_v7.py"
    spec = importlib.util.spec_from_file_location("split_issuer_resolution_v9_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load issuer-resolution helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = _helpers()
SOURCE: Final[dict[str, Any]] = {
    "ticker": "UTI1",
    "url": (
        "https://www.sec.gov/Archives/edgar/data/912899/"
        "000095012900005078/0000950129-00-005078.txt"
    ),
    "required_fragments": [
        "On September 14, 2000, UTI's Board of Directors authorized a two for one stock split",
        "The stock dividend was paid on October 3, 2000",
        "to stockholders of record on September 25, 2000",
    ],
    "instrument_id": "XUSE:CASH:UTI1USD",
    "issuer_effective_date": "2000-10-03",
    "ex_date": "2000-10-03 04:00:00+04:00",
    "issuer_ratio": 2.0,
    "ratio": 2.0,
    "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
}


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _fetch_source() -> tuple[dict[str, Any], str]:
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    response = httpx.get(SOURCE["url"], timeout=30.0, follow_redirects=True, headers=headers)
    response.raise_for_status()
    HELPERS.verify_source(response.text, SOURCE["required_fragments"])
    return (
        {
            **SOURCE,
            "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
            "required_fragments_verified": SOURCE["required_fragments"],
        },
        dt.datetime.now(dt.UTC).isoformat(),
    )


def build(source: dict[str, Any], *, retrieved_at: str) -> dict[str, Any]:
    context = HELPERS._load_sealed(CONTEXT)
    key = (SOURCE["instrument_id"], SOURCE["ex_date"], float(SOURCE["ratio"]))
    unresolved = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])): row
        for row in context["events"]
    }
    event = unresolved.get(key)
    if event is None:
        raise ValueError("issuer evidence does not bind the UTI1 frozen event")
    if source.get("url") != SOURCE["url"] or float(source["issuer_ratio"]) != 2.0:
        raise ValueError("UTI1 source changed from the sealed specification")
    if event["nearby_action_context"]:
        raise ValueError("UTI1 unexpectedly has companion action context")
    verified = {
        **source,
        "stored_ratio": float(event["stored_ratio"]),
        "ex_date_ms": int(dt.datetime.fromisoformat(SOURCE["ex_date"]).timestamp() * 1000),
        "prior_context_classification": event["context_classification"],
        "market_date_binding": HELPERS._market_date_binding("UTI1", SOURCE),
        "authorization": "BYPASS_PRICE_GAP_HEURISTIC_FOR_THIS_EXACT_EVENT_ONLY",
    }
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-resolution-batch.v9",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "ONE_EXACT_ISSUER_SHARE_MUTATION_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": [verified],
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": HELPERS._sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": "Merge only the exact UTI1 instrument/date/stored-ratio tuple.",
        "claim_boundary": (
            "This seal verifies only UTI1's plain two-for-one split. It does not open returns, "
            "authorize another event, or pass the global split gate."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    source, retrieved_at = _fetch_source()
    payload = build(source, retrieved_at=retrieved_at)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
