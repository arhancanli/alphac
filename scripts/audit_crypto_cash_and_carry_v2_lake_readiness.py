#!/usr/bin/env python3
"""Zero-return data readiness for the cash-and-carry redesign (its draft preregistration).

WHAT IT ASKS. Can the draft's universe rule be satisfied from the data we hold, before anything
is sealed? At every month end of the draft's window it applies the rule exactly as written: a coin
is eligible if its perpetual AND its spot have bars on each of the prior 30 UTC days and its
30-day median daily perpetual quote volume is at least $20 million. The v2a identity selects ten
coins, so the gate is at least ten eligible coins at every month end.

WHAT IT NEVER READS. Funding (the selection signal) and prices (the outcome). Only bar
timestamps and perpetual quote volume, the two inputs of the universe rule. So running it cannot
inform a choice the seal is meant to fix blind. No hypothesis is registered.

    uv run python scripts/audit_crypto_cash_and_carry_v2_lake_readiness.py [--write]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.dataset as ds

ROOT: Final = Path(__file__).resolve().parents[1]
PERP_LAKE: Final = ROOT / "data" / "lake"
SPOT_LAKE: Final = ROOT / "data" / "lake_spot"
SPOT_PROGRESS: Final = SPOT_LAKE / "_ingest" / "progress.json"
OUTPUT: Final = ROOT / "artifacts" / "audit" / "crypto_cash_and_carry_v2_lake_readiness.json"
SCHEMA: Final = "canli.alphac-crypto-cash-and-carry-v2-lake-readiness.v1"
WINDOW: Final = ("2021-06-30", "2026-06-30")
LOOKBACK_DAYS: Final = 30
MIN_MEDIAN_QUOTE_VOLUME: Final = 20_000_000.0
MIN_ELIGIBLE: Final = 10


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def daily_activity(lake: Path, market: str) -> pd.DataFrame:
    """One row per (coin, UTC day) with at least one bar, and that day's quote volume.

    One coin directory at a time: the perpetual lake is years of hourly bars for ~800 coins.
    """
    prefix = f"instrument_id=BINANCE:{market}:"
    frames = []
    for directory in sorted((lake / "ohlcv").glob(f"{prefix}*")):
        table = ds.dataset(directory, format="parquet").to_table(
            columns=["ts_open", "quote_volume"]
        )
        if table.num_rows == 0:
            continue
        bars = table.to_pandas()
        bars["day"] = bars["ts_open"].dt.tz_convert("UTC").dt.normalize()
        daily = bars.groupby("day")["quote_volume"].sum(min_count=1).reset_index()
        daily["coin"] = directory.name.removeprefix(prefix)
        frames.append(daily)
    if not frames:
        return pd.DataFrame({"coin": [], "day": [], "quote_volume": []})
    return pd.concat(frames, ignore_index=True)


def eligible_by_month_end(perp: pd.DataFrame, spot: pd.DataFrame) -> dict[str, list[str]]:
    """The draft's universe rule, applied at each month end of WINDOW."""
    month_ends = pd.date_range(WINDOW[0], WINDOW[1], freq="ME", tz="UTC")
    spot_days = spot.groupby("coin")["day"].apply(set).to_dict()
    perp_by_coin = {
        coin: rows.set_index("day")["quote_volume"] for coin, rows in perp.groupby("coin")
    }
    out: dict[str, list[str]] = {}
    for end in month_ends:
        days = pd.date_range(end - pd.Timedelta(days=LOOKBACK_DAYS - 1), end, freq="D", tz="UTC")
        wanted = set(days)
        eligible = []
        for coin, volume in perp_by_coin.items():
            if not wanted <= spot_days.get(coin, set()):
                continue
            window = volume.reindex(days)
            if window.isna().any():  # a perpetual day with no bar, or no quote volume, fails
                continue
            if float(window.median()) >= MIN_MEDIAN_QUOTE_VOLUME:
                eligible.append(coin)
        out[end.date().isoformat()] = sorted(eligible)
    return out


def build(
    perp: pd.DataFrame, spot: pd.DataFrame, progress: dict[str, Any], perp_symbols: int
) -> dict[str, Any]:
    eligible = eligible_by_month_end(perp, spot)
    counts = {month: len(coins) for month, coins in eligible.items()}
    done = progress.get("done", {})
    rejected = progress.get("rejected", {})
    ingest_complete = bool(progress.get("complete"))
    minimum = min(counts.values()) if counts else 0
    short_months = sorted(month for month, n in counts.items() if n < MIN_ELIGIBLE)
    if not ingest_complete:
        status = "INCOMPLETE_SPOT_INGEST_NOT_ASSESSABLE"
    elif short_months:
        status = "FAIL_UNIVERSE_BELOW_TOP_K"
    else:
        status = "PASS_UNIVERSE_SUPPORTS_TOP_K_EVERY_MONTH"
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "status": status,
        "claim_boundary": (
            "Data readiness only. Reads bar timestamps and perpetual quote volume, never funding "
            "or prices; registers no hypothesis and computes no return. A PASS says the draft's "
            "universe rule can be met, not that the strategy works."
        ),
        "rule": {
            "window_month_ends": list(WINDOW),
            "lookback_days_with_bars_both_legs": LOOKBACK_DAYS,
            "min_median_daily_perp_quote_volume_usd": MIN_MEDIAN_QUOTE_VOLUME,
            "gate_min_eligible_every_month_end": MIN_ELIGIBLE,
            "source": "docs/design/DRAFT_PREREG_CRYPTO_CASH_AND_CARRY_V2.md",
        },
        "spot_ingest": {
            "complete": ingest_complete,
            "symbols_done": len(done),
            "rejected_months": {coin: sorted(months) for coin, months in sorted(rejected.items())},
            "perp_symbols_in_lake": perp_symbols,
        },
        "eligible_count_by_month_end": counts,
        "minimum_eligible": minimum,
        "months_below_gate": short_months,
        "eligible_by_month_end": eligible,
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help=f"write {OUTPUT.relative_to(ROOT)}")
    args = parser.parse_args()
    progress = json.loads(SPOT_PROGRESS.read_text()) if SPOT_PROGRESS.is_file() else {}
    perp = daily_activity(PERP_LAKE, "PERP")
    spot = daily_activity(SPOT_LAKE, "SPOT")
    document = build(perp, spot, progress, perp_symbols=int(perp["coin"].nunique()))
    counts = document["eligible_count_by_month_end"]
    print(
        print(
            f"{document['status']}: min eligible {document['minimum_eligible']} "
            f"over {len(counts)} month ends"
        )
    )
    print("  " + " ".join(f"{m[:7]}={n}" for m, n in list(counts.items())[::6]))
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        print(f"wrote {OUTPUT.relative_to(ROOT)}  {document['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
