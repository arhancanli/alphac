import pandas as pd
import pytest

from alphaforge.validation.trend_input_routes_v2 import TrendInputRoutesV2
from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import ActionSnapshot

TIMES = [1788912000000, 1788998400000, 1789084800000]


def panel():
    return pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "session_ms": t,
                "raw_volume": v,
                "price_disputed": False,
                **{
                    f"{kind}_{f}": p
                    for kind, p in [("raw", 100.0), ("signal", 200.0)]
                    for f in ["open", "high", "low", "close"]
                },
            }
            for t, v in zip(TIMES, [100.0, 0.0, 100.0], strict=True)
        ]
    )


def test_zero_volume_preserves_sessions_and_blocks_execution():
    route = TrendInputRoutesV2(panel())
    execution = route.execution_bars(through_session=TIMES[-1])
    assert execution.session_ms.tolist() == TIMES
    assert execution.volume.tolist() == [100, 0, 100]
    assert execution.execution_eligible.tolist() == [True, False, True]
    assert route.feature_bars(through_session=TIMES[-1]).open.tolist() == [200] * 3


def test_disputed_future_does_not_block_earlier_features():
    data = panel()
    data.loc[2, "price_disputed"] = True
    route = TrendInputRoutesV2(data)
    assert len(route.feature_bars(through_session=TIMES[1])) == 2
    with pytest.raises(ObservationError, match="Unresolved"):
        route.feature_bars(through_session=TIMES[2])
    assert not route.execution_bars(through_session=TIMES[2]).execution_eligible.iloc[-1]


def test_zero_volume_label_endpoint_fails_without_calendar_shift():
    route = TrendInputRoutesV2(panel())
    with pytest.raises(ObservationError, match="zero-volume"):
        route.label(
            symbol="SPY",
            decision_session=TIMES[0],
            horizon=1,
            snapshot=None,
            as_of_ms=session_window(TIMES[-1])[0],
        )


def test_disputed_label_fails():
    data = panel()
    data["raw_volume"] = 100.0
    data.loc[2, "price_disputed"] = True
    with pytest.raises(ObservationError, match="Unresolved"):
        TrendInputRoutesV2(data).label(
            symbol="SPY",
            decision_session=TIMES[0],
            horizon=1,
            snapshot=None,
            as_of_ms=session_window(TIMES[-1])[0],
        )


def test_clean_label_uses_raw_prices_and_copies_are_isolated():
    data = panel()
    data["raw_volume"] = 100.0
    route = TrendInputRoutesV2(data)
    data.loc[2, "raw_open"] = 1
    view = route.execution_bars(through_session=TIMES[-1])
    view.loc[:, "execution_eligible"] = False
    release = session_window(TIMES[-1])[0]
    snapshot = ActionSnapshot("SPY", TIMES[0], TIMES[-1] + 86400000, release, "a" * 64, True, ())
    assert (
        route.label(
            symbol="SPY", decision_session=TIMES[0], horizon=1, snapshot=snapshot, as_of_ms=release
        ).gross_return
        == 0
    )
    assert route.execution_bars(through_session=TIMES[-1]).execution_eligible.all()


@pytest.mark.parametrize(
    "column,value", [("raw_volume", -1), ("raw_volume", float("nan")), ("price_disputed", "false")]
)
def test_invalid_quality_inputs(column, value):
    data = panel()
    data[column] = value
    with pytest.raises(ObservationError):
        TrendInputRoutesV2(data)
