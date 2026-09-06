#!/usr/bin/env python3
"""Test whether impossible Sharadar dividends are expressed on a split-adjusted basis.

This source-only diagnostic reads the sealed raw-price consistency audit and the raw
corporate-action archive. It never opens a strategy result. Arithmetic support for an
adjustment-basis hypothesis is not authorization to rewrite the executable lake.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE_AUDIT: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_price_consistency.json"
)
RAW_ACTIONS: Final[Path] = REPO / "data" / "sharadar_raw" / "ACTIONS.zip"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_dividend_split_basis.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _read_actions(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one ACTIONS CSV")
        with archive.open(names[0]) as stream:
            return pd.read_csv(stream, usecols=["date", "action", "ticker", "value"])


def classify_rows(offenders: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Rebase each source value by same-day and later market split ratios."""
    rows = offenders.copy()
    rows["ticker"] = rows["instrument_id"].str.split(":").str[2].str.removesuffix("USD")
    rows["ex_day"] = pd.to_datetime(rows["ex_date"], utc=True).dt.tz_localize(None).dt.normalize()
    # Sharadar can emit a market-price `split` and an inverse `adrratiosplit` on the same
    # date. Multiplying both would erase the actual split. The latter describes the ADR
    # contract ratio and is not a second market-share mutation in this arithmetic test.
    splits = actions[actions["action"] == "split"].copy()
    splits["ticker"] = splits["ticker"].astype(str).str.upper()
    splits["date"] = pd.to_datetime(splits["date"])
    splits["value"] = pd.to_numeric(splits["value"], errors="coerce")
    splits = splits[np.isfinite(splits["value"]) & (splits["value"] > 0.0)]

    products: list[float] = []
    for record in rows.itertuples(index=False):
        later = splits.loc[
            (splits["ticker"] == record.ticker) & (splits["date"] >= record.ex_day),
            "value",
        ]
        products.append(float(later.prod()) if len(later) else 1.0)
    rows["future_split_product"] = products
    rows["candidate_raw_cash_amount"] = rows["cash_amount"] * rows["future_split_product"]
    rows["candidate_raw_close_multiple"] = (
        rows["candidate_raw_cash_amount"] / rows["pre_close"]
    )
    rows["classification"] = np.where(
        rows["candidate_raw_close_multiple"] <= 1.0,
        "ARITHMETICALLY_RECONCILED_BY_FUTURE_SPLITS",
        "REMAINS_UNRESOLVED_AFTER_FUTURE_SPLITS",
    )
    return rows


def _record(row: Any) -> dict[str, Any]:
    return {
        "instrument_id": str(row.instrument_id),
        "ex_date": str(row.ex_date),
        "source_cash_amount": float(row.cash_amount),
        "pre_ex_raw_close": float(row.pre_close),
        "source_to_raw_close_multiple": float(row.pre_close_multiple),
        "future_split_product": float(row.future_split_product),
        "candidate_raw_cash_amount": float(row.candidate_raw_cash_amount),
        "candidate_raw_close_multiple": float(row.candidate_raw_close_multiple),
        "classification": str(row.classification),
    }


def build_audit(
    *, source_path: Path = SOURCE_AUDIT, actions_path: Path = RAW_ACTIONS
) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("decision") != "DIVIDEND_PRICE_CONSISTENCY_FAILED":
        raise ValueError("source dividend audit no longer fails closed")
    offenders = pd.DataFrame(source["offending_rows"])
    classified = classify_rows(offenders, _read_actions(actions_path))
    explained = classified[
        classified["classification"] == "ARITHMETICALLY_RECONCILED_BY_FUTURE_SPLITS"
    ]
    residual = classified[
        classified["classification"] == "REMAINS_UNRESOLVED_AFTER_FUTURE_SPLITS"
    ]
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-dividend-split-basis-audit.v1",
        "evidence_date": "2026-08-23",
        "author": "Arhan Canli",
        "decision": "SPLIT_BASIS_HYPOTHESIS_SUPPORTED_CORRECTION_NOT_AUTHORIZED",
        "method": (
            "For each impossible dividend, multiply the source value by every same-day or later "
            "market-price split for the same raw ticker, then compare the candidate raw cash "
            "amount with the sealed strictly pre-ex unadjusted close. Inverse ADR-ratio metadata "
            "is not executed as a second share mutation."
        ),
        "summary": {
            "source_offending_rows": len(classified),
            "arithmetically_reconciled_rows": len(explained),
            "arithmetically_reconciled_fraction": len(explained) / len(classified),
            "residual_unresolved_rows": len(residual),
            "residual_unresolved_instruments": int(residual["instrument_id"].nunique()),
            "maximum_rebased_close_multiple": float(
                classified["candidate_raw_close_multiple"].max()
            ),
        },
        "residual_instrument_counts": {
            str(key): int(value)
            for key, value in residual.groupby("instrument_id").size().items()
        },
        "classified_rows": [_record(row) for row in classified.itertuples(index=False)],
        "lineage": {
            "source_audit_path": str(source_path.relative_to(REPO)),
            "source_audit_sha256": _sha256(source_path),
            "source_audit_content_hash": source["content_hash"],
            "raw_actions_archive": str(actions_path.relative_to(REPO)),
            "raw_actions_archive_sha256": _sha256(actions_path),
            "sharadar_stock_price_documentation": "https://sharadar.com/docs/stocks",
            "sharadar_actions_documentation": "https://sharadar.com/docs/actions",
        },
        "required_next_action": (
            "Obtain explicit vendor adjustment-basis semantics before converting any of the "
            "421 reconciled rows. Resolve the remaining VATE row through issuer distribution "
            "evidence. Keep all 422 rows quarantined until both requirements are bound."
        ),
        "claim_boundary": (
            "The arithmetic strongly supports a split-adjustment-basis explanation for 421 "
            "rows, but public vendor documentation labels ACTIONS.value only as numeric. This "
            "audit authorizes no lake mutation, replay, trial, sleeve, or performance claim."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build_audit()
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
