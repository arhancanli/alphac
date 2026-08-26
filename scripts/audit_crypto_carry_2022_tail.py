#!/usr/bin/env python3
"""Reproduce the selected crypto-carry artifact's 2022 tail statistics.

The public paper cites the 2022 Sharpe because the full-history headline hides the family-defining
LUNA/FTX stress. This audit derives that number from the persisted hourly equity curve using the
same UTC-daily, 365-day metric functions as the engine and emits a deterministic public artifact.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq

from alphaforge.analytics.metrics import DAYS_PER_YEAR, daily_returns, max_drawdown, sharpe

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "artifacts" / "walkforward" / "crypto_carry_wk" / "equity.parquet"
OUTPUT: Final[Path] = REPO / "artifacts" / "research" / "crypto_carry_2022_tail.json"
START: Final[dt.datetime] = dt.datetime(2022, 1, 1, tzinfo=dt.UTC)
END: Final[dt.datetime] = dt.datetime(2023, 1, 1, tzinfo=dt.UTC)


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def build() -> dict[str, Any]:
    table = pq.read_table(SOURCE, columns=["ts", "equity"])  # type: ignore[no-untyped-call]
    equity = pd.Series(
        table.column("equity").to_numpy(),
        index=pd.Index(table.column("ts").to_numpy(), name="ts"),
        name="equity",
    )
    start_ms = int(START.timestamp() * 1000)
    end_ms = int(END.timestamp() * 1000)
    segment = equity[(equity.index >= start_ms) & (equity.index < end_ms)]
    returns = daily_returns(segment)
    drawdown, peak_ms, trough_ms = max_drawdown(segment)
    sr = sharpe(returns, DAYS_PER_YEAR)
    return {
        "schema": "canli.crypto-carry-tail-audit.v1",
        "claim_boundary": (
            "Derived historical simulation statistic for the selected artifact; not forward, "
            "live-money, or externally attested performance."
        ),
        "source": {
            "path": str(SOURCE.relative_to(REPO)),
            "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        },
        "window": {
            "requested_start": START.date().isoformat(),
            "requested_end_exclusive": END.date().isoformat(),
            "first_observation": _iso(int(segment.index[0])),
            "last_observation": _iso(int(segment.index[-1])),
            "hourly_equity_points": len(segment),
            "daily_return_observations": len(returns),
        },
        "method": {
            "equity_aggregation": "UTC day last observation",
            "return_type": "simple percentage return",
            "annualization_days": DAYS_PER_YEAR,
            "sharpe_formula": "mean(daily_return)/sample_std(daily_return)*sqrt(365)",
        },
        "result": {
            "annualized_sharpe": sr,
            "annualized_sharpe_rounded_2dp": round(sr, 2),
            "total_return": float(segment.iloc[-1] / segment.iloc[0] - 1.0),
            "maximum_drawdown": drawdown,
            "drawdown_peak": _iso(peak_ms),
            "drawdown_trough": _iso(trough_ms),
        },
    }


def main() -> None:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
