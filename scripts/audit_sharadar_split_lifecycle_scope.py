#!/usr/bin/env python3
"""Classify failed split boundaries against the frozen ticker price lifecycle."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
VALIDATION: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corrected_corporate_action_validation.json"
)
CROSSCHECK: Final[Path] = REPO / "artifacts" / "audit" / "polygon_split_crosscheck.json"
TICKERS_ARCHIVE: Final[Path] = REPO / "data" / "sharadar_raw" / "TICKERS.zip"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_split_lifecycle_scope.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def classify_lifecycle(
    *, event_date: str, first_price_date: str, last_price_date: str, pre_close: Any
) -> str:
    event = pd.Timestamp(event_date).date()
    first = pd.Timestamp(first_price_date).date()
    last = pd.Timestamp(last_price_date).date()
    if event < first:
        return "BEFORE_FIRST_PRICE_NON_EXECUTABLE"
    if event == first and pre_close is None:
        return "FIRST_PRICE_BOUNDARY_NO_PREEXISTING_EXPOSURE"
    if event > last:
        return "AFTER_LAST_PRICE_NON_EXECUTABLE"
    return "WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION"


def _ticker_lifecycles() -> dict[str, dict[str, str]]:
    with zipfile.ZipFile(TICKERS_ARCHIVE) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one TICKERS CSV")
        with archive.open(names[0]) as stream:
            tickers = pd.read_csv(
                stream,
                usecols=["table", "ticker", "firstpricedate", "lastpricedate"],
                dtype=str,
            )
    tickers = tickers.loc[tickers["table"] == "SEP"].copy()
    if tickers["ticker"].duplicated().any():
        raise ValueError("SEP ticker lifecycle mapping is not unique")
    return {
        str(row.ticker).upper(): {
            "first_price_date": str(row.firstpricedate),
            "last_price_date": str(row.lastpricedate),
        }
        for row in tickers.itertuples(index=False)
    }


def build() -> dict[str, Any]:
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    crosscheck = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
    failures = validation["split_gate"]["failures"]
    provider_by_key = {
        (row["instrument_id"], row["ex_date"]): row["classification"]
        for row in crosscheck["crosschecks"]
    }
    lifecycles = _ticker_lifecycles()
    rows: list[dict[str, Any]] = []
    for failure in failures:
        ticker = str(failure["instrument_id"]).split(":")[2].removesuffix("USD")
        lifecycle = lifecycles.get(ticker)
        if lifecycle is None:
            classification = "NO_FROZEN_TICKER_LIFECYCLE"
            first_price_date = None
            last_price_date = None
        else:
            first_price_date = lifecycle["first_price_date"]
            last_price_date = lifecycle["last_price_date"]
            classification = classify_lifecycle(
                event_date=failure["ex_date"],
                first_price_date=first_price_date,
                last_price_date=last_price_date,
                pre_close=failure.get("pre_close"),
            )
        rows.append(
            {
                "instrument_id": failure["instrument_id"],
                "ticker": ticker,
                "ex_date": failure["ex_date"],
                "stored_ratio": failure["stored_ratio"],
                "local_classification": failure["classification"],
                "provider_classification": provider_by_key[
                    (failure["instrument_id"], failure["ex_date"])
                ],
                "first_price_date": first_price_date,
                "last_price_date": last_price_date,
                "lifecycle_classification": classification,
            }
        )
    counts = pd.Series([row["lifecycle_classification"] for row in rows]).value_counts()
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-split-lifecycle-scope-audit.v1",
        "author": "Arhan Canli",
        "decision": "SPLIT_LIFECYCLE_SCOPE_AUDITED_REPLAY_GATE_REMAINS_CLOSED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "summary": {
            "failed_or_unverifiable_events": len(rows),
            "before_first_price_non_executable": int(
                counts.get("BEFORE_FIRST_PRICE_NON_EXECUTABLE", 0)
            ),
            "first_price_boundary_no_preexisting_exposure": int(
                counts.get("FIRST_PRICE_BOUNDARY_NO_PREEXISTING_EXPOSURE", 0)
            ),
            "after_last_price_non_executable": int(
                counts.get("AFTER_LAST_PRICE_NON_EXECUTABLE", 0)
            ),
            "within_price_lifecycle_requires_resolution": int(
                counts.get("WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION", 0)
            ),
            "no_frozen_ticker_lifecycle": int(
                counts.get("NO_FROZEN_TICKER_LIFECYCLE", 0)
            ),
        },
        "events": rows,
        "lineage": {
            "validation_path": str(VALIDATION.relative_to(REPO)),
            "validation_sha256": _sha256(VALIDATION),
            "validation_content_hash": validation["content_hash"],
            "provider_crosscheck_path": str(CROSSCHECK.relative_to(REPO)),
            "provider_crosscheck_sha256": _sha256(CROSSCHECK),
            "provider_crosscheck_content_hash": crosscheck["content_hash"],
            "ticker_archive_path": str(TICKERS_ARCHIVE.relative_to(REPO)),
            "ticker_archive_sha256": _sha256(TICKERS_ARCHIVE),
        },
        "required_next_action": (
            "Seal and test a rule that excludes pre-first-price, first-price-boundary, and "
            "post-last-price metadata from executable split transformations only when exposure "
            "and queued orders are impossible. Continue issuer resolution for every event inside "
            "the market-price lifecycle."
        ),
        "claim_boundary": (
            "Lifecycle classification does not delete source events or authorize ratio repair. "
            "It opens no returns, spends no hypothesis, and does not authorize replay or "
            "performance claims."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    for host in HOSTS:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text(rendered, encoding="utf-8")
    print(json.dumps({"summary": payload["summary"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
