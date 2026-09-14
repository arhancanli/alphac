"""One raw SIP daily capture using the existing paper credential profile."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import exchange_calendars as xcals
import httpx
import pandas as pd
from dotenv import dotenv_values

from alphaforge.validation.trend_daily_capture import capture_daily

ROOT = Path(__file__).resolve().parents[1]


async def main():
    now = pd.Timestamp.now(tz="UTC")
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    recent = cal.sessions_in_range((now - pd.Timedelta(days=10)).date(), now.date())
    session = next(s for s in reversed(recent) if cal.session_close(s) < now)
    reservation = (
        ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912/candidate/reservation.json"
    )
    config = json.loads(reservation.read_text())["trial_config"]
    symbols = [i.split(":")[-1].removesuffix("USD") for i in config["instrument_ids"]]
    values = dotenv_values(Path.home() / ".config/alphaforge/alpaca_equity.env")
    if values.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/") != (
        "https://paper-api.alpaca.markets"
    ):
        raise ValueError("Paper profile required")
    out = ROOT / "evidence" / ("alphatrend-daily-capture-" + now.strftime("%Y%m%dT%H%M%SZ"))
    async with httpx.AsyncClient(
        headers={
            "APCA-API-KEY-ID": values["APCA_API_KEY_ID"],
            "APCA-API-SECRET-KEY": values["APCA_API_SECRET_KEY"],
        },
        timeout=8,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        result = await capture_daily(
            client, out, session_ms=int(session.value // 1_000_000), symbols=symbols
        )
    bindings = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__),
            reservation,
            ROOT / "src/alphaforge/validation/trend_daily_capture.py",
        ]
    }
    (out / "bindings.json").write_text(json.dumps(bindings, indent=2) + "\n")
    print(
        json.dumps(
            {
                "directory": str(out),
                "bars": len(result["rows"]),
                "runtime_ready": result["runtime_ready"],
                "blockers": result["blockers"],
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
