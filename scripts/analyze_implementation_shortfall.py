#!/usr/bin/env python3
"""Implementation shortfall of the live paper equity sleeves, decomposed and measured.

WHY. The cost model charges a half-spread and an impact term on every filled dollar. Whether that
is realistic needs the classic decomposition (Perold 1988) against the price the decision was
taken at. The fills table records only a padded marketable limit, which is why the earlier
realism study (analyze_cost_model_realism.py) called slippage "not measurable". It is measurable
from the lake: orders are submitted before the open on the previous session's close, so that
close IS the decision price, and the session's open and close are in `data/lake/ohlcv_1d`.

THE THREE PARTS, per order, in basis points of its decision notional, positive = cost:
- delay:        decision close -> session open (the overnight gap the schedule accepts);
- execution:    session open -> fill price (filled orders only);
- opportunity:  decision close -> session close, for the unfilled quantity (missed trades).
Sign s = +1 for a buy, -1 for a sell: a cost is s * (later price - earlier price) / decision.

GUARDS. An order whose decision-to-session move exceeds 30% is excluded and counted (a split or a
bad bar would pose as slippage); so is an order with no bar. Reads the trading databases and the
lake read-only. Registers no hypothesis and changes no cost parameter. 0 trials.

    uv run python scripts/analyze_implementation_shortfall.py [--write]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT: Final = Path(__file__).resolve().parents[1]
LAKE_1D: Final = ROOT / "data" / "lake" / "ohlcv_1d"
SLEEVES: Final = {
    "alphamax": ROOT / "var/trading_equity.sqlite",
    "alphavintage": ROOT / "var/trading_alphavintage.sqlite",
}
OUTPUT: Final = ROOT / "artifacts" / "analysis" / "implementation_shortfall" / "result.json"
MAX_ABS_MOVE: Final = 0.30
FILLED: Final = "filled"


def load_orders(db: Path) -> pd.DataFrame:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return pd.read_sql_query(
            "select o.client_order_id, o.ts as order_ts, o.instrument_id, o.side, o.qty, "
            "f.status, f.ts as fill_ts, f.filled_qty, f.fill_price "
            "from orders o join fills f using(client_order_id)",
            conn,
        )


def load_bars(instrument_ids: list[str]) -> dict[str, pd.DataFrame]:
    bars: dict[str, pd.DataFrame] = {}
    for instrument in sorted(set(instrument_ids)):
        directory = LAKE_1D / f"instrument_id={instrument}"
        if not directory.is_dir():
            continue
        frame = (
            ds.dataset(directory, format="parquet")
            .to_table(columns=["ts_open", "open", "close"])
            .to_pandas()
        )
        frame["day"] = frame["ts_open"].dt.tz_convert("UTC").dt.date
        bars[instrument] = frame.drop_duplicates("day", keep="last").set_index("day").sort_index()
    return bars


def decompose(
    orders: pd.DataFrame, bars: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """One row per usable order with its delay, execution and opportunity cost in bps."""
    rows, excluded = [], {"no_bar": 0, "implausible_move": 0, "zero_quantity": 0}
    for order in orders.itertuples(index=False):
        if not order.qty:
            excluded["zero_quantity"] += 1
            continue
        frame = bars.get(order.instrument_id)
        session = dt.datetime.fromtimestamp(order.fill_ts / 1000, dt.UTC).date()
        if frame is None or session not in frame.index:
            excluded["no_bar"] += 1
            continue
        prior = frame.index[frame.index < session]
        if len(prior) == 0:
            excluded["no_bar"] += 1
            continue
        decision = float(frame.loc[prior[-1], "close"])
        session_open = float(frame.loc[session, "open"])
        session_close = float(frame.loc[session, "close"])
        if (
            decision <= 0
            or max(abs(session_open / decision - 1), abs(session_close / decision - 1))
            > MAX_ABS_MOVE
        ):
            excluded["implausible_move"] += 1
            continue
        sign = 1.0 if order.side == "buy" else -1.0
        filled_fraction = min(1.0, float(order.filled_qty or 0.0) / float(order.qty))
        filled = order.status == FILLED and order.fill_price and filled_fraction > 0
        execution = (
            sign * (float(order.fill_price) - session_open) / decision * 1e4 if filled else 0.0
        )
        delay = sign * (session_open - decision) / decision * 1e4
        opportunity = sign * (session_close - decision) / decision * 1e4
        rows.append(
            {
                "status": order.status,
                "decision_notional": decision * float(order.qty),
                "filled_fraction": filled_fraction if filled else 0.0,
                "delay_bps": delay,
                "execution_bps": execution,
                "opportunity_bps": opportunity,
            }
        )
    return pd.DataFrame(rows), excluded


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    """Notional-weighted parts; each weighted by the quantity it applies to."""
    if frame.empty:
        return {"orders": 0}
    notional = frame["decision_notional"]
    filled_w = notional * frame["filled_fraction"]
    unfilled_w = notional * (1 - frame["filled_fraction"])
    total = float(notional.sum())

    def wavg(values: pd.Series, weights: pd.Series) -> float | None:
        w = float(weights.sum())
        return None if w == 0 else float((values * weights).sum() / w)

    delay_on_filled = wavg(frame["delay_bps"], filled_w)
    execution_on_filled = wavg(frame["execution_bps"], filled_w)
    opportunity_on_unfilled = wavg(frame["opportunity_bps"], unfilled_w)
    shortfall = (
        float((frame["delay_bps"] + frame["execution_bps"]).mul(filled_w).sum())
        + float(frame["opportunity_bps"].mul(unfilled_w).sum())
    ) / total
    return {
        "orders": len(frame),
        "fill_rate_by_count": float((frame["filled_fraction"] > 0).mean()),
        "fill_rate_by_notional": float(filled_w.sum() / total),
        "decision_notional_usd": total,
        "delay_bps_on_filled": delay_on_filled,
        "execution_bps_on_filled": execution_on_filled,
        "opportunity_bps_on_unfilled": opportunity_on_unfilled,
        "implementation_shortfall_bps_of_decision_notional": shortfall,
        "execution_bps_percentiles_filled": {
            q: float(np.percentile(frame.loc[frame["filled_fraction"] > 0, "execution_bps"], q))
            for q in (10, 50, 90)
        }
        if (frame["filled_fraction"] > 0).any()
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {
        "schema": "canli.alphac-implementation-shortfall.v1",
        "claim_boundary": (
            "Paper fills from the broker's paper engine, decomposed against the previous session's "
            "close as the decision price. Paper fills are not guaranteed to match live fills. "
            "Registers no hypothesis; changes no cost parameter. 0 trials."
        ),
        "sign_convention": "positive = cost, basis points of decision notional",
        "sleeves": {},
    }
    for sleeve, db in SLEEVES.items():
        if not db.is_file():
            result["sleeves"][sleeve] = {"database_exists": False}
            continue
        orders = load_orders(db)
        frame, excluded = decompose(orders, load_bars(orders["instrument_id"].tolist()))
        result["sleeves"][sleeve] = {
            **summarize(frame),
            "excluded": excluded,
            "orders_read": len(orders),
        }
    print(json.dumps(result["sleeves"], indent=2))
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
