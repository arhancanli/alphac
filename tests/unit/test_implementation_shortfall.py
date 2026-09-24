"""Implementation shortfall splits into delay, execution and opportunity with the right signs."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "implementation_shortfall_under_test", ROOT / "scripts" / "analyze_implementation_shortfall.py"
)
assert _SPEC and _SPEC.loader
IS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(IS)

DAY0, DAY1 = dt.date(2026, 9, 21), dt.date(2026, 9, 22)
FILL_TS = int(dt.datetime(2026, 9, 22, 13, 30, tzinfo=dt.UTC).timestamp() * 1000)


def _bars(close0: float, open1: float, close1: float) -> dict[str, pd.DataFrame]:
    frame = pd.DataFrame({"open": [close0, open1], "close": [close0, close1]}, index=[DAY0, DAY1])
    return {"X": frame}


def _order(side: str, status: str, fill_price: float | None, filled_qty: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "client_order_id": "o",
                "order_ts": FILL_TS - 3_600_000,
                "instrument_id": "X",
                "side": side,
                "qty": 10.0,
                "status": status,
                "fill_ts": FILL_TS,
                "filled_qty": filled_qty,
                "fill_price": fill_price,
            }
        ]
    )


def test_a_filled_buy_pays_the_gap_and_its_own_price_versus_the_open() -> None:
    frame, _ = IS.decompose(_order("buy", "filled", 101.5, 10.0), _bars(100.0, 101.0, 103.0))
    row = frame.iloc[0]
    assert round(row["delay_bps"], 6) == 100.0  # 100 -> 101 against a buyer
    assert round(row["execution_bps"], 6) == 50.0  # paid 101.5 against a 101 open
    summary = IS.summarize(frame)
    assert round(summary["implementation_shortfall_bps_of_decision_notional"], 6) == 150.0


def test_an_unfilled_buy_is_charged_the_move_it_missed_and_a_sell_reverses_the_sign() -> None:
    missed, _ = IS.decompose(_order("buy", "expired", None, 0.0), _bars(100.0, 102.0, 104.0))
    summary = IS.summarize(missed)
    assert summary["fill_rate_by_count"] == 0.0
    assert round(summary["opportunity_bps_on_unfilled"], 6) == 400.0
    assert round(summary["implementation_shortfall_bps_of_decision_notional"], 6) == 400.0
    sold, _ = IS.decompose(_order("sell", "expired", None, 0.0), _bars(100.0, 102.0, 104.0))
    assert round(IS.summarize(sold)["opportunity_bps_on_unfilled"], 6) == -400.0


def test_a_split_sized_move_or_a_missing_bar_is_excluded_and_counted() -> None:
    frame, excluded = IS.decompose(_order("buy", "filled", 50.5, 10.0), _bars(100.0, 50.0, 51.0))
    assert frame.empty and excluded["implausible_move"] == 1
    frame, excluded = IS.decompose(_order("buy", "filled", 101.0, 10.0), {})
    assert frame.empty and excluded["no_bar"] == 1


def test_the_backtest_benchmark_pays_the_gap_so_the_excess_is_the_order_policys_cost() -> None:
    missed, _ = IS.decompose(_order("buy", "expired", None, 0.0), _bars(100.0, 102.0, 104.0))
    summary = IS.summarize(missed)
    # At the open it would have paid the 200 bp gap plus the half-spread; missing it cost 400.
    half = IS.AT_OPEN_HALF_SPREAD_BPS
    assert round(summary["at_open_benchmark_bps"], 6) == round(200.0 + half, 6)
    assert round(summary["excess_over_at_open_fill_bps"], 6) == round(400.0 - 200.0 - half, 6)
