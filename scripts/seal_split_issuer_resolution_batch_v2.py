#!/usr/bin/env python3
"""Seal exact issuer evidence for a second batch of quarantined split-like events."""

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
CONTEXT: Final[Path] = REPO / "artifacts/audit/unresolved_split_event_context.json"
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v2.json"
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "AMPE": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1411906/"
            "000155837022018084/ampe-20221117xex99d1.htm"
        ),
        "required_fragments": [
            "fifteen-to-one reverse stock split",
            "became effective November 9, 2022",
            (
                "common stock will commence trading on the NYSE American on Tuesday, "
                "November 22, 2022"
            ),
        ],
        "instrument_id": "XUSE:CASH:AMPEUSD",
        "ex_date": "2022-11-22 04:00:00+04:00",
        "issuer_ratio": 1 / 15,
        "ratio": 0.06667,
        "ratio_binding": "ISSUER_RATIO_ROUNDED_TO_FROZEN_FIVE_DECIMAL_VENDOR_PRECISION",
        "event_semantics": "FIRST_SPLIT_ADJUSTED_TRADING_RESUMPTION",
    },
    "EVHC": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1678531/"
            "000167853117000044/evhc-2016123110k.htm"
        ),
        "required_fragments": [
            (
                "each share of EHH common stock was converted into 0.334 shares of "
                "Company common stock"
            ),
            "On December 2, 2016, shares of the common stock of the Company",
            "began trading on the New York Stock Exchange under the ticker symbol “EVHC”",
        ],
        "instrument_id": "XUSE:CASH:EVHCUSD",
        "ex_date": "2016-12-02 04:00:00+04:00",
        "issuer_ratio": 0.334,
        "ratio": 0.334,
        "ratio_binding": "ISSUER_RATIO_EXACTLY_MATCHES_FROZEN_VENDOR_RATIO",
        "event_semantics": "MERGER_EXCHANGE_CONVERSION_AT_FIRST_NEWCO_TRADING_DATE",
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_sealed(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.pop("content_hash", None)
    actual = _content_hash(payload)
    payload["content_hash"] = declared
    if declared != actual:
        raise ValueError(f"content hash mismatch: {path.relative_to(REPO)}")
    return payload


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
                    **source,
                    "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
                    "required_fragments_verified": source["required_fragments"],
                }
            )
    return rows, dt.datetime.now(dt.UTC).isoformat()


def build(sources: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    context = _load_sealed(CONTEXT)
    unresolved = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])): row
        for row in context["events"]
    }
    verified_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for source in sources:
        key = (source["instrument_id"], source["ex_date"], float(source["ratio"]))
        if key in seen:
            raise ValueError(f"duplicate issuer resolution: {key}")
        seen.add(key)
        event = unresolved.get(key)
        if event is None:
            raise ValueError(f"issuer source does not bind an unresolved frozen event: {key}")
        if event["lifecycle_classification"] != "WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION":
            raise ValueError("issuer source is not an in-lifecycle unresolved event")
        if event["provider_classification"] != "NO_INDEPENDENT_PROVIDER_MATCH":
            raise ValueError("batch is restricted to events without a provider match")

        issuer_ratio = float(source["issuer_ratio"])
        stored_ratio = float(event["stored_ratio"])
        if source["ticker"] == "AMPE":
            if round(issuer_ratio, 5) != stored_ratio:
                raise ValueError("AMPE issuer ratio does not match frozen five-decimal precision")
        elif issuer_ratio != stored_ratio:
            raise ValueError("issuer ratio does not exactly match frozen ratio")

        verified_events.append(
            {
                **source,
                "stored_ratio": stored_ratio,
                "ex_date_ms": int(dt.datetime.fromisoformat(source["ex_date"]).timestamp() * 1000),
                "prior_context_classification": event["context_classification"],
                "authorization": "BYPASS_PRICE_GAP_HEURISTIC_FOR_THIS_EXACT_EVENT_ONLY",
            }
        )

    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-resolution-batch.v2",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "TWO_EXACT_QUARANTINED_EVENTS_ISSUER_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": verified_events,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": _sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Merge only these exact instrument/date/stored-ratio tuples into the global "
            "fail-closed governance policy. Do not infer a broad ratio tolerance or event rule."
        ),
        "claim_boundary": (
            "Issuer evidence resolves only AMPE on its first resumed split-adjusted trading date "
            "and EVHC as a merger exchange conversion on its first Newco trading date. It does "
            "not open returns, authorize another event, validate performance, or pass the global "
            "split gate."
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
