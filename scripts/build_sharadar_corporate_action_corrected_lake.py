#!/usr/bin/env python3
"""Build a versioned Sharadar lake with normalized executable corporate actions.

The build opens no strategy output. It reconstructs corporate actions from the
frozen raw archive under a sealed repair contract, while hard-linking every other
dataset. A separate post-build audit must pass before any replay is authorized.
"""

from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

REPO: Final[Path] = Path(__file__).resolve().parents[1]
BASE_LAKE: Final[Path] = REPO / "data" / "lake_sharadar"
RAW_ACTIONS: Final[Path] = REPO / "data" / "sharadar_raw" / "ACTIONS.zip"
AUTHORITY: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_dividend_basis_resolution.json"
)
OUTPUT: Final[Path] = (
    REPO / "artifacts" / "audit" / "sharadar_corporate_action_corrected_lake.json"
)
NON_ACTION_DATASETS: Final[tuple[str, ...]] = (
    "fundamentals",
    "ohlcv_1d",
    "universe_membership",
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _tree_root(root: Path) -> tuple[str, int, int]:
    leaves: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*.parquet") if item.is_file()):
        leaves.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    canonical = json.dumps(leaves, sort_keys=True, separators=(",", ":")).encode()
    return (
        "sha256:" + hashlib.sha256(canonical).hexdigest(),
        len(leaves),
        sum(int(item["bytes"]) for item in leaves),
    )


def corrected_lake_path(authority: dict[str, Any]) -> Path:
    digest = str(authority["content_hash"]).removeprefix("sha256:")[:12]
    return (
        REPO
        / "data"
        / "corrections"
        / f"corporate_action_basis_{digest}_materialized_v1"
        / "data"
        / "lake_sharadar"
    )


def _canonical_id(ticker: pd.Series) -> pd.Series:
    symbols = (
        ticker.astype(str)
        .str.upper()
        .str.replace(".", "", regex=False)
        .str.replace("-", "", regex=False)
    )
    return "XUSE:CASH:" + symbols + "USD"


def _read_raw_actions() -> pd.DataFrame:
    with zipfile.ZipFile(RAW_ACTIONS) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one ACTIONS CSV")
        with archive.open(names[0]) as stream:
            frame = pd.read_csv(stream, usecols=["date", "action", "ticker", "value"])
    frame = frame[frame["action"].isin(["split", "adrratiosplit", "dividend"])].copy()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    if (~np.isfinite(frame["value"])).any():
        raise ValueError("raw executable action value is non-finite")
    frame["instrument_id"] = _canonical_id(frame["ticker"])
    frame["action_type"] = np.where(frame["action"] == "dividend", "dividend", "split")
    frame["vkey"] = frame["value"].map(lambda value: float(value).hex())
    frame["date_value"] = pd.to_datetime(frame["date"], format="%Y-%m-%d").dt.date
    return frame


def _read_base_actions() -> tuple[pd.DataFrame, pa.Schema]:
    root = BASE_LAKE / "corporate_actions"
    table = ds.dataset(root, format="parquet", partitioning=None).to_table()
    frame = table.to_pandas()
    frame["date"] = pd.to_datetime(frame["ex_date"], utc=True).dt.strftime("%Y-%m-%d")
    frame["value"] = frame["ratio"].where(
        frame["action_type"] == "split", frame["cash_amount"]
    )
    frame["vkey"] = frame["value"].map(lambda value: float(value).hex())
    return frame, table.schema


def _future_market_split_products(
    raw: pd.DataFrame,
) -> dict[str, tuple[list[dt.date], list[float]]]:
    market = raw[raw["action"] == "split"]
    grouped = (
        market.groupby(["ticker", "date_value"], sort=True)["value"]
        .prod()
        .reset_index()
    )
    result: dict[str, tuple[list[dt.date], list[float]]] = {}
    for ticker, rows in grouped.groupby("ticker", sort=False):
        ordered = rows.sort_values("date_value")
        dates = ordered["date_value"].tolist()
        values = ordered["value"].astype(float).tolist()
        suffix = [1.0] * len(values)
        running = 1.0
        for index in range(len(values) - 1, -1, -1):
            running *= values[index]
            if not math.isfinite(running) or running <= 0.0:
                raise ValueError(f"invalid cumulative split product for {ticker}")
            suffix[index] = running
        result[str(ticker)] = (dates, suffix)
    return result


def _product_at_or_after(
    lookup: dict[str, tuple[list[dt.date], list[float]]], ticker: str, date: dt.date
) -> float:
    series = lookup.get(ticker)
    if series is None:
        return 1.0
    dates, suffix = series
    index = bisect.bisect_left(dates, date)
    return 1.0 if index == len(dates) else suffix[index]


def normalize_actions(
    base: pd.DataFrame, raw: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return a source-traced executable action frame under the sealed contract."""
    key_columns = ["instrument_id", "date", "action_type", "vkey"]
    if base.duplicated(key_columns).any():
        raise ValueError("base corporate-action keys are not unique")
    raw_groups = raw.groupby(key_columns, sort=False, dropna=False)
    source_tickers: dict[tuple[Any, ...], str] = {}
    market_split_keys: set[tuple[Any, ...]] = set()
    for key, rows in raw_groups:
        tickers = sorted(set(rows["ticker"].astype(str)))
        if len(tickers) != 1:
            raise ValueError(f"canonical action key maps to multiple raw tickers: {key}")
        source_tickers[key] = tickers[0]
        if (rows["action"] == "split").any():
            market_split_keys.add(key)
    base_keys = [tuple(row) for row in base[key_columns].itertuples(index=False, name=None)]
    missing = [key for key in base_keys if key not in source_tickers]
    if missing:
        raise ValueError(f"base rows missing raw lineage: {missing[:5]}")

    normalized = base.copy()
    normalized["source_ticker"] = [source_tickers[key] for key in base_keys]
    is_split = normalized["action_type"] == "split"
    executable_split = pd.Series(
        [key in market_split_keys for key in base_keys], index=normalized.index
    )
    adrratio_metadata_rows = int((is_split & ~executable_split).sum())
    normalized = normalized[~is_split | executable_split].copy()

    hdb_zero = (
        (normalized["instrument_id"] == "XUSE:CASH:HDBUSD")
        & (normalized["action_type"] == "dividend")
        & (normalized["date"] == "2025-06-26")
        & (normalized["cash_amount"] == 0.0)
    )
    vate_unsupported = (
        (normalized["instrument_id"] == "XUSE:CASH:VATEUSD")
        & (normalized["action_type"] == "dividend")
        & (normalized["date"] == "2020-05-14")
        & (normalized["cash_amount"] == 38.9)
    )
    if int(hdb_zero.sum()) != 1 or int(vate_unsupported.sum()) != 1:
        raise ValueError("authorized HDB/VATE quarantine targets changed")
    normalized = normalized[~hdb_zero & ~vate_unsupported].copy()

    lookup = _future_market_split_products(raw)
    dividends = normalized["action_type"] == "dividend"
    dividend_products = [
        _product_at_or_after(
            lookup,
            str(row.source_ticker),
            pd.Timestamp(row.date).date(),
        )
        for row in normalized.loc[dividends].itertuples(index=False)
    ]
    source_cash = normalized.loc[dividends, "cash_amount"].astype(float).to_numpy()
    converted_cash = source_cash * np.asarray(dividend_products, dtype=float)
    if (~np.isfinite(converted_cash) | (converted_cash <= 0.0)).any():
        raise ValueError("normalized dividend is non-finite or non-positive")
    changed = int((converted_cash != source_cash).sum())
    normalized.loc[dividends, "cash_amount"] = converted_cash

    apple = normalized[
        (normalized["instrument_id"] == "XUSE:CASH:AAPLUSD")
        & (normalized["action_type"] == "dividend")
        & (normalized["date"] == "2020-05-08")
    ]
    if len(apple) != 1 or float(apple.iloc[0]["cash_amount"]) != 0.82:
        raise ValueError("Apple ordinary-event anchor did not normalize exactly")

    normalized = normalized.drop(
        columns=["date", "value", "vkey", "source_ticker"], errors="ignore"
    )
    summary = {
        "base_rows": len(base),
        "normalized_rows": len(normalized),
        "adrratiosplit_metadata_rows_removed_from_execution": adrratio_metadata_rows,
        "exact_source_rows_quarantined": 2,
        "dividend_rows_normalized": int(dividends.sum()),
        "dividend_amounts_changed": changed,
        "market_split_rows_preserved": int((normalized["action_type"] == "split").sum()),
    }
    return normalized, summary


def _write_actions(frame: pd.DataFrame, schema: pa.Schema, root: Path) -> None:
    frame = frame.copy()
    frame["year"] = pd.to_datetime(frame["ex_date"], utc=True).dt.year.astype(int)
    columns = schema.names
    for (instrument_id, year), rows in frame.groupby(["instrument_id", "year"], sort=True):
        destination = (
            root
            / f"instrument_id={instrument_id}"
            / f"year={year}"
            / "data.parquet"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(
            rows[columns], schema=schema, preserve_index=False, safe=True
        )
        pq.write_table(table, destination, compression="zstd", version="2.6")


def _validate_authority() -> dict[str, Any]:
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    if authority.get("content_hash") != _content_hash(authority):
        raise ValueError("dividend-basis authority content hash is invalid")
    if authority.get("decision") != (
        "VERSIONED_DIVIDEND_BASIS_REPAIR_AUTHORIZED_FOR_DATA_VALIDATION"
    ):
        raise ValueError("authority does not permit a versioned validation build")
    contract = authority.get("repair_contract", {})
    if (
        contract.get("amount_imputation_permitted") is not False
        or contract.get("original_archive_or_lake_mutation_permitted") is not False
        or contract.get("new_physical_version_required") is not True
    ):
        raise ValueError("authority repair constraints changed")
    return authority


def build() -> dict[str, Any]:
    authority = _validate_authority()
    target = corrected_lake_path(authority)
    if target.exists():
        raise FileExistsError(f"versioned target exists; verify rather than overwrite: {target}")
    base, schema = _read_base_actions()
    raw = _read_raw_actions()
    normalized, summary = normalize_actions(base, raw)
    base_root_before, base_files, base_bytes = _tree_root(BASE_LAKE / "corporate_actions")

    target.parent.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix=".ca-lake-stage-", dir=target.parent))
    stage = stage_parent / "lake_sharadar"
    try:
        for dataset in NON_ACTION_DATASETS:
            shutil.copytree(BASE_LAKE / dataset, stage / dataset, copy_function=os.link)
        _write_actions(normalized, schema, stage / "corporate_actions")
        corrected_root, corrected_files, corrected_bytes = _tree_root(
            stage / "corporate_actions"
        )
        os.replace(stage, target)
    except Exception:
        shutil.rmtree(stage_parent, ignore_errors=True)
        raise
    shutil.rmtree(stage_parent, ignore_errors=True)

    base_root_after, _, _ = _tree_root(BASE_LAKE / "corporate_actions")
    if base_root_before != base_root_after:
        raise RuntimeError("base corporate-action tree changed during versioned build")
    for dataset in NON_ACTION_DATASETS:
        source_leaf = next((BASE_LAKE / dataset).rglob("*.parquet"))
        target_leaf = target / dataset / source_leaf.relative_to(BASE_LAKE / dataset)
        if source_leaf.stat().st_ino != target_leaf.stat().st_ino:
            raise RuntimeError(f"{dataset} was copied instead of hard-linked")

    payload: dict[str, Any] = {
        "schema": "canli.alphac-sharadar-corporate-action-corrected-lake.v1",
        "author": "Arhan Canli",
        "decision": "VERSIONED_CORPORATE_ACTION_LAKE_BUILT_VALIDATION_PENDING",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "base_lake": str(BASE_LAKE.relative_to(REPO)),
        "corrected_lake": str(target.relative_to(REPO)),
        "preregistration_logical_suffix": "data/lake_sharadar",
        "normalization": summary,
        "lineage": {
            "authority_path": str(AUTHORITY.relative_to(REPO)),
            "authority_sha256": _sha256(AUTHORITY),
            "authority_content_hash": authority["content_hash"],
            "raw_actions_archive": str(RAW_ACTIONS.relative_to(REPO)),
            "raw_actions_archive_sha256": _sha256(RAW_ACTIONS),
            "base_corporate_actions_root": base_root_before,
            "base_corporate_action_files": base_files,
            "base_corporate_action_bytes": base_bytes,
            "corrected_corporate_actions_root": corrected_root,
            "corrected_corporate_action_files": corrected_files,
            "corrected_corporate_action_bytes": corrected_bytes,
            "hardlinked_immutable_datasets": list(NON_ACTION_DATASETS),
        },
        "invariants": {
            "original_lake_preserved_by_hash": True,
            "all_base_rows_have_raw_lineage": True,
            "apple_2020_05_08_cash_amount_is_0_82": True,
            "hdb_zero_and_vate_unsupported_rows_absent": True,
            "amounts_imputed": False,
            "non_action_datasets_hardlinked": True,
            "physical_version_is_content_addressed": True,
            "logical_preregistration_path_preserved": str(target).endswith(
                "data/lake_sharadar"
            ),
        },
        "required_next_action": (
            "Run full-lake dividend-price and split-price boundary audits. Do not replay or "
            "promote this lake unless both pass and a separate validation receipt authorizes it."
        ),
        "claim_boundary": (
            "This proves only that a new physical data version was materialized under the sealed "
            "source transformation contract. It opens no returns, spends no hypothesis, and does "
            "not authorize a replay, validate a strategy, or improve any performance statistic."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    payload = build()
    print(json.dumps({"decision": payload["decision"], "content_hash": payload["content_hash"]}))
    print(payload["corrected_lake"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
