#!/usr/bin/env python3
"""Seal issuer evidence for non-executable bankruptcy/relisting lifecycle breaks."""

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
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_lifecycle_discontinuity_resolution.json"


def _source(role: str, url: str, *fragments: str) -> dict[str, Any]:
    return {"role": role, "url": url, "required_fragments": list(fragments)}


EVENTS: Final[dict[str, dict[str, Any]]] = {
    "BASXQ": {
        "instrument_id": "XUSE:CASH:BASXQUSD",
        "ex_date": "2016-12-27 04:00:00+04:00",
        "issuer_effective_date": "2016-12-23",
        "stored_ratio": 0.00175,
        "event_semantics": "BANKRUPTCY_OLD_EQUITY_CANCELLATION_AND_NEW_EQUITY_RELISTING",
        "sources": [
            _source(
                "OLD_EQUITY_CANCELLATION_AND_EMERGENCE",
                "https://www.sec.gov/Archives/edgar/data/1109189/000110918916000402/basic-form8xkforemergence.htm",
                "On December 23, 2016 (the “Effective Date”)",
                "the Debtors emerged from their Chapter 11 Cases",
                (
                    "the “Old Common Shares”), and any rights of any holder in respect thereof, "
                    "were deemed cancelled, discharged and of no force or effect"
                ),
            ),
            _source(
                "NEW_EQUITY_FIRST_TRADING_DATE_AND_CUSIP",
                "https://www.sec.gov/Archives/edgar/data/1109189/000110918916000402/exh992201623pressrelease.htm",
                "new common stock (CUSIP number 06985P 209)",
                "same as the symbol for existing shares",
                (
                    "Trading in the New Common Shares on the NYSE is expected to commence on "
                    "Tuesday, December 27, 2016"
                ),
            ),
        ],
    },
    "TDW": {
        "instrument_id": "XUSE:CASH:TDWUSD",
        "ex_date": "2017-08-01 04:00:00+04:00",
        "issuer_effective_date": "2017-07-31",
        "stored_ratio": 0.031,
        "event_semantics": "BANKRUPTCY_OLD_EQUITY_CANCELLATION_AND_WARRANT_DISTRIBUTION",
        "sources": [
            _source(
                "OLD_EQUITY_CANCELLATION_AND_WARRANT_DISTRIBUTION",
                "https://www.sec.gov/Archives/edgar/data/98222/000119312517242513/d431632d8k.htm",
                "On July 31, 2017 (the “Effective Date”)",
                "outstanding shares of the Old Common Stock",
                "were deemed cancelled, discharged and of no further force or effect",
                "Series A Warrants” and the “Series B Warrants",
                "on a pro rata basis to all pre-emergence holders",
            ),
            _source(
                "NEW_EQUITY_FIRST_TRADING_DATE_AND_CUSIP",
                "https://www.sec.gov/Archives/edgar/data/98222/000119312517242513/d431632dex992.htm",
                "new common stock (CUSIP number 88642R 109)",
                "same NYSE ticker symbol “TDW”",
                (
                    "Trading in the New Common Stock on the NYSE is expected to commence on "
                    "Tuesday, August 1, 2017"
                ),
            ),
        ],
    },
    "CIVI": {
        "instrument_id": "XUSE:CASH:CIVIUSD",
        "ex_date": "2017-05-01 04:00:00+04:00",
        "issuer_effective_date": "2017-04-28",
        "stored_ratio": 0.00896,
        "event_semantics": "BANKRUPTCY_OLD_EQUITY_CANCELLATION_AND_WARRANT_DISTRIBUTION",
        "sources": [
            _source(
                "OLD_EQUITY_CANCELLATION_AND_WARRANT_DISTRIBUTION",
                "https://www.sec.gov/Archives/edgar/data/1509589/000095010317004047/dp75602_8k.htm",
                "On April 28, 2017 (the “Effective Date”)",
                "each share of the Company's common stock outstanding prior to the Effective Date",
                "was cancelled",
                "issuance of up to an aggregate of 1,650,510 warrants",
                "to former holders of Existing Equity Interests",
            ),
        ],
    },
    "KEGX": {
        "instrument_id": "XUSE:CASH:KEGXUSD",
        "ex_date": "2016-12-16 04:00:00+04:00",
        "issuer_effective_date": "2016-12-15",
        "stored_ratio": 0.005,
        "event_semantics": "BANKRUPTCY_OLD_EQUITY_CANCELLATION_NEW_SHARES_AND_WARRANTS",
        "sources": [
            _source(
                "OLD_EQUITY_CANCELLATION_AND_WARRANT_DISTRIBUTION",
                "https://www.sec.gov/Archives/edgar/data/318996/000119312516794624/d313262d8k.htm",
                "all previously issued and outstanding shares",
                "Pre-Effective Date Common Stock were cancelled",
                "issued two series of warrants to the former holders",
            ),
            _source(
                "NEW_EQUITY_ALLOCATION_AND_FIRST_TRADING_DATE",
                "https://www.sec.gov/Archives/edgar/data/318996/000119312516794624/d313262dex991.htm",
                "New Shares Issued to Equity Holders",
                "1,338,266",
                "trading in its common stock is expected to commence on December 16, 2016",
            ),
        ],
    },
    "EGLE2": {
        "instrument_id": "XUSE:CASH:EGLE2USD",
        "ex_date": "2014-10-16 04:00:00+04:00",
        "issuer_effective_date": "2014-10-15",
        "stored_ratio": 0.005,
        "event_semantics": "BANKRUPTCY_AGGREGATE_OWNERSHIP_ALLOCATION_AND_WARRANT_DISTRIBUTION",
        "sources": [
            _source(
                "OLD_EQUITY_CANCELLATION_AGGREGATE_ALLOCATION_AND_WARRANTS",
                "https://www.sec.gov/Archives/edgar/data/1322439/000143774914018448/egle20141015_8k.htm",
                "On October 15, 2014 (the “Effective Date”)",
                "cancellation of all outstanding Equity Interests",
                "receiving (i) shares of New Eagle Common Stock equal to 0.5%",
                "an aggregate of 3,040,540 New Eagle Equity Warrants",
            ),
        ],
    },
    "CQB": {
        "instrument_id": "XUSE:CASH:CQBUSD",
        "ex_date": "2002-03-20 04:00:00+04:00",
        "issuer_effective_date": "2002-03-19",
        "stored_ratio": 0.071,
        "event_semantics": "BANKRUPTCY_OLD_SECURITIES_EXCHANGED_FOR_NEW_EQUITY_AND_WARRANTS",
        "sources": [
            _source(
                "OLD_SECURITIES_EXCHANGE_NEW_EQUITY_AND_WARRANTS",
                "https://www.sec.gov/Archives/edgar/data/101063/000102140802003831/d10k.txt",
                (
                    "On March 19, 2002, CBII completed its previously announced financial "
                    "restructuring"
                ),
                "became effective March 19, 2002",
                (
                    "Previously outstanding preferred, preference and common stock is being "
                    "exchanged for 2% of the New Common Stock"
                ),
                "7-year warrants",
                (
                    "trading in such shares on the New York Stock Exchange will not commence "
                    "until March 20, 2002"
                ),
            ),
        ],
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
    evidence: list[dict[str, Any]] = []
    headers = {"User-Agent": "AlphaC research audit contact@canlicapital.com"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for ticker, event in EVENTS.items():
            for source in event["sources"]:
                response = client.get(source["url"])
                response.raise_for_status()
                verify_source(response.text, source["required_fragments"])
                evidence.append(
                    {
                        "ticker": ticker,
                        **source,
                        "retrieved_sha256": hashlib.sha256(response.content).hexdigest(),
                        "required_fragments_verified": source["required_fragments"],
                    }
                )
    return evidence, dt.datetime.now(dt.UTC).isoformat()


def _market_boundary(event: dict[str, Any]) -> dict[str, Any]:
    year = str(event["ex_date"])[:4]
    path = PRICE_ROOT / f"instrument_id={event['instrument_id']}" / f"year={year}/data.parquet"
    frame = pd.read_parquet(path, columns=["ts_open", "close"])
    frame["date"] = pd.to_datetime(frame["ts_open"], unit="ms", utc=True).dt.date
    ex_date = dt.date.fromisoformat(str(event["ex_date"])[:10])
    rows = frame.loc[frame["date"] <= ex_date].sort_values("ts_open")
    if len(rows) < 2 or rows.iloc[-1]["date"] != ex_date:
        raise ValueError(f"missing frozen event-date market boundary: {event['instrument_id']}")
    previous = rows.iloc[-2]
    effective_date = dt.date.fromisoformat(event["issuer_effective_date"])
    if previous["date"] != effective_date:
        raise ValueError(f"issuer effective date is not the final pre-event bar: {event['ticker']}")
    current = rows.iloc[-1]
    return {
        "binding": "EVENT_DATE_IS_FIRST_FROZEN_PRICE_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
        "prior_date": previous["date"].isoformat(),
        "prior_close": float(previous["close"]),
        "event_date": current["date"].isoformat(),
        "event_close": float(current["close"]),
        "price_partition_path": str(path.relative_to(REPO)),
        "price_partition_sha256": _sha256(path),
    }


def build(evidence: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    context = _load_sealed(CONTEXT)
    unresolved = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])): row
        for row in context["events"]
    }
    evidence_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in evidence:
        evidence_by_ticker.setdefault(row["ticker"], []).append(row)

    resolutions: list[dict[str, Any]] = []
    for ticker, specification in EVENTS.items():
        key = (
            specification["instrument_id"],
            specification["ex_date"],
            float(specification["stored_ratio"]),
        )
        event = unresolved.get(key)
        if event is None:
            raise ValueError(f"issuer evidence does not bind an unresolved frozen event: {key}")
        if event["lifecycle_classification"] != "WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION":
            raise ValueError(f"{ticker} row is no longer an in-lifecycle unresolved event")
        observed_roles = {row["role"] for row in evidence_by_ticker.get(ticker, [])}
        expected_roles = {row["role"] for row in specification["sources"]}
        if observed_roles != expected_roles:
            raise ValueError(f"all issuer-evidence roles are required for {ticker}")
        resolutions.append(
            {
                "ticker": ticker,
                **{key: value for key, value in specification.items() if key != "sources"},
                "ex_date_ms": int(
                    dt.datetime.fromisoformat(specification["ex_date"]).timestamp() * 1000
                ),
                "stored_ratio_semantics": (
                    "NOT_A_COMPLETE_OR_SUPPORTED_OLD_TO_NEW_SHAREHOLDER_CONVERSION"
                ),
                "execution_authorized": False,
                "governance_route": (
                    "NON_EXECUTABLE_ISSUER_VERIFIED_LIFECYCLE_DISCONTINUITY"
                ),
                "source_row_deleted": False,
                "ratio_repair_authorized": False,
                "prior_context_classification": event["context_classification"],
                "market_date_binding": _market_boundary({"ticker": ticker, **specification}),
                "issuer_evidence": evidence_by_ticker[ticker],
            }
        )

    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-lifecycle-discontinuity-resolution.v2",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "SIX_SPLIT_LIKE_ROWS_RESOLVED_AS_NONEXECUTABLE_LIFECYCLE_BREAKS",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "resolved_events": resolutions,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": _sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Route these exact rows as non-executable lifecycle discontinuities. Any simulated "
            "position crossing an old-equity cancellation must abort; no stored ratio in this "
            "seal may be applied as a complete share conversion."
        ),
        "claim_boundary": (
            "The issuer filings and frozen price sequence establish cancellation/restructuring "
            "boundaries involving new equity, aggregate allocations, and/or warrants. They do "
            "not validate the stored values as complete shareholder conversions, repair prices, "
            "authorize execution, or validate returns."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    evidence, retrieved_at = _fetch_sources()
    payload = build(evidence, retrieved_at=retrieved_at)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
