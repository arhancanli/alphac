#!/usr/bin/env python3
"""Seal sixteen issuer conflicts that remain hard quarantined and non-executable."""

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
OUTPUT: Final[Path] = REPO / "artifacts/audit/split_issuer_conflict_resolution_batch_v5.json"
SOURCES: Final[dict[str, dict[str, Any]]] = {
    "AAWW": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1135185/"
            "000093041306005893/c43889_10-q.htm"
        ),
        "required_fragments": [
            "As of June 30, 2006, there were 20,049,108 shares",
            "20,049,108 and 19,815,338 shares outstanding",
        ],
        "instrument_id": "XUSE:CASH:AAWWUSD",
        "issuer_terms_date": "2006-06-30",
        "ex_date": "2006-04-01 04:00:00+04:00",
        "issuer_ratio": 1.0,
        "stored_ratio": 6.0,
        "conflict": "ISSUER_SHARE_COUNTS_CONTRADICT_SIX_FOR_ONE_STORED_MUTATION",
        "issuer_evidence": {
            "pre_event_2005_year_end_shares": 19_815_338,
            "post_event_2006_q2_shares": 20_049_108,
        },
    },
    "ACL": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1167379/"
            "000116737905000020/acl20f2004.htm"
        ),
        "required_fragments": [
            "305,654,454 shares outstanding at December 31, 2004",
            "308,519,051 shares outstanding at December 31, 2003",
        ],
        "instrument_id": "XUSE:CASH:ACLUSD",
        "issuer_terms_date": "2004-12-31",
        "ex_date": "2004-08-30 04:00:00+04:00",
        "issuer_ratio": 1.0,
        "stored_ratio": 0.1,
        "conflict": "ISSUER_SHARE_COUNTS_CONTRADICT_ONE_FOR_TEN_STORED_MUTATION",
        "issuer_evidence": {
            "pre_event_2003_year_end_shares": 308_519_051,
            "post_event_2004_year_end_shares": 305_654_454,
        },
    },
    "CDR": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/761648/"
            "000095012303009594/y88871sv11.htm"
        ),
        "required_fragments": [
            "our 2-for-1 stock split which occurred July 7, 2003",
            "All share and per share information set forth in this prospectus has been adjusted",
        ],
        "instrument_id": "XUSE:CASH:CDRUSD",
        "issuer_event_date": "2003-07-07",
        "ex_date": "2003-07-15 04:00:00+04:00",
        "issuer_ratio": 2.0,
        "stored_ratio": 2.0,
        "conflict": "ISSUER_EVENT_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "DIAL1": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/771950/"
            "000095012309035313/c89015e10vq.htm"
        ),
        "required_fragments": [
            "a two hundred to one (200:1) reverse stock split",
            "was approved and effective on August 3, 2009",
        ],
        "instrument_id": "XUSE:CASH:DIAL1USD",
        "issuer_event_date": "2009-08-03",
        "ex_date": "2009-08-07 04:00:00+04:00",
        "issuer_ratio": 0.005,
        "stored_ratio": 0.005,
        "conflict": "ISSUER_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "GEVA": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/911326/"
            "000119312511294917/d251415d8k.htm"
        ),
        "required_fragments": [
            "filed on November 2, 2011",
            "one-for-five reverse stock split",
            "each five shares of Trimeris common stock",
            "were automatically combined into and became one share",
        ],
        "instrument_id": "XUSE:CASH:GEVAUSD",
        "issuer_event_date": "2011-11-02",
        "ex_date": "2011-11-04 04:00:00+04:00",
        "issuer_ratio": 0.2,
        "stored_ratio": 0.2,
        "conflict": "ISSUER_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "MHGVY": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1578526/"
            "000110465914032214/a14-11076_120f.htm"
        ),
        "required_fragments": [
            "As filed with the Securities and Exchange Commission on April 30, 2014",
            "American Depositary Shares, each representing 1 ordinary share",
            "New York Stock Exchange",
        ],
        "instrument_id": "XUSE:CASH:MHGVYUSD",
        "issuer_terms_date": "2014-04-30",
        "ex_date": "2014-05-01 04:00:00+04:00",
        "issuer_ratio": 1.0,
        "stored_ratio": 0.1,
        "conflict": "ISSUER_ADS_TERMS_CONFLICT_WITH_FROZEN_STORED_RATIO",
    },
    "NVEC": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/724910/"
            "000091205700052325/a2032378z8-k.txt"
        ),
        "required_fragments": [
            "Effective as of November 21, 2000",
            "all outstanding shares of common stock of Premis held as of that date were converted",
            "on a 5:1 basis in a reverse stock-split",
            "each shareholder of Merged NVE received 3.5 shares of stock of the Company",
        ],
        "instrument_id": "XUSE:CASH:NVECUSD",
        "issuer_event_date": "2000-11-20",
        "ex_date": "2000-12-06 04:00:00+04:00",
        "issuer_ratio": 0.2,
        "stored_ratio": 0.2,
        "conflict": "ISSUER_DATE_MISMATCH_AND_COMPOSITE_MERGER_REPLAY_REQUIRED",
    },
    "NCI1": {
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
        "issuer_event_date": "1998-04-01",
        "ex_date": "1998-04-02 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "stored_ratio": 1.5,
        "conflict": "DUPLICATE_FROZEN_EVENT_ONE_DAY_AFTER_ISSUER_EFFECTIVE_EVENT",
    },
    "IPAR": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/822663/"
            "000093041301501460/c22238_10q.txt"
        ),
        "required_fragments": [
            "the Board of Directors authorized a 3 for 2 stock split",
            "in the form of a 50% dividend",
            "payable September 14, 2001",
        ],
        "instrument_id": "XUSE:CASH:IPARUSD",
        "issuer_event_date": "2001-09-14",
        "ex_date": "2001-09-20 04:00:00+04:00",
        "issuer_ratio": 1.5,
        "stored_ratio": 1.5,
        "conflict": "ISSUER_PAYABLE_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "PRTK": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1178711/"
            "000119312509020145/d8k.htm"
        ),
        "required_fragments": [
            "Also on January 30, 2009, in connection with the Merger",
            "Novacea effected a 1-for-5 reverse stock split",
            "issued shares of common stock to the TPI stockholders at the rate of 0.14134 shares",
        ],
        "instrument_id": "XUSE:CASH:PRTKUSD",
        "issuer_event_date": "2009-01-30",
        "ex_date": "2009-02-06 04:00:00+04:00",
        "issuer_ratio": 0.2,
        "stored_ratio": 0.2,
        "conflict": "ISSUER_DATE_MISMATCH_AND_COMPOSITE_MERGER_REPLAY_REQUIRED",
    },
    "USB": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/36104/"
            "000104746999007568/0001047469-99-007568.txt"
        ),
        "required_fragments": [
            "the three-for-one split of the Company's common stock",
            "announced February 18, 1998",
            "a 200 percent dividend payable May 18, 1998",
        ],
        "instrument_id": "XUSE:CASH:USBUSD",
        "issuer_event_date": "1998-05-18",
        "ex_date": "1999-04-16 04:00:00+04:00",
        "issuer_ratio": 3.0,
        "stored_ratio": 3.0,
        "conflict": "ISSUER_PAYABLE_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "PRGN1": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1031107/"
            "000104746904014838/a2134573z10-k.htm"
        ),
        "required_fragments": [
            "all shares of our old common stock were cancelled on August 7, 2003",
            "Since August 8, 2003, our new common stock has been traded",
            "one share of new common stock for every 48.7548 shares of old common stock",
            "Based on a settlement reached in November 2003",
        ],
        "instrument_id": "XUSE:CASH:PRGN1USD",
        "issuer_event_date": "2003-08-07",
        "issuer_first_new_stock_trading_date": "2003-08-08",
        "ex_date": "2003-10-17 04:00:00+04:00",
        "issuer_ratio": 1 / 48.7548,
        "stored_ratio": 0.02051,
        "conflict": "ISSUER_EFFECTIVE_AND_FIRST_TRADING_DATES_DO_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "ABEV": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1113172/"
            "000114420407063976/v089496_20-f.htm"
        ),
        "required_fragments": [
            "payment by AmBev of a common stock dividend in May 2005",
            "one common share for each five shares owned",
            "stock bonus issued on May 31, 2005",
        ],
        "instrument_id": "XUSE:CASH:ABEVUSD",
        "issuer_event_date": "2005-05-31",
        "ex_date": "2005-06-09 04:00:00+04:00",
        "issuer_ratio": 1.2,
        "stored_ratio": 1.2,
        "conflict": "ISSUER_STOCK_BONUS_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "E": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1002242/"
            "000131143505000018/sj0605en20f2.htm"
        ),
        "required_fragments": [
            "group two shares of nominal value euro 0.5 into one share",
            "The conversion, due to EU requirements, was effective from June 18, 2001",
            "Starting from the same date, each ADS represents five Eni Shares",
            "2 for 1 reverse stock split",
        ],
        "instrument_id": "XUSE:CASH:EUSD",
        "issuer_event_date": "2001-06-18",
        "ex_date": "2001-06-22 04:00:00+04:00",
        "issuer_ratio": 0.5,
        "stored_ratio": 0.5,
        "conflict": "ISSUER_REVERSE_SPLIT_DATE_DOES_NOT_MATCH_FROZEN_EVENT_DATE",
    },
    "EXMCQ": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/725282/"
            "000072528298000006/0000725282-98-000006.txt"
        ),
        "required_fragments": [
            "49,741,018 and 49,660,359 issued and outstanding",
            "The number of shares outstanding of registrant's Common Stock",
            "as of July 31, 1998 was 49,766,256",
            "Each five rights will entitle the holder to purchase one share",
            "exercise price of $.05 per right",
        ],
        "instrument_id": "XUSE:CASH:EXMCQUSD",
        "issuer_terms_date": "1998-08-14",
        "ex_date": "1998-06-09 04:00:00+04:00",
        "issuer_ratio": 1.0,
        "stored_ratio": 0.05,
        "conflict": "STORED_RATIO_MATCHES_RIGHTS_PRICE_NOT_ISSUER_SHARE_MUTATION",
    },
    "AZAA": {
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1141880/"
            "000109432804000079/arizona10ksb041404woex.txt"
        ),
        "required_fragments": [
            "The Company was incorporated in Nevada in December 2000",
            "began trading on October 1, 2003",
            "under the symbol \"AZAA\"",
        ],
        "instrument_id": "XUSE:CASH:AZAAUSD",
        "issuer_terms_date": "2004-03-30",
        "ex_date": "2000-11-10 04:00:00+04:00",
        "issuer_ratio": 1.0,
        "stored_ratio": 2.0,
        "conflict": "FROZEN_EVENT_PREDATES_ISSUER_FORMATION_AND_TICKER_TRADING",
        "issuer_evidence": {
            "issuer_incorporation_month": "2000-12",
            "azaa_trading_start_date": "2003-10-01",
        },
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


def _market_boundary(
    ticker: str, specification: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    if event["lifecycle_classification"] == "NO_FROZEN_TICKER_LIFECYCLE":
        return {
            "boundary_available": False,
            "reason": "NO_FROZEN_TICKER_LIFECYCLE",
            "first_price_date": event["first_price_date"],
            "last_price_date": event["last_price_date"],
        }
    year = str(specification["ex_date"])[:4]
    path = (
        PRICE_ROOT
        / f"instrument_id={specification['instrument_id']}"
        / f"year={year}/data.parquet"
    )
    frame = pd.read_parquet(path, columns=["ts_open", "close", "volume"])
    frame["date"] = pd.to_datetime(frame["ts_open"], unit="ms", utc=True).dt.date
    event_date = dt.date.fromisoformat(str(specification["ex_date"])[:10])
    pre_rows = frame.loc[frame["date"] <= event_date].sort_values("ts_open")
    post_rows = frame.loc[frame["date"] > event_date].sort_values("ts_open")
    if len(pre_rows) < 3:
        raise ValueError(f"missing frozen pre-event market boundary: {ticker}")
    event_date_bar_present = pre_rows.iloc[-1]["date"] == event_date
    if not event_date_bar_present and not str(event["context_classification"]).startswith(
        "WEEKEND_"
    ):
        raise ValueError(f"missing frozen event-date market boundary: {ticker}")
    if not event_date_bar_present and post_rows.empty:
        raise ValueError(f"missing frozen post-event market boundary: {ticker}")

    def serialize(rows: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "date": row.date.isoformat(),
                "close": float(row.close),
                "volume": float(row.volume),
            }
            for row in rows.itertuples(index=False)
        ]

    return {
        "boundary_available": True,
        "event_date_bar_present": event_date_bar_present,
        "last_three_bars_on_or_before_event": serialize(pre_rows.iloc[-3:]),
        "first_three_bars_after_event": serialize(post_rows.iloc[:3]),
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
        raise ValueError("exactly the sixteen sealed issuer-conflict sources are required")
    resolved: list[dict[str, Any]] = []
    for ticker, specification in SOURCES.items():
        source = provided[ticker]
        key = (
            specification["instrument_id"],
            specification["ex_date"],
            float(specification["stored_ratio"]),
        )
        event = unresolved.get(key)
        if event is None:
            raise ValueError(f"issuer conflict does not bind an unresolved frozen event: {key}")
        if float(source["issuer_ratio"]) != float(specification["issuer_ratio"]):
            raise ValueError(f"{ticker} issuer ratio changed from sealed specification")
        resolved.append(
            {
                **source,
                "ex_date_ms": int(
                    dt.datetime.fromisoformat(specification["ex_date"]).timestamp() * 1000
                ),
                "prior_context_classification": event["context_classification"],
                "market_boundary": _market_boundary(ticker, specification, event),
                "execution_authorized": False,
                "ratio_repair_authorized": False,
                "governance_route": "HARD_QUARANTINE_ISSUER_CONFLICT_OR_DATE_MISMATCH",
            }
        )
    payload: dict[str, Any] = {
        "schema": "canli.alphac-split-issuer-conflict-resolution-batch.v5",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "SIXTEEN_ISSUER_CONFLICTS_RESOLVED_SEMANTICALLY_EXECUTION_REMAINS_FORBIDDEN",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "resolved_events": resolved,
        "lineage": {
            "unresolved_context_path": str(CONTEXT.relative_to(REPO)),
            "unresolved_context_sha256": _sha256(CONTEXT),
            "unresolved_context_content_hash": context["content_hash"],
        },
        "required_next_action": (
            "Keep all sixteen exact frozen tuples quarantined. CDR, DIAL1, GEVA, IPAR, USB, "
            "PRGN1, ABEV, and E require issuer-supported date corrections; NVEC and PRTK also "
            "require composite merger replay; MHGVY and EXMCQ have unsupported stored-ratio "
            "semantics; AAWW and ACL have stored mutations contradicted by issuer share counts; "
            "AZAA predates issuer formation and ticker trading."
        ),
        "claim_boundary": (
            "This identifies eleven issuer-date, duplicate, or composite mismatches, four "
            "ratio-semantics conflicts, and one issuer-identity/timeline conflict. "
            "It does "
            "not repair either row, authorize execution, open returns, validate performance, or "
            "pass the global split gate."
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
