import pandas as pd
import pytest

from alphaforge.validation.trend_input_routes import TrendInputRoutes
from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import ActionSnapshot

DECISION, ENTRY, EXIT = 1788912000000, 1788998400000, 1789084800000


def frame():
    return pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "session_ms": t,
                "raw_open": p,
                "raw_high": p + 1,
                "raw_low": p - 1,
                "raw_close": p,
                "signal_open": s,
                "signal_high": s + 2,
                "signal_low": s - 2,
                "signal_close": s,
                "raw_volume": 1000,
            }
            for t, p, s in [(ENTRY, 100.0, 1000.0), (EXIT, 110.0, 5000.0)]
        ]
    )


def test_separate_routes():
    routes = TrendInputRoutes(frame())
    assert routes.feature_bars(through_session=EXIT).open.tolist() == [1000, 5000]
    assert routes.execution_bars(through_session=EXIT).open.tolist() == [100, 110]
    assert len(routes.execution_bars(through_session=ENTRY)) == 1


def test_raw_label_ignores_synthetic_ratio():
    routes = TrendInputRoutes(frame())
    release = session_window(EXIT)[0]
    snap = ActionSnapshot("SPY", ENTRY, EXIT + 86400000, release, "a" * 64, True, ())
    result = routes.label(
        symbol="SPY", decision_session=DECISION, horizon=1, snapshot=snap, as_of_ms=release
    )
    assert result.gross_return == pytest.approx(0.1)


def test_copies_cannot_mutate_sealed_inputs():
    source = frame()
    routes = TrendInputRoutes(source)
    source.loc[:, "raw_open"] = 1
    returned = routes.execution_bars(through_session=EXIT)
    returned.loc[:, "open"] = 1
    assert routes.execution_bars(through_session=EXIT).open.tolist() == [100, 110]


@pytest.mark.parametrize("kind", ["duplicate", "nan", "missing", "bad_ohlc"])
def test_bad_inputs(kind):
    source = frame()
    if kind == "duplicate":
        source = pd.concat([source, source])
    elif kind == "nan":
        source.loc[0, "signal_close"] = float("nan")
    elif kind == "missing":
        source = source.drop(columns="raw_open")
    else:
        source.loc[0, "raw_high"] = 50
    with pytest.raises(ObservationError):
        TrendInputRoutes(source)
