#!/usr/bin/env python3
"""Seal the exact ETS1 reverse split without opening returns."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CONTEXT: Final[Path] = REPO / "artifacts/audit/unresolved_split_event_context.json"
PRICE: Final[Path] = (
    REPO
    / "data/corrections/corporate_action_basis_48fcfde04e3c_materialized_v1"
    / "data/lake_sharadar/ohlcv_1d/instrument_id=XUSE:CASH:ETS1USD/year=2005/data.parquet"
)
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v6.json"
SOURCE: Final[dict[str, Any]] = {
    "ticker": "ETS1",
    "url": (
        "https://www.sec.gov/Archives/edgar/data/846909/"
        "000095013505006345/b57408ene10vq.htm"
    ),
    "required_fragments": [
        "the Company's Board of Directors approved a 1-for-8 reverse stock split",
        "of the Company's outstanding shares of common stock",
        "the reverse stock split became effective on October 28, 2005",
        "issued shares were reverse split on a 1 for 8 basis",
    ],
    "instrument_id": "XUSE:CASH:ETS1USD",
    "issuer_effective_date": "2005-10-28",
    "ex_date": "2005-10-31 04:00:00+04:00",
    "issuer_ratio": 0.125,
    "ratio": 0.125,
    "event_semantics": "REVERSE_SPLIT_AT_FIRST_FROZEN_BAR_AFTER_LEGAL_EFFECTIVE_DATE",
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
        str.maketrans(
            {"\u2010": "-", "\u2011": "-", "\u2013": "-", "\u2014": "-", "\u2019": "'"}
        )
    ).replace("-", " ")
    missing = [
        fragment
        for fragment in fragments
        if " ".join(fragment.lower().replace("-", " ").split()) not in normalized
    ]
    if missing:
        raise ValueError(f"issuer source is missing required fragments: {missing}")


def _fetch_source() -> tuple[dict[str, Any], str]:
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        response = client.get(SOURCE["url"])
        response.raise_for_status()
        verify_source(response.text, SOURCE["required_fragments"])
    return (
        {
            **SOURCE,
            "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
            "required_fragments_verified": SOURCE["required_fragments"],
        },
        dt.datetime.now(dt.UTC).isoformat(),
    )


def _market_date_binding() -> dict[str, Any]:
    frame = pd.read_parquet(PRICE, columns=["ts_open", "close"])
    frame["date"] = pd.to_datetime(frame["ts_open"], unit="ms", utc=True).dt.date
    event_date = dt.date.fromisoformat(str(SOURCE["ex_date"])[:10])
    rows = frame.loc[frame["date"] <= event_date].sort_values("ts_open")
    if len(rows) < 2 or rows.iloc[-1]["date"] != event_date:
        raise ValueError("missing ETS1 event-date frozen price boundary")
    previous, current = rows.iloc[-2], rows.iloc[-1]
    if previous["date"].isoformat() != SOURCE["issuer_effective_date"]:
        raise ValueError("ETS1 issuer effective date is not the final pre-event frozen bar")
    return {
        "binding": "EVENT_DATE_IS_FIRST_FROZEN_PRICE_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
        "prior_date": previous["date"].isoformat(),
        "prior_close": float(previous["close"]),
        "event_date": current["date"].isoformat(),
        "event_close": float(current["close"]),
        "price_partition_path": str(PRICE.relative_to(REPO)),
        "price_partition_sha256": _sha256(PRICE),
    }


def build(source: dict[str, Any], *, retrieved_at: str) -> dict[str, Any]:
    context = _load_sealed(CONTEXT)
    if float(source["issuer_ratio"]) != float(SOURCE["issuer_ratio"]):
        raise ValueError("ETS1 issuer ratio does not match the sealed source specification")
    key = (SOURCE["instrument_id"], SOURCE["ex_date"], float(SOURCE["ratio"]))
    matches = [
        row
        for row in context["events"]
        if (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])) == key
    ]
    if len(matches) != 1:
        raise ValueError("ETS1 evidence does not bind exactly one frozen unresolved event")
    event = matches[0]
    if event["lifecycle_classification"] != "WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION":
        raise ValueError("ETS1 row is no longer an in-lifecycle unresolved event")
    if float(source["issuer_ratio"]) != float(event["stored_ratio"]):
        raise ValueError("ETS1 issuer ratio does not match the frozen stored ratio")
    if event["nearby_action_context"]:
        raise ValueError("ETS1 event unexpectedly has companion action context")
    verified = {
        **source,
        "stored_ratio": float(event["stored_ratio"]),
        "ex_date_ms": int(dt.datetime.fromisoformat(SOURCE["ex_date"]).timestamp() * 1000),
        "prior_context_classification": event["context_classification"],
        "market_date_binding": _market_date_binding(),
        "authorization": "BYPASS_PRICE_GAP_HEURISTIC_FOR_THIS_EXACT_EVENT_ONLY",
    }
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-resolution-batch.v6",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "ETS1_EXACT_REVERSE_SPLIT_ISSUER_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": [verified],
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": _sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Merge only this exact instrument/date/stored-ratio tuple into the fail-closed policy."
        ),
        "claim_boundary": (
            "This seal verifies one 1-for-8 reverse split and its first frozen post-effective-date "
            "bar. It does not open returns, authorize another event, or pass the global split gate."
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
