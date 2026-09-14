from dataclasses import replace

import pandas as pd
import pytest
from test_backtest_engine import (
    BTC,
    HOUR,
    T0,
    ScriptedStrategy,
    build_engine,
    make_instrument,
    two_asset_bars,
)

from alphaforge.backtest.fills import BarView, NextOpenFill
from alphaforge.backtest.quality_fill import QualityGatedFill, ReviewedBar
from alphaforge.costs import TransactionCostModel


def records(bars, eligible=True):
    return [
        ReviewedBar(
            str(row["instrument_id"]),
            BarView(
                **{
                    f: row[f]
                    for f in ["ts_open", "open", "high", "low", "close", "volume", "quote_volume"]
                }
            ),
            eligible,
        )
        for row in bars
    ]


@pytest.mark.parametrize(
    "case", ["clean", "disputed", "absent", "synthetic", "volume_changed", "zero_volume"]
)
def test_gate_in_real_event_engine(tmp_path, case):
    bars = [row for row in two_asset_bars(4) if row["instrument_id"] == BTC]
    if case == "zero_volume":
        bars[1]["volume"] = 0.0
        bars[1]["quote_volume"] = 0.0
    reviewed = records(bars)
    if case in {"disputed", "zero_volume"}:
        reviewed[1] = replace(reviewed[1], eligible=False)
    elif case == "absent":
        reviewed.pop(1)
    elif case == "synthetic":
        reviewed[1] = replace(reviewed[1], bar=replace(reviewed[1].bar, open=200.0))
    elif case == "volume_changed":
        reviewed[1] = replace(reviewed[1], bar=replace(reviewed[1].bar, quote_volume=1.0))
    gate = QualityGatedFill(NextOpenFill(TransactionCostModel()), reviewed)
    engine = build_engine(tmp_path, bars, [], [make_instrument(BTC)], fill_model=gate)
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.1}}), [BTC], start=T0, end=T0 + 4 * HOUR
    )
    assert result.counters["fills_applied"] == (1 if case == "clean" else 0)
    assert result.counters.get("dropped_no_bar_liquidity", 0) == (0 if case == "clean" else 1)
    assert len(result.equity) > 0
    if case == "clean":
        baseline = build_engine(tmp_path / "baseline", bars, [], [make_instrument(BTC)])
        reference = baseline.run(
            ScriptedStrategy({T0 + HOUR: {BTC: 0.1}}),
            [BTC],
            start=T0,
            end=T0 + 4 * HOUR,
        )
        pd.testing.assert_frame_equal(result.fills, reference.fills, check_exact=True)
        pd.testing.assert_series_equal(result.equity, reference.equity, check_exact=True)


def test_zero_volume_cannot_be_marked_eligible():
    reviewed = records([two_asset_bars(1)[0]])
    zero = replace(reviewed[0], bar=replace(reviewed[0].bar, volume=0.0))
    with pytest.raises(ValueError, match="volume"):
        QualityGatedFill(NextOpenFill(TransactionCostModel()), [zero])


def test_duplicate_and_mutable_input():
    reviewed = records([two_asset_bars(1)[0]])
    with pytest.raises(ValueError, match="Unique"):
        QualityGatedFill(NextOpenFill(TransactionCostModel()), reviewed * 2)
    gate = QualityGatedFill(NextOpenFill(TransactionCostModel()), reviewed)
    reviewed.clear()
    assert len(gate._reviewed) == 1
