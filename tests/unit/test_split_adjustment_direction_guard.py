"""The engine and the lakes must agree on what a split ratio means, checked against each other
on a real split rather than each against itself (feedback: a gate nobody checked against the
other gate). Apple's 2020-08-31 four-for-one is stored as 4.0 in every lake; the adjusted close
the day before must be the raw 499.23 divided by four, not multiplied."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from alphaforge.core.time import Timeframe
from alphaforge.features.library.equity_price import adjusted_close

ROOT = Path(__file__).resolve().parents[2]
AAPL = "XUSE:CASH:AAPLUSD"
DAY = Timeframe.D1.ms


def _ms(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() * 1000)


def test_a_vendor_factor_of_four_divides_the_pre_ex_price() -> None:
    """Pure engine check with the vendor convention: raw 499.23 before, 129.04 after."""
    idx = [_ms(dt.date(2020, 8, 27)), _ms(dt.date(2020, 8, 28)), _ms(dt.date(2020, 8, 31))]
    raw = pd.DataFrame({AAPL: [500.04, 499.23, 129.04]}, index=idx)
    actions = pd.DataFrame(
        {
            "instrument_id": [AAPL],
            "ex_date": [idx[2]],
            "available_at": [idx[2]],
            "action_type": ["split"],
            "ratio": [4.0],
            "cash_amount": [float("nan")],
        }
    )
    adjusted = adjusted_close(raw, actions, tf_ms=DAY, include_dividends=False)[AAPL]
    assert adjusted.iloc[1] == pytest.approx(499.23 / 4.0)
    assert adjusted.iloc[2] == pytest.approx(129.04)
    assert abs(adjusted.iloc[2] / adjusted.iloc[1] - 1.0) < 0.05  # the split is neutralized


def test_a_non_positive_split_factor_is_refused() -> None:
    raw = pd.DataFrame({AAPL: [10.0, 5.0]}, index=[0, DAY])
    bad = pd.DataFrame(
        {
            "instrument_id": [AAPL],
            "ex_date": [DAY],
            "available_at": [DAY],
            "action_type": ["split"],
            "ratio": [0.0],
            "cash_amount": [float("nan")],
        }
    )
    with pytest.raises(ValueError, match="positive finite"):
        adjusted_close(raw, bad, tf_ms=DAY)


@pytest.mark.workspace_evidence
@pytest.mark.parametrize("lake", ["data/lake", "data/lake_sharadar"])
def test_every_production_lake_neutralizes_apples_2020_split_through_the_engine(lake: str) -> None:
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader

    root = ROOT / lake
    if not (root / "ohlcv_1d" / f"instrument_id={AAPL}").exists():
        pytest.skip(f"{lake} is not on this machine")
    reader = PITDataReader(LakePaths(root))
    start, end = _ms(dt.date(2020, 8, 1)), _ms(dt.date(2020, 9, 15))
    bars = reader.ohlcv([AAPL], start=start, end=end, as_of=end, tf=Timeframe.D1).to_pandas()
    bars["ts"] = (
        pd.to_datetime(bars["ts_open"], utc=True) - pd.Timestamp(0, tz="UTC")
    ) // pd.Timedelta(milliseconds=1)
    raw = bars.set_index("ts")["close"].astype("float64").to_frame(AAPL)
    actions = reader.corporate_actions([AAPL], start=start, end=end, as_of=end).to_pandas()
    actions = actions.assign(
        ex_date=(pd.to_datetime(actions["ex_date"], utc=True) - pd.Timestamp(0, tz="UTC"))
        // pd.Timedelta(milliseconds=1),
        available_at=(pd.to_datetime(actions["available_at"], utc=True) - pd.Timestamp(0, tz="UTC"))
        // pd.Timedelta(milliseconds=1),
    )
    splits = actions[actions["action_type"] == "split"]
    assert list(splits["ratio"]) == [4.0], "the lake stores the vendor factor, new shares per old"
    adjusted = adjusted_close(raw, actions, tf_ms=DAY, include_dividends=False)[AAPL]
    pre = adjusted.loc[_ms(dt.date(2020, 8, 28))]
    post = adjusted.loc[_ms(dt.date(2020, 8, 31))]
    assert pre == pytest.approx(499.23 / 4.0, rel=1e-6)
    assert abs(post / pre - 1.0) < 0.05
