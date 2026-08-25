#!/usr/bin/env python3
"""Cross-check failed Sharadar split boundaries against Polygon, GET-only."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import signal
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
VALIDATION: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corrected_corporate_action_validation.json"
)
TICKERS_ARCHIVE: Final[Path] = REPO / "data" / "sharadar_raw" / "TICKERS.zip"
ENV_PATH: Final[Path] = Path.home() / ".config" / "alphaforge" / "polygon.env"
ENDPOINT: Final[str] = "https://api.polygon.io/v3/reference/splits"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "polygon_split_crosscheck.json"
CHECKPOINT: Final[Path] = REPO / "var" / "audit" / "polygon_split_crosscheck_checkpoint.json"
QUERY: Final[dict[str, Any]] = {
    "execution_date.gte": "1997-12-31",
    "execution_date.lte": "2026-08-23",
    "limit": 1000,
    "sort": "execution_date",
    "order": "asc",
}
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _request_with_deadline(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any],
    wall_clock_seconds: int = 45,
) -> httpx.Response:
    def _deadline(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"Polygon request exceeded {wall_clock_seconds}s wall-clock deadline")

    previous = signal.signal(signal.SIGALRM, _deadline)
    signal.setitimer(signal.ITIMER_REAL, wall_clock_seconds)
    try:
        return client.get(url, params=params)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _write_checkpoint(
    *,
    rows: list[dict[str, Any]],
    next_execution_date_gte: str | None,
    pages: int,
    complete: bool,
) -> None:
    payload = {
        "schema": "canli.alphac-polygon-split-download-checkpoint.v2",
        "endpoint": ENDPOINT,
        "query": QUERY,
        "pages": pages,
        "rows": rows,
        "next_execution_date_gte": next_execution_date_gte,
        "complete": complete,
    }
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    temporary = CHECKPOINT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(CHECKPOINT)


def fetch() -> tuple[list[dict[str, Any]], str, int]:
    api_key = _load_env(ENV_PATH)["POLYGON_API_KEY"]
    if CHECKPOINT.exists():
        checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        if checkpoint.get("endpoint") != ENDPOINT or checkpoint.get("query") != QUERY:
            raise ValueError("Polygon checkpoint does not match the sealed query")
        rows = list(checkpoint["rows"])
        pages = int(checkpoint["pages"])
        lower_bound = checkpoint.get("next_execution_date_gte")
        if checkpoint.get("complete"):
            return rows, dt.datetime.now(dt.UTC).isoformat(), pages
    else:
        rows = []
        pages = 0
        lower_bound = str(QUERY["execution_date.gte"])
    if not lower_bound:
        raise ValueError("incomplete Polygon checkpoint has no continuation boundary")
    seen_provider_ids = {str(row["id"]) for row in rows}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        while True:
            params = {**QUERY, "execution_date.gte": lower_bound, "apiKey": api_key}
            for attempt in range(1, 4):
                try:
                    response = _request_with_deadline(client, ENDPOINT, params=params)
                    response.raise_for_status()
                    break
                except (httpx.HTTPError, TimeoutError):
                    if attempt == 3:
                        raise
                    time.sleep(3 * attempt)
            payload = response.json()
            if payload.get("status") != "OK":
                raise ValueError("Polygon split endpoint did not return OK")
            page_rows = list(payload.get("results", []))
            page_dates = [str(row["execution_date"]) for row in page_rows]
            if page_dates != sorted(page_dates):
                raise ValueError("Polygon split page is not sorted by execution date ascending")
            if any(
                date < lower_bound or date > str(QUERY["execution_date.lte"])
                for date in page_dates
            ):
                raise ValueError("Polygon split page escaped the sealed date range")
            new_rows = [row for row in page_rows if str(row["id"]) not in seen_provider_ids]
            rows.extend(new_rows)
            seen_provider_ids.update(str(row["id"]) for row in new_rows)
            pages += 1
            complete = len(page_rows) < int(QUERY["limit"])
            next_lower_bound = None if complete else page_dates[-1]
            if not complete and next_lower_bound == lower_bound and not new_rows:
                raise ValueError("Polygon date-boundary pagination made no progress")
            _write_checkpoint(
                rows=rows,
                next_execution_date_gte=next_lower_bound,
                pages=pages,
                complete=complete,
            )
            print(f"Polygon split page {pages}: {len(rows)} rows", file=sys.stderr, flush=True)
            if pages > 1000:
                raise ValueError("Polygon pagination exceeded the 1000-page safety ceiling")
            if complete:
                break
            lower_bound = str(next_lower_bound)
    return rows, dt.datetime.now(dt.UTC).isoformat(), pages


def _aliases() -> dict[str, set[str]]:
    with zipfile.ZipFile(TICKERS_ARCHIVE) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one TICKERS CSV")
        with archive.open(names[0]) as stream:
            tickers = pd.read_csv(stream, usecols=["ticker", "relatedtickers"])
    result: dict[str, set[str]] = {}
    for row in tickers.itertuples(index=False):
        ticker = str(row.ticker).upper()
        canonical = ticker.replace(".", "").replace("-", "")
        values = {ticker}
        if not pd.isna(row.relatedtickers):
            values.update(str(row.relatedtickers).upper().split())
        result.setdefault(canonical, set()).update(values)
    return result


def classify_failure(
    failure: dict[str, Any],
    provider_rows: list[dict[str, Any]],
    aliases: set[str],
) -> dict[str, Any]:
    date = str(failure["ex_date"])[:10]
    matches = [
        row
        for row in provider_rows
        if str(row.get("ticker", "")).upper() in aliases
        and row.get("execution_date") == date
        and float(row.get("split_from", 0.0)) > 0.0
        and float(row.get("split_to", 0.0)) > 0.0
    ]
    ratios = sorted(
        {
            float(row["split_to"]) / float(row["split_from"])
            for row in matches
        }
    )
    stored = float(failure["stored_ratio"])
    confirms_stored = any(
        math.isclose(ratio, stored, rel_tol=2e-4, abs_tol=5.01e-6)
        for ratio in ratios
    )
    confirms_reciprocal = any(
        math.isclose(ratio, 1.0 / stored, rel_tol=2e-4, abs_tol=5.01e-6)
        for ratio in ratios
    )
    if confirms_stored:
        classification = "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO"
    elif confirms_reciprocal:
        classification = "INDEPENDENT_PROVIDER_CONFIRMS_RECIPROCAL_RATIO"
    elif matches:
        classification = "INDEPENDENT_PROVIDER_EVENT_CONFLICT"
    else:
        classification = "NO_INDEPENDENT_PROVIDER_MATCH"
    return {
        "instrument_id": failure["instrument_id"],
        "ex_date": failure["ex_date"],
        "local_classification": failure["classification"],
        "stored_ratio": stored,
        "aliases_checked": sorted(aliases),
        "provider_ratios": ratios,
        "provider_rows": sorted(
            matches,
            key=lambda row: (str(row.get("ticker")), str(row.get("id"))),
        ),
        "classification": classification,
    }


def build(
    provider_rows: list[dict[str, Any]], *, retrieved_at: str, pages: int
) -> dict[str, Any]:
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    if validation.get("decision") != "CORPORATE_ACTION_VALIDATION_FAILED_SPLIT_BOUNDARIES":
        raise ValueError("local split validation no longer fails closed")
    failures = validation["split_gate"]["failures"]
    alias_map = _aliases()
    crosschecks: list[dict[str, Any]] = []
    for failure in failures:
        symbol = str(failure["instrument_id"]).split(":")[2].removesuffix("USD")
        aliases = alias_map.get(symbol, {symbol})
        crosschecks.append(classify_failure(failure, provider_rows, aliases))
    counts = pd.Series([row["classification"] for row in crosschecks]).value_counts()
    provider_canonical = json.dumps(
        sorted(
            provider_rows,
            key=lambda row: (
                str(row.get("execution_date")),
                str(row.get("ticker")),
                str(row.get("id")),
            ),
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload: dict[str, Any] = {
        "schema": "canli.alphac-polygon-split-crosscheck.v1",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "INDEPENDENT_SPLIT_CROSSCHECK_COMPLETE_LOCAL_GATE_REMAINS_CLOSED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "summary": {
            "local_failed_or_unverifiable_events": len(crosschecks),
            "independent_provider_confirms_stored_ratio": int(
                counts.get("INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO", 0)
            ),
            "independent_provider_confirms_reciprocal_ratio": int(
                counts.get("INDEPENDENT_PROVIDER_CONFIRMS_RECIPROCAL_RATIO", 0)
            ),
            "independent_provider_event_conflict": int(
                counts.get("INDEPENDENT_PROVIDER_EVENT_CONFLICT", 0)
            ),
            "no_independent_provider_match": int(
                counts.get("NO_INDEPENDENT_PROVIDER_MATCH", 0)
            ),
        },
        "crosschecks": crosschecks,
        "source": {
            "provider": "Polygon.io Reference Splits API",
            "endpoint": ENDPOINT,
            "query": {
                "execution_date.gte": "1997-12-31",
                "execution_date.lte": "2026-08-23",
                "sort": "execution_date",
                "order": "asc",
            },
            "pages": pages,
            "provider_rows": len(provider_rows),
            "provider_snapshot_sha256": hashlib.sha256(provider_canonical).hexdigest(),
            "credentials_published": False,
        },
        "lineage": {
            "local_validation_path": str(VALIDATION.relative_to(REPO)),
            "local_validation_sha256": _sha256(VALIDATION),
            "local_validation_content_hash": validation["content_hash"],
            "ticker_alias_archive": str(TICKERS_ARCHIVE.relative_to(REPO)),
            "ticker_alias_archive_sha256": _sha256(TICKERS_ARCHIVE),
        },
        "required_next_action": (
            "Use independently confirmed reciprocal rows as candidates for an explicit versioned "
            "repair. Independently confirmed stored ratios still require lifecycle/date analysis "
            "when the local price boundary disagrees. Keep unmatched and conflicting events closed."
        ),
        "claim_boundary": (
            "This GET-only cross-check measures external corporate-action agreement. It does not "
            "mutate a lake, open returns, spend a hypothesis, authorize a replay, or validate "
            "performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    rows, retrieved_at, pages = fetch()
    payload = build(rows, retrieved_at=retrieved_at, pages=pages)
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
