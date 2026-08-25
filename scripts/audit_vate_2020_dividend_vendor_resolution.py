#!/usr/bin/env python3
"""Resolve the unsupported VATE/HCHC 2020 dividend row without opening returns."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
SPLIT_BASIS_AUDIT: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_split_basis.json"
)
RAW_ACTIONS: Final[Path] = REPO / "data" / "sharadar_raw" / "ACTIONS.zip"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "vate_2020_dividend_resolution.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
ENV_PATH: Final[Path] = Path.home() / ".config" / "alphaforge" / "alpaca_equity.env"
ALPACA_ENDPOINT: Final[str] = "https://data.alpaca.markets/v1/corporate-actions"
SEC_2020_10K: Final[str] = (
    "https://www.sec.gov/Archives/edgar/data/1006837/000100683721000027/"
    "hchc-20201231.htm"
)
SEC_MAY_14_8K: Final[str] = (
    "https://www.sec.gov/Archives/edgar/data/1006837/000110465920061613/"
    "tm2019732d1_8k.htm"
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


def fetch() -> tuple[dict[str, Any], bytes, str]:
    env = _load_env(ENV_PATH)
    headers = {
        "APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"],
    }
    params = {
        "symbols": "HCHC,VATE",
        "types": "cash_dividend",
        "start": "2020-01-01",
        "end": "2020-12-31",
        "region": "all",
        "data_quality": "all",
        "limit": 100,
    }
    response = httpx.get(ALPACA_ENDPOINT, headers=headers, params=params, timeout=30.0)
    response.raise_for_status()
    filing = httpx.get(
        SEC_2020_10K,
        headers={"User-Agent": "Canli Capital independent research contact@canlicapital.com"},
        timeout=30.0,
    )
    filing.raise_for_status()
    return response.json(), filing.content, dt.datetime.now(dt.UTC).isoformat()


def _raw_row(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one ACTIONS CSV")
        with archive.open(names[0]) as stream:
            actions = pd.read_csv(
                stream, usecols=["date", "action", "ticker", "name", "value"]
            )
    row = actions[
        (actions["date"] == "2020-05-14")
        & (actions["action"] == "dividend")
        & (actions["ticker"] == "VATE")
    ]
    if len(row) != 1 or float(row.iloc[0]["value"]) != 38.9:
        raise ValueError("exact VATE raw source row changed")
    return {
        "date": "2020-05-14",
        "action": "dividend",
        "ticker": "VATE",
        "name": str(row.iloc[0]["name"]),
        "value": 38.9,
    }


def _plain_text(document: bytes) -> str:
    text = re.sub(r"<[^>]+>", " ", document.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def build(
    alpaca_response: dict[str, Any],
    filing_document: bytes,
    *,
    retrieved_at: str,
) -> dict[str, Any]:
    audit = json.loads(SPLIT_BASIS_AUDIT.read_text(encoding="utf-8"))
    if audit.get("decision") != (
        "SPLIT_BASIS_HYPOTHESIS_SUPPORTED_CORRECTION_NOT_AUTHORIZED"
    ):
        raise ValueError("split-basis audit is no longer fail-closed")
    residual = [
        row
        for row in audit["classified_rows"]
        if row["classification"] == "REMAINS_UNRESOLVED_AFTER_FUTURE_SPLITS"
    ]
    if (
        len(residual) != 1
        or residual[0]["instrument_id"] != "XUSE:CASH:VATEUSD"
        or residual[0]["ex_date"][:10] != "2020-05-14"
        or residual[0]["candidate_raw_cash_amount"] != 3.89
    ):
        raise ValueError("VATE is no longer the sole split-basis residual")

    cash_rows = alpaca_response.get("corporate_actions", {}).get("cash_dividends", [])
    if cash_rows:
        raise ValueError("independent provider now reports a 2020 HCHC/VATE cash dividend")
    filing_text = _plain_text(filing_document)
    if "does not anticipate paying cash dividends in the foreseeable future" not in filing_text:
        raise ValueError("issuer dividend-policy statement not found in 2020 Form 10-K")
    if "Preferred Share Dividends" not in filing_text:
        raise ValueError("issuer filing no longer distinguishes preferred-share dividends")

    source_row = _raw_row(RAW_ACTIONS)
    payload: dict[str, Any] = {
        "schema": "canli.alphac-vate-2020-dividend-resolution.v1",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "VERSIONED_UNSUPPORTED_DIVIDEND_ROW_QUARANTINE_AUTHORIZED",
        "status": "READY_FOR_VERSIONED_DATA_REPAIR_NO_AMOUNT_IMPUTATION",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "source_row": source_row,
        "basis_audit_residual": residual[0],
        "issuer_evidence": {
            "provider": "U.S. Securities and Exchange Commission",
            "form_10k_url": SEC_2020_10K,
            "form_10k_sha256": hashlib.sha256(filing_document).hexdigest(),
            "period_of_report": "2020-12-31",
            "finding": (
                "The issuer says it did not anticipate paying cash dividends in the foreseeable "
                "future and separately reports preferred-share dividends. No common-share cash "
                "dividend corresponding to the source row is established."
            ),
            "same_date_form_8k_url": SEC_MAY_14_8K,
            "same_date_form_8k_subject": "board reconstitution and governance settlement",
        },
        "independent_vendor_check": {
            "provider": "Alpaca Market Data corporate-actions API",
            "endpoint": ALPACA_ENDPOINT,
            "query": {
                "symbols": "HCHC,VATE",
                "types": "cash_dividend",
                "start": "2020-01-01",
                "end": "2020-12-31",
                "region": "all",
                "data_quality": "all",
            },
            "cash_dividend_rows_returned": 0,
            "credentials_published": False,
            "limitation": (
                "Absence from a second provider is corroboration, not proof of complete "
                "historical coverage. The issuer filing is the governing evidence."
            ),
        },
        "lineage": {
            "split_basis_audit_path": str(SPLIT_BASIS_AUDIT.relative_to(REPO)),
            "split_basis_audit_sha256": _sha256(SPLIT_BASIS_AUDIT),
            "split_basis_audit_content_hash": audit["content_hash"],
            "raw_actions_archive": str(RAW_ACTIONS.relative_to(REPO)),
            "raw_actions_archive_sha256": _sha256(RAW_ACTIONS),
        },
        "repair_contract": {
            "original_lake_mutation_permitted": False,
            "versioned_exact_row_quarantine_permitted": True,
            "cash_amount_imputation_permitted": False,
            "rows_permitted_to_remove": [source_row],
        },
        "claim_boundary": (
            "This authorizes only exact-row quarantine in a new physical lake version. It does "
            "not establish a replacement amount, authorize split-basis conversion of the other "
            "421 rows, open returns, spend a hypothesis, rerun a strategy, or validate performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    response, filing, retrieved_at = fetch()
    payload = build(response, filing, retrieved_at=retrieved_at)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    for host in HOSTS:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text(rendered, encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
