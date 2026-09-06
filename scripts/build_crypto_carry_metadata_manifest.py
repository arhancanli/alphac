#!/usr/bin/env python3
"""Seal the full frozen instrument metadata required by a portable crypto-carry replay."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Final, cast

ROOT: Final = Path(__file__).resolve().parents[1]
PORTABILITY: Final = ROOT / "artifacts/publication/crypto_carry_portability_manifest.json"
OPS_DB: Final = ROOT / "var/ops.sqlite"
OUTPUT: Final = ROOT / "artifacts/publication/crypto_carry_instrument_metadata.json"
FIELDS: Final = (
    "instrument_id",
    "asset_class",
    "market_type",
    "base",
    "quote",
    "tick_size",
    "lot_size",
    "min_qty",
    "min_notional",
    "contract_multiplier",
    "can_short",
    "maker_fee_bps",
    "taker_fee_bps",
    "funding_interval_hours",
    "listed_ts",
    "delisted_ts",
    "valid_from_ms",
    "valid_to_ms",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def build() -> dict[str, Any]:
    portability = json.loads(PORTABILITY.read_text())
    ids = sorted(row["instrument_id"] for row in portability["records"])
    placeholders = ",".join("?" for _ in ids)
    query = f"""
        SELECT {", ".join(FIELDS)}
        FROM instruments_v
        WHERE valid_to_ms IS NULL AND instrument_id IN ({placeholders})
        ORDER BY instrument_id
    """
    with sqlite3.connect(OPS_DB) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute(query, ids).fetchall()]
    for row in rows:
        row["can_short"] = bool(row["can_short"])
    failures = []
    if len(rows) != len(ids):
        failures.append("NOT_ALL_SELECTED_INSTRUMENTS_HAVE_CURRENT_METADATA")
    if [row["instrument_id"] for row in rows] != ids:
        failures.append("METADATA_ID_SET_DIFFERS_FROM_SELECTED_RUN")
    if any(row["asset_class"] != "crypto_perp" for row in rows):
        failures.append("NON_CRYPTO_PERP_METADATA_IN_SELECTED_RUN")
    if any(row["market_type"] != "perp" for row in rows):
        failures.append("NON_PERPETUAL_METADATA_IN_SELECTED_RUN")
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-instrument-metadata.v1",
        "author": "Arhan Canli",
        "status": "PASS_FULL_FROZEN_LOCAL_METADATA_INVENTORY" if not failures else "FAIL",
        "passes": not failures,
        "portability_binding": {
            "path": str(PORTABILITY.relative_to(ROOT)),
            "sha256": _sha256(PORTABILITY),
            "content_hash": portability["content_hash"],
        },
        "source_binding": {
            "path": str(OPS_DB.relative_to(ROOT)),
            "sha256": _sha256(OPS_DB),
            "table": "instruments_v",
            "selection": "valid_to_ms IS NULL for the selected 58-instrument run",
        },
        "field_names": list(FIELDS),
        "records": rows,
        "totals": {
            "records": len(rows),
            "delisted_instruments": sum(row["delisted_ts"] is not None for row in rows),
            "four_hour_funding_instruments": sum(
                row["funding_interval_hours"] == 4 for row in rows
            ),
            "eight_hour_funding_instruments": sum(
                row["funding_interval_hours"] == 8 for row in rows
            ),
        },
        "fresh_exchange_metadata_reacquired": False,
        "full_walkforward_replayed": False,
        "independent_replication": False,
        "failures": failures,
        "claim_boundary": (
            "This packet seals the full current SCD2 rows used to reconstruct the selected "
            "crypto-carry instrument store. It is frozen local metadata, not a fresh historical "
            "exchangeInfo acquisition, and by itself does not recreate universe membership, "
            "replay the strategy, or constitute independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def validate_published() -> dict[str, Any]:
    document = json.loads(OUTPUT.read_text())
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError("published crypto-carry metadata hash is invalid")
    current = build()
    if document != current:
        # This packet is sealed into the prospective trial.  Preserve its exact
        # historical portability binding when a later inventory refresh changes
        # only that binding; all selected metadata rows and claim fields must
        # still reproduce byte-for-byte at the JSON-value level.
        historical_body = {
            key: value
            for key, value in document.items()
            if key not in {"content_hash", "portability_binding", "source_binding"}
        }
        current_body = {
            key: value
            for key, value in current.items()
            if key not in {"content_hash", "portability_binding", "source_binding"}
        }
        if historical_body != current_body:
            raise RuntimeError("published crypto-carry metadata packet is substantively stale")
        historical_source = {
            key: value for key, value in document["source_binding"].items() if key != "sha256"
        }
        current_source = {
            key: value for key, value in current["source_binding"].items() if key != "sha256"
        }
        if historical_source != current_source:
            raise RuntimeError("published crypto-carry metadata source contract changed")
        portability = json.loads(PORTABILITY.read_text())
        if portability.get("content_hash") != _content_hash(portability):
            raise RuntimeError("current portability manifest hash is invalid")
        if [row["instrument_id"] for row in document["records"]] != [
            row["instrument_id"] for row in portability["records"]
        ]:
            raise RuntimeError("current portability instrument selection changed")
    return cast(dict[str, Any], document)


def main() -> None:
    document = build()
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{document['status']}: {OUTPUT}")
    print(json.dumps(document["totals"], indent=2, sort_keys=True))
    print(f"content_hash: {document['content_hash']}")
    if not document["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
