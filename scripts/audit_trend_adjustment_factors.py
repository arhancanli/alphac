"""Extend Treasury ETF overlap across monthly distributions; descriptive data audit."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import httpx
import pandas as pd
from dotenv import dotenv_values

from alphaforge.validation.trend_daily_capture import ENDPOINT
from alphaforge.validation.trend_history_capture import normalize_history

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-adjustment-factors-20260912"
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2/lake_mf/ohlcv_1d"
SYMBOLS = ["IEF", "SHY", "TLT"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


async def main():
    OUT.mkdir(exist_ok=False)
    paths = [
        next((SOURCE / f"instrument_id=XUSE:CASH:{s}USD/year=2026").glob("*.parquet"))
        for s in SYMBOLS
    ]
    write(
        "protocol.json",
        {
            "scope": "PRICE_ADJUSTMENT_DIAGNOSTIC_NO_STRATEGY_RETURNS",
            "symbols": SYMBOLS,
            "start": "2026-05-01",
            "end_exclusive": "2026-08-22",
            "requests": 1,
            "retries": 0,
            "feed": "sip",
            "adjustment": "raw",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
            "interpretation": "Ratios are descriptive, not authenticated corporate actions",
            "bindings": {
                str(p): sha(p)
                for p in [
                    Path(__file__),
                    *paths,
                    ROOT / "src/alphaforge/validation/trend_history_capture.py",
                    ROOT / "src/alphaforge/validation/trend_daily_capture.py",
                ]
            },
        },
    )
    values = dotenv_values(Path.home() / ".config/alphaforge/alpaca_equity.env")
    assert values.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/") == (
        "https://paper-api.alpaca.markets"
    )
    params = {
        "symbols": ",".join(SYMBOLS),
        "timeframe": "1Day",
        "start": "2026-05-01T00:00:00Z",
        "end": "2026-08-22T00:00:00Z",
        "feed": "sip",
        "adjustment": "raw",
        "limit": 10000,
    }
    write(
        "request.json",
        {
            "url": ENDPOINT,
            "method": "GET",
            "params": params,
            "requested_at_local": datetime.now(UTC).isoformat(),
        },
    )
    async with httpx.AsyncClient(
        headers={
            "APCA-API-KEY-ID": values["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": values["APCA_API_SECRET_KEY"],
        },
        timeout=15,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        response = await client.get(ENDPOINT, params=params)
    (OUT / "response.bin").write_bytes(response.content)
    write(
        "receipt.json",
        {
            "http_status": response.status_code,
            "received_at_local": datetime.now(UTC).isoformat(),
            "server_date": response.headers.get("date"),
            "sha256": sha(OUT / "response.bin"),
        },
    )
    if response.status_code != 200:
        raise ValueError("History request failed")
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    grid = cal.sessions_in_range("2026-05-01", "2026-08-21")
    sessions = [int(s.value // 1_000_000) for s in grid]
    raw = pd.DataFrame(normalize_history(response.json(), sessions=sessions, symbols=SYMBOLS))
    raw.to_parquet(OUT / "raw_history.parquet", index=False)
    summaries = []
    overlaps = []
    for symbol, path in zip(SYMBOLS, paths, strict=True):
        old = pd.read_parquet(path)
        old["session_ms"] = old.ts_open.dt.as_unit("ms").astype("int64")
        part = old.merge(
            raw[raw.symbol == symbol],
            on="session_ms",
            suffixes=("_lake", "_raw"),
            validate="one_to_one",
        ).sort_values("session_ms")
        assert len(part) == len(sessions)
        part["lake_to_raw_factor"] = part.close_lake / part.close_raw
        part["factor_change_bps"] = part.lake_to_raw_factor.pct_change(fill_method=None) * 10000
        part["return_difference_bps"] = (
            part.close_lake.pct_change(fill_method=None)
            - part.close_raw.pct_change(fill_method=None)
        ) * 10000
        overlaps.append(part)
        changes = part.loc[
            part.factor_change_bps.abs() > 1,
            ["session_ms", "lake_to_raw_factor", "factor_change_bps"],
        ]
        summaries.append(
            {
                "symbol": symbol,
                "sessions": len(part),
                "minimum_factor": float(part.lake_to_raw_factor.min()),
                "maximum_factor": float(part.lake_to_raw_factor.max()),
                "max_absolute_return_difference_bps": float(part.return_difference_bps.abs().max()),
                "factor_changes_above_one_bp": changes.to_dict(orient="records"),
            }
        )
    pd.concat(overlaps).to_parquet(OUT / "overlap.parquet", index=False)
    result = {
        "raw_bars": len(raw),
        "per_symbol": summaries,
        "splice_allowed": False,
        "reason": "Historical total-return scale requires action-aware continuation",
        "action_provenance_established": False,
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    write("result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        if OUT.exists() and not (OUT / "failure.json").exists():
            write("failure.json", {"error_type": type(exc).__name__})
        raise
