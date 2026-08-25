#!/usr/bin/env python3
"""Verify twelve composite share mutations while keeping incomplete replay closed."""

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
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_resolution_batch_v4.json"
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "ATNI": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/879585/"
            "000095013098001580/0000950130-98-001580.txt"
        ),
        "required_fragments": [
            "On December 30, 1997, the Company was split into two separate public companies",
            "Emerging Communications, Inc.",
            "received one share of ECI Common Stock and 0.4 shares of Company Common Stock",
        ],
        "instrument_id": "XUSE:CASH:ATNIUSD",
        "issuer_effective_date": "1997-12-30",
        "ex_date": "1997-12-31 04:00:00+04:00",
        "issuer_ratio": 0.4,
        "ratio": 0.4,
        "event_semantics": "SPLIT_OFF_WITH_COMPANION_ECI_SECURITY_ENTITLEMENT",
        "date_binding": "ISSUER_EFFECTIVE_DATE_PRECEDES_EVENT_WITHOUT_PRE_EVENT_BAR",
    },
    "CMO": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/766701/"
            "000095013401503792/d88804e8-k.txt"
        ),
        "required_fragments": [
            "a special dividend of $7.30 per common share",
            "the close of business on June 29, 2001, as the effective date of the reverse split",
            "the first day the common shares traded post-split was July 2, 2001",
            "coincided with the first day that the common shares began trading ex-special dividend",
        ],
        "instrument_id": "XUSE:CASH:CMOUSD",
        "issuer_effective_date": "2001-06-29",
        "ex_date": "2001-07-02 04:00:00+04:00",
        "issuer_ratio": 0.5,
        "ratio": 0.5,
        "event_semantics": "REVERSE_SPLIT_WITH_COMPANION_SPECIAL_CASH_DIVIDEND",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "ITT": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/216228/"
            "000095012311095346/y93291e8vk.htm"
        ),
        "required_fragments": [
            "completed the previously announced spin-off of Exelis Inc.",
            "one-for-two reverse stock split of ITT common stock",
            "would be effective after market close that day",
        ],
        "instrument_id": "XUSE:CASH:ITTUSD",
        "issuer_effective_date": "2011-10-31",
        "ex_date": "2011-11-01 04:00:00+04:00",
        "issuer_ratio": 0.5,
        "ratio": 0.5,
        "event_semantics": "POST_SPINOFF_REVERSE_SPLIT_AT_FIRST_POST_EFFECTIVE_BAR",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "SBRA": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1492298/"
            "000119312510261436/d8k.htm"
        ),
        "required_fragments": [
            "On November 15, 2010, Sun Healthcare Group, Inc.",
            "REIT Conversion Merger",
            "each stockholder of Old Sun receiving one share of common stock of Sabra",
            "for every three shares of common stock of Old Sun",
        ],
        "instrument_id": "XUSE:CASH:SBRAUSD",
        "issuer_effective_date": "2010-11-15",
        "ex_date": "2010-11-16 04:00:00+04:00",
        "issuer_ratio": 1 / 3,
        "ratio": 0.33333,
        "event_semantics": "POST_SPINOFF_REIT_CONVERSION_AT_FIRST_POST_EFFECTIVE_BAR",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "NRF": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1273801/"
            "000127380114000061/nrf0630201410-q.htm"
        ),
        "required_fragments": [
            "one-for-two reverse stock split completed on June 30, 2014",
            "every two shares of our issued and outstanding common stock",
            "were combined into one issued and outstanding share of our common stock",
        ],
        "instrument_id": "XUSE:CASH:NRFUSD",
        "issuer_effective_date": "2014-06-30",
        "ex_date": "2014-06-30 04:00:00+04:00",
        "issuer_ratio": 0.5,
        "ratio": 0.5,
        "event_semantics": "SPINOFF_LINKED_REVERSE_SPLIT_ON_ISSUER_COMPLETION_DATE",
        "date_binding": "ISSUER_COMPLETION_DATE_EQUALS_FROZEN_EVENT_DATE",
    },
    "IHG": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/858446/"
            "000115697305000999/u49002e6vk.htm"
        ),
        "required_fragments": [
            "The Scheme, which was approved by shareholders on 1 June 2005, became effective",
            "shareholders receive 11 New IHG ordinary shares for every 15 ordinary shares",
            "£1.65 in cash for every ordinary share held",
            "New IHG American depositary shares will be listed and trading will commence",
        ],
        "instrument_id": "XUSE:CASH:IHGUSD",
        "issuer_effective_date": "2005-06-27",
        "ex_date": "2005-06-28 04:00:00+04:00",
        "issuer_ratio": 11 / 15,
        "ratio": 0.73333,
        "event_semantics": "SCHEME_SHARE_EXCHANGE_WITH_COMPANION_CASH_CONSIDERATION",
        "date_binding": "ISSUER_DATE_MISMATCH_COMPOSITE_ACTION",
    },
    "KMI1": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/54502/"
            "000095013499001524/0000950134-99-001524.txt"
        ),
        "required_fragments": [
            "a three-for-two split of the Company's common stock",
            "The stock split was distributed and the increase in dividend was paid concurrently",
            "on December 31, 1998",
        ],
        "instrument_id": "XUSE:CASH:KMI1USD",
        "issuer_effective_date": "1998-12-31",
        "ex_date": "1999-01-04 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "ratio": 1.5,
        "event_semantics": "STOCK_SPLIT_WITH_CONCURRENT_CASH_DIVIDEND_MISSING_FROM_FROZEN_ACTIONS",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "KSU": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/54480/"
            "000005448000000020/0000054480-00-000020.txt"
        ),
        "required_fragments": [
            (
                "Each holder of record of KCSI Common Stock received two shares of common stock "
                "of Stilwell"
            ),
            "KCSI effected the Distribution on July 12, 2000",
            "to effect a one for two reverse stock split",
        ],
        "instrument_id": "XUSE:CASH:KSUUSD",
        "issuer_effective_date": "2000-07-12",
        "ex_date": "2000-07-13 04:00:00+04:00",
        "issuer_ratio": 0.5,
        "ratio": 0.5,
        "event_semantics": "REVERSE_SPLIT_WITH_COMPANION_STILWELL_SECURITY_ENTITLEMENT",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "TYC": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/833444/"
            "000110465907052190/a07-17393_3ex99d1.htm"
        ),
        "required_fragments": [
            (
                "Immediately following the distribution of the common shares of "
                "Tyco Electronics and Covidien"
            ),
            "every four common shares of Tyco International were converted into one common share",
            "one-for-four reverse stock split",
            "closing share prices quoted on the New York Stock Exchange on July 2, 2007",
        ],
        "instrument_id": "XUSE:CASH:TYCUSD",
        "issuer_effective_date": "2007-07-02",
        "ex_date": "2007-07-02 04:00:00+04:00",
        "issuer_ratio": 0.25,
        "ratio": 0.25,
        "event_semantics": "POST_DISTRIBUTION_REVERSE_SPLIT_WITH_TWO_SPINOFF_ENTITLEMENTS",
        "date_binding": "FROZEN_EVENT_DATE_BOUND_TO_SAME_DAY_SPINOFF_CONTEXT_NOT_EXECUTION",
    },
    "T1": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/5907/"
            "000095012303003510/e84804e10vk.txt"
        ),
        "required_fragments": [
            "On November 18, 2002, AT&T completed the spin-off of AT&T Broadband",
            "Each AT&T shareowner received a distribution of 0.3235 of a share",
            "one-for-five reverse stock split of AT&T common stock",
            "was effected on November 18, 2002 immediately after the completion of the spin-off",
        ],
        "instrument_id": "XUSE:CASH:T1USD",
        "issuer_effective_date": "2002-11-18",
        "ex_date": "2002-11-19 04:00:00+04:00",
        "issuer_ratio": 0.2,
        "ratio": 0.2,
        "event_semantics": "POST_BROADBAND_SPINOFF_REVERSE_SPLIT_WITH_COMCAST_ENTITLEMENT",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "RBAK": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1081290/"
            "000119312504042090/d10k.htm"
        ),
        "required_fragments": [
            (
                "the issuance of warrants exercisable for the Company's common stock to the "
                "Company's stockholders"
            ),
            "an approximate 73.39:1 reverse stock split",
            "holders of the Convertible Notes received an aggregate of 47,500,000 shares",
            "January 2, 2004 the Company emerged from bankruptcy",
        ],
        "instrument_id": "XUSE:CASH:RBAKUSD",
        "issuer_effective_date": "2004-01-02",
        "ex_date": "2004-01-05 04:00:00+04:00",
        "issuer_ratio": 1 / 73.39,
        "ratio": 0.01363,
        "event_semantics": "BANKRUPTCY_REVERSE_SPLIT_WITH_CREDITOR_EQUITY_AND_STOCKHOLDER_WARRANTS",
        "date_binding": "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE",
    },
    "SDH1": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1048286/"
            "000092838598000674/0000928385-98-000674.txt"
        ),
        "required_fragments": [
            "On March 27, 1998, Marriott International, Inc.",
            "received one share of MAR Common Stock and one share of MAR-A Common Stock",
            "Immediately following the Distribution, shares of Old Marriott common stock "
            "underwent a one-for-four reverse stock split",
            "25 shares of Sodexho Marriott Services, Inc. common stock",
        ],
        "instrument_id": "XUSE:CASH:SDH1USD",
        "issuer_effective_date": "1998-03-27",
        "ex_date": "1998-03-23 04:00:00+04:00",
        "issuer_ratio": 0.25,
        "ratio": 0.25,
        "event_semantics": "SPINOFF_AND_MERGER_REVERSE_SPLIT_WITH_TWO_NEW_MARRIOTT_CLASSES",
        "date_binding": "ISSUER_DATE_MISMATCH_COMPOSITE_ACTION",
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
            {
                "\u2010": "-",
                "\u2011": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2019": "'",
            }
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
    paths = [path]
    prior_path = path.parent.parent / f"year={int(year) - 1}/data.parquet"
    if prior_path.exists():
        paths.insert(0, prior_path)
    frame = pd.concat(
        [pd.read_parquet(candidate, columns=["ts_open", "close"]) for candidate in paths],
        ignore_index=True,
    )
    frame["date"] = pd.to_datetime(frame["ts_open"], unit="ms", utc=True).dt.date
    event_date = dt.date.fromisoformat(str(specification["ex_date"])[:10])
    rows = frame.loc[frame["date"] <= event_date].sort_values("ts_open")
    if rows.empty or rows.iloc[-1]["date"] != event_date:
        raise ValueError(f"missing frozen event-date market boundary: {ticker}")
    if (
        len(rows) < 2
        and specification["date_binding"]
        == "ISSUER_EFFECTIVE_DATE_PRECEDES_EVENT_WITHOUT_PRE_EVENT_BAR"
    ):
        current = rows.iloc[-1]
        return {
            "binding": specification["date_binding"],
            "prior_date": None,
            "prior_close": None,
            "event_date": current["date"].isoformat(),
            "event_close": float(current["close"]),
            "price_partition_path": str(path.relative_to(REPO)),
            "price_partition_sha256": _sha256(path),
            "prior_price_partition_path": (
                str(prior_path.relative_to(REPO)) if prior_path.exists() else None
            ),
            "prior_price_partition_sha256": (
                _sha256(prior_path) if prior_path.exists() else None
            ),
        }
    if len(rows) < 2:
        raise ValueError(f"missing frozen pre-event market boundary: {ticker}")
    previous, current = rows.iloc[-2], rows.iloc[-1]
    effective_date = dt.date.fromisoformat(specification["issuer_effective_date"])
    if specification["date_binding"] == "FIRST_FROZEN_BAR_AFTER_ISSUER_EFFECTIVE_DATE":
        if previous["date"] != effective_date:
            raise ValueError(f"issuer effective date is not the final pre-event bar: {ticker}")
    elif (
        specification["date_binding"] == "ISSUER_COMPLETION_DATE_EQUALS_FROZEN_EVENT_DATE"
        and current["date"] != effective_date
    ):
        raise ValueError(f"issuer completion date does not equal event date: {ticker}")
    return {
        "binding": specification["date_binding"],
        "prior_date": previous["date"].isoformat(),
        "prior_close": float(previous["close"]),
        "event_date": current["date"].isoformat(),
        "event_close": float(current["close"]),
        "price_partition_path": str(path.relative_to(REPO)),
        "price_partition_sha256": _sha256(path),
        "prior_price_partition_path": (
            str(prior_path.relative_to(REPO)) if prior_path.exists() else None
        ),
        "prior_price_partition_sha256": _sha256(prior_path) if prior_path.exists() else None,
    }


def build(sources: list[dict[str, Any]], *, retrieved_at: str) -> dict[str, Any]:
    context = _load_sealed(CONTEXT)
    unresolved = {
        (row["instrument_id"], row["ex_date"], float(row["stored_ratio"])): row
        for row in context["events"]
    }
    provided = {row["ticker"]: row for row in sources}
    if set(provided) != set(SOURCES):
        raise ValueError("exactly the twelve sealed composite-action sources are required")
    verified: list[dict[str, Any]] = []
    for ticker, specification in SOURCES.items():
        source = provided[ticker]
        if float(source["issuer_ratio"]) != float(specification["issuer_ratio"]):
            raise ValueError(f"{ticker} issuer ratio changed from sealed specification")
        key = (
            specification["instrument_id"],
            specification["ex_date"],
            float(specification["ratio"]),
        )
        event = unresolved.get(key)
        if event is None:
            raise ValueError(f"issuer source does not bind an unresolved frozen event: {key}")
        issuer_ratio = float(source["issuer_ratio"])
        stored_ratio = float(event["stored_ratio"])
        if round(issuer_ratio, 5) != stored_ratio:
            raise ValueError(f"{ticker} issuer ratio does not match frozen precision")
        verified.append(
            {
                **source,
                "stored_ratio": stored_ratio,
                "ex_date_ms": int(
                    dt.datetime.fromisoformat(specification["ex_date"]).timestamp() * 1000
                ),
                "prior_context_classification": event["context_classification"],
                "market_date_binding": _market_date_binding(ticker, specification),
                "share_mutation_verified": True,
                "execution_authorized": False,
                "governance_route": "HARD_QUARANTINE_ISSUER_VERIFIED_COMPOSITE_ACTION",
                "required_companion_replay": (
                    "COMPANION_CASH_DISTRIBUTION"
                    if ticker in {"CMO", "IHG"}
                    else (
                        "CASH_DIVIDEND_MISSING_FROM_FROZEN_ACTIONS"
                        if ticker == "KMI1"
                        else (
                            "CREDITOR_EQUITY_AND_STOCKHOLDER_WARRANT_ENTITLEMENTS"
                            if ticker == "RBAK"
                            else "SEPARATE_SPINOFF_DISTRIBUTED_SECURITY_ENTITLEMENT"
                        )
                    )
                ),
            }
        )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-resolution-batch.v4",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "TWELVE_COMPOSITE_SHARE_MUTATIONS_VERIFIED_REPLAY_NOT_AUTHORIZED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "resolved_events": verified,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": _sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Route these exact tuples as issuer-verified composite-action quarantines until the "
            "engine can replay each separate distributed-security or cash entitlement."
        ),
        "claim_boundary": (
            "This verifies only the ATNI, CMO, ITT, SBRA, NRF, IHG, KMI1, KSU, TYC, T1, "
            "RBAK, and SDH1 "
            "share-mutation components. "
            "Because the engine does not replay their companion distributed securities, special "
            "dividend, or cash scheme consideration, none is executable. "
            "This does not open returns, validate performance, or pass the global split gate."
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
