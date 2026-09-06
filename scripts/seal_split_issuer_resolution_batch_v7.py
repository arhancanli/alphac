#!/usr/bin/env python3
"""Seal six exact issuer share mutations without opening returns."""

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
PRICE_ROOT: Final[Path] = (
    REPO
    / "data/corrections/corporate_action_basis_48fcfde04e3c_materialized_v1"
    / "data/lake_sharadar/ohlcv_1d"
)
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v7.json"
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "BNI": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/934612/"
            "000093461298000017/0000934612-98-000017.txt"
        ),
        "required_fragments": [
            "approved a three-for-one common stock split",
            "a stock dividend of two additional shares of BNSF common stock",
            "payable for each share outstanding or held in treasury on September 1, 1998",
        ],
        "instrument_id": "XUSE:CASH:BNIUSD",
        "issuer_distribution_date": "1998-09-01",
        "ex_date": "1998-09-02 04:00:00+04:00",
        "issuer_ratio": 3.0,
        "ratio": 3.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "EPAC": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/6955/"
            "000095013198002327/0000950131-98-002327.txt"
        ),
        "required_fragments": [
            "authorized a two-for-one stock split",
            "a 100 percent stock dividend",
            "shares of the Company's common stock were issued on February 3, 1998",
        ],
        "instrument_id": "XUSE:CASH:EPACUSD",
        "issuer_effective_date": "1998-02-03",
        "ex_date": "1998-02-03 04:00:00+04:00",
        "issuer_ratio": 2.0,
        "ratio": 2.0,
        "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
    },
    "GDW": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/42293/"
            "000004229300000009/0000042293-00-000009.txt"
        ),
        "required_fragments": [
            "a three-for-one split of its outstanding Common Stock",
            "in the form of a 200% stock dividend",
            "This dividend was payable December 10, 1999",
        ],
        "instrument_id": "XUSE:CASH:GDWUSD",
        "issuer_distribution_date": "1999-12-10",
        "ex_date": "1999-12-13 04:00:00+04:00",
        "issuer_ratio": 3.0,
        "ratio": 3.0,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "HAFC": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1109242/"
            "000091205701539508/a2062901z10-q.htm"
        ),
        "required_fragments": [
            "the Company announced a three-for-two stock split",
            "one additional share of Hanmi Financial common stock for every two shares",
            "Distribution of additional shares issued as a result of the split occurred on "
            "September 21, 2001",
        ],
        "instrument_id": "XUSE:CASH:HAFCUSD",
        "issuer_distribution_date": "2001-09-21",
        "ex_date": "2001-09-24 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "JAKK": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1009829/"
            "000095014899002339/0000950148-99-002339.txt"
        ),
        "required_fragments": [
            "On November 4, 1999, we will distribute",
            "a dividend of 1/2 share of our common stock for each share",
            "cash will be paid in lieu of fractional shares",
        ],
        "instrument_id": "XUSE:CASH:JAKKUSD",
        "issuer_distribution_date": "1999-11-04",
        "ex_date": "1999-11-05 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE",
    },
    "LNG": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/3570/"
            "000119312504049308/d10k.htm"
        ),
        "required_fragments": [
            "our stockholders approved a one-for-four reverse stock split",
            "The reverse stock split became effective on October 18, 2000",
            "reduced our issued and outstanding shares from 43,989,572 shares to 10,997,393",
        ],
        "instrument_id": "XUSE:CASH:LNGUSD",
        "issuer_effective_date": "2000-10-18",
        "ex_date": "2000-10-18 04:00:00+04:00",
        "issuer_ratio": 0.25,
        "ratio": 0.25,
        "date_binding": "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE",
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


def _fetch_sources() -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for ticker, specification in SOURCES.items():
            response = client.get(specification["url"])
            response.raise_for_status()
            verify_source(response.text, specification["required_fragments"])
            rows.append(
                {
                    "ticker": ticker,
                    **specification,
                    "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
                    "required_fragments_verified": specification["required_fragments"],
                }
            )
    return rows, dt.datetime.now(dt.UTC).isoformat()


def _market_date_binding(ticker: str, specification: dict[str, Any]) -> dict[str, Any]:
    year = str(specification["ex_date"])[:4]
    path = (
        PRICE_ROOT
        / f"instrument_id={specification['instrument_id']}"
        / f"year={year}/data.parquet"
    )
    frame = pd.read_parquet(path, columns=["ts_open", "close"])
    frame["date"] = pd.to_datetime(frame["ts_open"], unit="ms", utc=True).dt.date
    event_date = dt.date.fromisoformat(str(specification["ex_date"])[:10])
    rows = frame.loc[frame["date"] <= event_date].sort_values("ts_open")
    if len(rows) < 2 or rows.iloc[-1]["date"] != event_date:
        raise ValueError(f"missing frozen event-date market boundary: {ticker}")
    previous, current = rows.iloc[-2], rows.iloc[-1]
    binding = specification["date_binding"]
    if (
        binding == "FIRST_FROZEN_BAR_AFTER_ISSUER_DISTRIBUTION_DATE"
        and previous["date"].isoformat() != specification["issuer_distribution_date"]
    ):
        raise ValueError(f"issuer distribution date is not the final pre-event bar: {ticker}")
    if (
        binding == "ISSUER_EFFECTIVE_DATE_EQUALS_FROZEN_EVENT_DATE"
        and current["date"].isoformat() != specification["issuer_effective_date"]
    ):
        raise ValueError(f"issuer effective date does not equal frozen event date: {ticker}")
    return {
        "binding": binding,
        "prior_date": previous["date"].isoformat(),
        "prior_close": float(previous["close"]),
        "event_date": current["date"].isoformat(),
        "event_close": float(current["close"]),
        "price_partition_path": str(path.relative_to(REPO)),
        "price_partition_sha256": _sha256(path),
    }


def build(sources: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    context = _load_sealed(CONTEXT)
    unresolved = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])): row
        for row in context["events"]
    }
    provided = {row["ticker"]: row for row in sources}
    if set(provided) != set(SOURCES):
        raise ValueError("exactly the six sealed issuer sources are required")
    verified: list[dict[str, Any]] = []
    for ticker, specification in SOURCES.items():
        source = provided[ticker]
        key = (
            specification["instrument_id"],
            specification["ex_date"],
            float(specification["ratio"]),
        )
        event = unresolved.get(key)
        if event is None:
            raise ValueError(f"issuer evidence does not bind an unresolved frozen event: {key}")
        if float(source["issuer_ratio"]) != float(specification["issuer_ratio"]):
            raise ValueError(f"{ticker} issuer ratio changed from sealed specification")
        if event["nearby_action_context"]:
            raise ValueError(f"{ticker} unexpectedly has companion action context")
        verified.append(
            {
                **source,
                "stored_ratio": float(event["stored_ratio"]),
                "ex_date_ms": int(
                    dt.datetime.fromisoformat(specification["ex_date"]).timestamp() * 1000
                ),
                "prior_context_classification": event["context_classification"],
                "market_date_binding": _market_date_binding(ticker, specification),
                "authorization": "BYPASS_PRICE_GAP_HEURISTIC_FOR_THIS_EXACT_EVENT_ONLY",
            }
        )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-resolution-batch.v7",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "SIX_EXACT_ISSUER_SHARE_MUTATIONS_VERIFIED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "verified_events": verified,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": _sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Merge only these six exact instrument/date/stored-ratio tuples into the fail-closed "
            "policy."
        ),
        "claim_boundary": (
            "This seal verifies six plain splits at their issuer-bound frozen bars: BNI, EPAC, "
            "GDW, HAFC, JAKK, and LNG. It does not open returns, authorize another event, or pass "
            "the global split gate."
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
