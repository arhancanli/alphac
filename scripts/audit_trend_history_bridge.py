"""Bounded raw SIP acquisition and adjusted-lake overlap audit; no signal/return trial."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import httpx
import pandas as pd
from dotenv import dotenv_values

from alphaforge.validation.trend_daily_capture import ENDPOINT
from alphaforge.validation.trend_history_capture import normalize_history

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/alphatrend-history-bridge-20260912"
SOURCE = ROOT / "artifacts/analysis/alphatrend_directional_20260912_attempt2"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


async def main():
    OUT.mkdir(exist_ok=False)
    reservation = ROOT / (
        "artifacts/analysis/alphatrend_causal_continuous_20260912/candidate/reservation.json"
    )
    config = json.loads(reservation.read_text())["trial_config"]
    symbols = sorted(i.split(":")[-1].removesuffix("USD") for i in config["instrument_ids"])
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    grid = cal.sessions_in_range("2026-08-03", "2026-09-11")
    sessions = [int(s.value // 1_000_000) for s in grid]
    inputs = sorted((SOURCE / "lake_mf/ohlcv_1d").glob("*/year=2026/*.parquet"))
    frames = []
    for path in inputs:
        frame = pd.read_parquet(path)
        frame["symbol"] = frame.instrument_id.str.split(":").str[-1].str.removesuffix("USD")
        frame["session_ms"] = frame.ts_open.dt.as_unit("ms").astype("int64")
        frames.append(frame)
    historical = pd.concat(frames, ignore_index=True)
    assert set(historical.symbol) == set(symbols)
    historical = historical[historical.session_ms.isin(sessions)]
    assert not historical.duplicated(["symbol", "session_ms"]).any()
    loader = Path("/Users/arhancanli/alphaforge/scripts/mf_etf_load.py")
    shutil.copy2(loader, OUT / "historical_loader_source.py")
    bindings = {
        str(p): sha(p)
        for p in [
            *inputs,
            reservation,
            loader,
            Path(__file__),
            ROOT / "src/alphaforge/validation/trend_history_capture.py",
            ROOT / "src/alphaforge/validation/trend_daily_capture.py",
            SOURCE / "input_manifest.json",
        ]
    }
    write(
        "protocol.json",
        {
            "scope": "ACQUISITION_AND_PRICE_CONVENTION_DIAGNOSTIC",
            "start": "2026-08-03",
            "end_exclusive": "2026-09-12",
            "symbols": symbols,
            "sessions": sessions,
            "max_requests": 1,
            "retries": 0,
            "adjustment": "raw",
            "feed": "sip",
            "new_hypotheses": 0,
            "union_hypotheses": 238,
            "bindings": bindings,
            "splice_authorized_by_this_audit": False,
            "comparison": "Exact overlap and descriptive level/return differences; no tuning",
        },
    )
    values = dotenv_values(Path.home() / ".config/alphaforge/alpaca_equity.env")
    assert values.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/") == (
        "https://paper-api.alpaca.markets"
    )
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": "2026-08-03T00:00:00Z",
        "end": "2026-09-12T00:00:00Z",
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
        raise ValueError("SIP history request failed")
    fresh = pd.DataFrame(normalize_history(response.json(), sessions=sessions, symbols=symbols))
    fresh.to_parquet(OUT / "raw_history.parquet", index=False)
    joined = historical.merge(
        fresh, on=["symbol", "session_ms"], suffixes=("_lake", "_sip"), validate="one_to_one"
    ).sort_values(["symbol", "session_ms"])
    for field in ["open", "high", "low", "close", "volume"]:
        joined[field + "_ratio"] = joined[field + "_lake"] / joined[field + "_sip"]
    joined["close_return_lake"] = joined.groupby("symbol").close_lake.pct_change(fill_method=None)
    joined["close_return_sip"] = joined.groupby("symbol").close_sip.pct_change(fill_method=None)
    joined["close_return_difference_bps"] = (
        joined.close_return_lake - joined.close_return_sip
    ) * 10000
    joined.to_parquet(OUT / "overlap.parquet", index=False)
    summaries = []
    for symbol, part in joined.groupby("symbol"):
        summaries.append(
            {
                "symbol": symbol,
                "overlap_sessions": len(part),
                "median_lake_to_raw_close": float(part.close_ratio.median()),
                "min_lake_to_raw_close": float(part.close_ratio.min()),
                "max_lake_to_raw_close": float(part.close_ratio.max()),
                "max_absolute_return_difference_bps": float(
                    part.close_return_difference_bps.abs().max()
                ),
            }
        )
    last = int(historical.session_ms.max())
    missing = fresh[fresh.session_ms > last]
    missing.to_parquet(OUT / "missing_prefix_raw_bars.parquet", index=False)
    result = {
        "raw_bars": len(fresh),
        "sessions": len(sessions),
        "symbols": len(symbols),
        "last_frozen_session": str(pd.Timestamp(last, unit="ms").date()),
        "missing_prefix_sessions_acquired": int(missing.session_ms.nunique()),
        "missing_prefix_raw_bars_acquired": len(missing),
        "overlap_rows": len(joined),
        "historical_convention": "Yahoo adjclose/close applied to OHL, close=adjclose",
        "fresh_convention": "SIP adjustment=raw",
        "per_symbol": summaries,
        "history_appended": False,
        "runtime_ready": False,
        "remaining": [
            "Point-in-time split/dividend bridge",
            "Full-prefix provenance",
            "Clock attestation",
            "Producer binding and account context",
        ],
        "new_hypotheses": 0,
        "union_hypotheses": 238,
    }
    for name, digest in bindings.items():
        assert sha(Path(name)) == digest, name
    write("result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        if OUT.exists() and not (OUT / "failure.json").exists():
            write("failure.json", {"error_type": type(exc).__name__, "runtime_ready": False})
        raise
