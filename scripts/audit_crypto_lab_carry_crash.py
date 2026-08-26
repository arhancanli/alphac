#!/usr/bin/env python3
"""Seal the LABUSDT carry-crash incident from immutable local execution evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var/trading_crypto_perp.sqlite"
FUNDING_PATH = (
    ROOT / "data/lake/funding/instrument_id=BINANCE:PERP:LABUSDT/year=2026/data.parquet"
)
OUTPUT_PATH = ROOT / "artifacts/engineering/crypto_lab_carry_crash_incident.json"
INSTRUMENT = "BINANCE:PERP:LABUSDT"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def analyze(fills: list[dict[str, Any]], funding: pd.DataFrame) -> dict[str, Any]:
    ordered = sorted(fills, key=lambda row: int(row["ts"]))
    if len(ordered) != 3:
        raise ValueError(f"expected the frozen three-fill LAB sequence, got {len(ordered)}")
    entry, close, reversal = ordered
    if not (
        entry["side"] == "buy"
        and close["side"] == "sell"
        and reversal["side"] == "sell"
        and float(entry["qty"]) == float(close["qty"])
    ):
        raise ValueError("LAB fill sequence is not the expected long-close-short reversal")

    entry_price = float(entry["price"])
    close_price = float(close["price"])
    qty = float(entry["qty"])
    gross_pnl = qty * (close_price - entry_price)
    closing_fees = float(entry["fee_quote"]) + float(close["fee_quote"])
    net_pnl = gross_pnl - closing_fees

    frame = funding.copy()
    frame["ts_funding"] = pd.to_datetime(frame["ts_funding"], utc=True)
    entry_time = pd.to_datetime(int(entry["ts"]), unit="ms", utc=True)
    close_time = pd.to_datetime(int(close["ts"]), unit="ms", utc=True)
    held = frame[(frame["ts_funding"] >= entry_time) & (frame["ts_funding"] <= close_time)]
    negative = held[held["rate"] < 0]
    nonnegative = held[held["rate"] >= 0]
    first_nonnegative = (
        None
        if nonnegative.empty
        else nonnegative["ts_funding"].min().isoformat().replace("+00:00", "Z")
    )

    return {
        "verdict": "GENUINE_MARKET_CRASH_NOT_CONTRACT_IDENTITY_DEFECT",
        "instrument": INSTRUMENT,
        "execution_sequence": {
            "long_entry": entry,
            "long_close": close,
            "short_reversal": reversal,
        },
        "long_episode": {
            "entry_price": entry_price,
            "close_price": close_price,
            "price_return": close_price / entry_price - 1.0,
            "quantity": qty,
            "gross_price_pnl_quote": gross_pnl,
            "gross_price_pnl_quote_rounded_2dp": round(gross_pnl, 2),
            "absolute_gross_price_loss_quote_rounded_2dp": abs(round(gross_pnl, 2)),
            "entry_and_close_fees_quote": closing_fees,
            "net_price_pnl_after_entry_and_close_fees_quote": net_pnl,
            "net_price_pnl_after_entry_and_close_fees_quote_rounded_2dp": round(net_pnl, 2),
            "absolute_net_price_loss_quote_rounded_2dp": abs(round(net_pnl, 2)),
        },
        "funding_regime_while_held": {
            "observations": len(held),
            "mean_rate": float(held["rate"].mean()),
            "minimum_rate": float(held["rate"].min()),
            "maximum_rate": float(held["rate"].max()),
            "negative_observations": len(negative),
            "nonnegative_observations": len(nonnegative),
            "first_nonnegative_settlement": first_nonnegative,
            "interpretation": (
                "The carry signal entered long during negative funding; funding later changed "
                "sign and the scheduled rebalance closed the long and opened a short."
            ),
        },
        "forward_record_relation": {
            "lab_long_closed_utc": pd.to_datetime(int(close["ts"]), unit="ms", utc=True)
            .isoformat()
            .replace("+00:00", "Z"),
            "flagship_forward_record_starts": "2026-08-07",
            "classification": "PRE_FLAGSHIP_WINDOW_DOES_NOT_EXPLAIN_CURRENT_FORWARD_LOSS",
        },
        "decision": "PRESERVE_LOSS_NO_PRICE_JUMP_GUARD_NO_WEIGHT_CHANGE",
    }


def build_document() -> dict[str, Any]:
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        fills = [
            dict(row)
            for row in connection.execute(
                "SELECT client_order_id, instrument_id, side, qty, price, fee_quote, ts "
                "FROM fills WHERE instrument_id = ? ORDER BY ts, fill_id",
                (INSTRUMENT,),
            ).fetchall()
        ]
    funding = pd.read_parquet(FUNDING_PATH)
    result = analyze(fills, funding)
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-lab-carry-crash-incident.v1",
        "author": "Arhan Canli",
        "claim_boundary": (
            "Forensic description of one paper-traded LABUSDT episode. It spends zero return "
            "hypotheses, does not estimate Sharpe or expected performance, does not authorize a "
            "strategy change, and does not rewrite the published equity record."
        ),
        "source_bindings": {
            "paper_execution_database": {
                "path": "var/trading_crypto_perp.sqlite",
                "sha256": _sha256(DB_PATH.read_bytes()),
            },
            "point_in_time_funding": {
                "path": (
                    "data/lake/funding/instrument_id=BINANCE:PERP:LABUSDT/"
                    "year=2026/data.parquet"
                ),
                "sha256": _sha256(FUNDING_PATH.read_bytes()),
            },
        },
        "independent_market_context": [
            {
                "url": "https://chartexchange.com/symbol/crypto-labusdt/historical/",
                "supports": "independent dated prices during the July 2026 collapse",
            },
            {
                "url": "https://phemex.com/announcements/phemex-will-delist-labusdt694",
                "supports": "contemporaneous venue response to LABUSDT market risk",
            },
        ],
        "observability_correction": {
            "historical_gap": (
                "Position snapshots retained quantity and average entry but not the exact cycle "
                "mark or instrument-level unrealized PnL. Historical attribution cannot be "
                "fabricated from aggregate equity."
            ),
            "prospective_fix": (
                "Future paper cycles persist exact order-book mark, mark source, market value, "
                "and unrealized PnL through an additive nullable schema migration."
            ),
        },
        **result,
    }
    document["content_hash"] = f"sha256:{_sha256(_canonical(document))}"
    return document


def main() -> None:
    document = build_document()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
