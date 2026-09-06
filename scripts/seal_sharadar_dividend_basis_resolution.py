#!/usr/bin/env python3
"""Seal issuer-anchored authority for a versioned Sharadar dividend-basis repair."""

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
RAW_ACTIONS: Final[Path] = REPO / "data" / "sharadar_raw" / "ACTIONS.zip"
SPLIT_BASIS_AUDIT: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_split_basis.json"
)
HDB_RESOLUTION: Final[Path] = (
    REPO / "artifacts" / "audit" / "hdb_dividend_vendor_resolution.json"
)
VATE_RESOLUTION: Final[Path] = (
    REPO / "artifacts" / "audit" / "vate_2020_dividend_resolution.json"
)
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_dividend_basis_resolution.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
APPLE_HISTORY: Final[str] = "https://investor.apple.com/dividend-history/default.aspx"
APPLE_SEC_FILING: Final[str] = (
    "https://www.sec.gov/Archives/edgar/data/320193/000032019320000050/"
    "a8-kexhibit991q2202032.htm"
)
SHARADAR_STOCKS_DOCS: Final[str] = "https://sharadar.com/docs/stocks"
SHARADAR_ACTIONS_DOCS: Final[str] = "https://sharadar.com/docs/actions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _plain_text(document: bytes) -> str:
    text = re.sub(r"<[^>]+>", " ", document.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch() -> tuple[dict[str, bytes], str]:
    headers = {"User-Agent": "Canli Capital independent research contact@canlicapital.com"}
    documents: dict[str, bytes] = {}
    for name, url in {
        "apple_history": APPLE_HISTORY,
        "apple_sec_filing": APPLE_SEC_FILING,
        "sharadar_stocks_docs": SHARADAR_STOCKS_DOCS,
        "sharadar_actions_docs": SHARADAR_ACTIONS_DOCS,
    }.items():
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        documents[name] = response.content
    return documents, dt.datetime.now(dt.UTC).isoformat()


def _apple_source_rows(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one ACTIONS CSV")
        with archive.open(names[0]) as stream:
            actions = pd.read_csv(
                stream, usecols=["date", "action", "ticker", "name", "value"]
            )
    rows = actions[
        (actions["ticker"] == "AAPL")
        & (
            ((actions["action"] == "dividend") & (actions["date"] == "2020-05-08"))
            | ((actions["action"] == "split") & (actions["date"] == "2020-08-31"))
        )
    ].sort_values(["date", "action"])
    if len(rows) != 2:
        raise ValueError("Apple source anchor rows changed")
    dividend = rows[rows["action"] == "dividend"].iloc[0]
    split = rows[rows["action"] == "split"].iloc[0]
    if float(dividend["value"]) != 0.205 or float(split["value"]) != 4.0:
        raise ValueError("Apple source anchor values changed")
    return [
        {
            "date": str(row.date),
            "action": str(row.action),
            "ticker": str(row.ticker),
            "name": str(row.name),
            "value": float(row.value),
        }
        for row in rows.itertuples(index=False)
    ]


def build(documents: dict[str, bytes], *, retrieved_at: str) -> dict[str, Any]:
    audit = json.loads(SPLIT_BASIS_AUDIT.read_text(encoding="utf-8"))
    hdb = json.loads(HDB_RESOLUTION.read_text(encoding="utf-8"))
    vate = json.loads(VATE_RESOLUTION.read_text(encoding="utf-8"))
    if audit.get("summary", {}).get("arithmetically_reconciled_rows") != 421:
        raise ValueError("split-basis reconciliation coverage changed")
    if hdb.get("decision") != "VERSIONED_ZERO_MARKER_QUARANTINE_AUTHORIZED":
        raise ValueError("HDB exact-row authority changed")
    if vate.get("decision") != "VERSIONED_UNSUPPORTED_DIVIDEND_ROW_QUARANTINE_AUTHORIZED":
        raise ValueError("VATE exact-row authority changed")

    apple_history_text = _plain_text(documents["apple_history"])
    apple_filing_text = _plain_text(documents["apple_sec_filing"])
    stocks_text = _plain_text(documents["sharadar_stocks_docs"])
    actions_text = _plain_text(documents["sharadar_actions_docs"])
    if "4-for-1 Stock Split" not in apple_history_text or "$.82" not in apple_history_text:
        raise ValueError("Apple investor-history anchor changed")
    if "cash dividend of $0.82 per share" not in apple_filing_text:
        raise ValueError("Apple SEC cash-dividend anchor changed")
    if "Close Price - Split Adjusted" not in stocks_text:
        raise ValueError("Sharadar stock-price adjustment documentation changed")
    if "Value value numeric" not in actions_text:
        raise ValueError("Sharadar ACTIONS value documentation changed")

    source_rows = _apple_source_rows(RAW_ACTIONS)
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-dividend-basis-resolution.v1",
        "author": "Arhan Canli",
        "retrieved_at": retrieved_at,
        "decision": "VERSIONED_DIVIDEND_BASIS_REPAIR_AUTHORIZED_FOR_DATA_VALIDATION",
        "status": "REPAIR_CONTRACT_SEALED_REPLAY_NOT_AUTHORIZED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "ordinary_event_anchor": {
            "ticker": "AAPL",
            "source_rows": source_rows,
            "source_dividend_value": 0.205,
            "later_market_split_ratio": 4.0,
            "candidate_raw_dividend": 0.82,
            "issuer_declared_raw_dividend": 0.82,
            "exact_equality": 0.205 * 4.0 == 0.82,
            "finding": (
                "Sharadar's pre-split dividend value is expressed on the later split-adjusted "
                "basis. Multiplying by the same-ticker market split restores the issuer-declared "
                "cash amount exactly."
            ),
        },
        "systemic_evidence": {
            "source_offending_rows": 422,
            "rows_reconciled_by_the_same_formula": 421,
            "residual_rows_with_exact_quarantine_authority": 1,
            "reconciled_fraction": audit["summary"]["arithmetically_reconciled_fraction"],
        },
        "repair_contract": {
            "dividend_formula": (
                "raw_cash_amount = source_value * product(value of every same-ticker raw "
                "action='split' with date >= dividend date)"
            ),
            "formula_scope": "every finite positive dividend in the frozen ACTIONS archive",
            "market_split_source_action": "split",
            "adrratiosplit_is_second_position_mutation": False,
            "hdb_2025_06_26_zero_marker_action": "QUARANTINE_EXACT_ROW",
            "vate_2020_05_14_unsupported_dividend_action": "QUARANTINE_EXACT_ROW",
            "amount_imputation_permitted": False,
            "original_archive_or_lake_mutation_permitted": False,
            "new_physical_version_required": True,
        },
        "mandatory_post_build_gates": {
            "all_positive_dividends_at_or_below_pre_ex_raw_close": True,
            "all_executable_splits_pass_price_boundary_sanity": True,
            "all_non_corporate_action_files_byte_identical_or_hardlinked": True,
            "exact_hdb_and_vate_rows_absent": True,
            "no_other_source_rows_dropped": True,
            "replay_permitted_before_all_gates_pass": False,
        },
        "sources": {
            "apple_dividend_history": {
                "url": APPLE_HISTORY,
                "retrieved_sha256": hashlib.sha256(documents["apple_history"]).hexdigest(),
            },
            "apple_sec_filing": {
                "url": APPLE_SEC_FILING,
                "retrieved_sha256": hashlib.sha256(documents["apple_sec_filing"]).hexdigest(),
            },
            "sharadar_stock_price_documentation": {
                "url": SHARADAR_STOCKS_DOCS,
                "retrieved_sha256": hashlib.sha256(
                    documents["sharadar_stocks_docs"]
                ).hexdigest(),
            },
            "sharadar_actions_documentation": {
                "url": SHARADAR_ACTIONS_DOCS,
                "retrieved_sha256": hashlib.sha256(
                    documents["sharadar_actions_docs"]
                ).hexdigest(),
                "limitation": "Public documentation labels value numeric without basis semantics.",
            },
        },
        "lineage": {
            "raw_actions_archive_sha256": _sha256(RAW_ACTIONS),
            "split_basis_audit_sha256": _sha256(SPLIT_BASIS_AUDIT),
            "split_basis_audit_content_hash": audit["content_hash"],
            "hdb_resolution_sha256": _sha256(HDB_RESOLUTION),
            "hdb_resolution_content_hash": hdb["content_hash"],
            "vate_resolution_sha256": _sha256(VATE_RESOLUTION),
            "vate_resolution_content_hash": vate["content_hash"],
        },
        "claim_boundary": (
            "This authorizes a new physical data version for validation only. The adjustment-basis "
            "interpretation is an issuer-anchored inference because public ACTIONS documentation "
            "does not state the basis explicitly. No replay, trial, sleeve, or performance claim "
            "is authorized until every post-build gate passes."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    documents, retrieved_at = fetch()
    payload = build(documents, retrieved_at=retrieved_at)
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
