from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pyarrow as pa
import pytest
from test_backtest_engine import bar_row, ohlcv_table
from test_payable_engine import DAY, IID, ms, setup
from test_trend_runner_bundle import inputs

from alphaforge.backtest.engine import ScriptedStrategy
from alphaforge.backtest.payable_engine import PayableEquityBacktester
from alphaforge.core.errors import LookaheadError
from alphaforge.data.schemas import CORPORATE_ACTIONS_SCHEMA, Dataset
from alphaforge.data.store.writer import LakeWriter
from alphaforge.execution.corporate_actions import CorporateAction, CorporateActionType
from alphaforge.validation.trend_dividend_settlement import DividendPayment, DividendSettlementBook
from alphaforge.validation.trend_observation import ObservationError
from alphaforge.validation.trend_price_bridge import Action
from alphaforge.validation.trend_runner_bundle import TrendRunnerBundle

VINTAGE = ms("2026-09-12")


def action(payment):
    return CorporateAction(
        instrument_id=payment.symbol,
        action_type=CorporateActionType.CASH_DIVIDEND,
        ex_date=payment.ex_ms,
        available_at=payment.observed_ms,
        ratio=1.0,
        cash_amount=float(payment.cash_per_share),
    )


@pytest.mark.parametrize(
    "weight,pay",
    [(0.1, "2026-01-17"), (-0.1, "2026-01-17"), (0.1, "2026-01-15"), (0.1, "2026-02-01")],
)
def test_late_vintage_matches_timely_economic_book(tmp_path, weight, pay):
    args, kwargs, payments, start, end = setup(tmp_path, financing=True, pay=ms(pay))
    script = {ms("2026-01-13"): {IID: weight}, ms("2026-01-16"): {IID: 0.0}}
    timely = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy(script), [IID], start=start, end=end
    )
    late = [replace(payments[0], observed_ms=VINTAGE)]
    retro = PayableEquityBacktester(
        *args,
        payments=late,
        retrospective_vintage_ms=VINTAGE,
        retrospective_actions=[action(late[0])],
        **kwargs,
    ).run(ScriptedStrategy(script), [IID], start=start, end=end)
    pd.testing.assert_series_equal(timely.equity, retro.equity, check_exact=True)
    pd.testing.assert_frame_equal(timely.fills, retro.fills, check_exact=True)
    pd.testing.assert_frame_equal(timely.financing_events, retro.financing_events, check_exact=True)
    for key in ["dividend_settlements", "terminal_pending_dividends", "terminal_settled_cash"]:
        assert timely.config[key] == retro.config[key]
    assert retro.config["point_in_time_proven"] is False
    assert retro.config["retrospective_action_records"][0]["available_at"] == VINTAGE
    assert "research_mode" not in timely.config
    with pytest.raises(ObservationError):
        DividendSettlementBook(Decimal(0)).accrue(late[0], Decimal(1), as_of_ms=late[0].ex_ms)


def test_rejects_future_capture_missing_schedule_and_duplicates(tmp_path):
    args, kwargs, payments, _, _ = setup(tmp_path)
    late = replace(payments[0], observed_ms=VINTAGE)
    for events, pays in [
        ([action(late)], []),
        ([action(late)] * 2, [late]),
        ([action(late)], [late, late]),
    ]:
        with pytest.raises(ValueError):
            PayableEquityBacktester(
                *args,
                payments=pays,
                retrospective_vintage_ms=VINTAGE,
                retrospective_actions=events,
                **kwargs,
            )
    with pytest.raises(LookaheadError):
        PayableEquityBacktester(
            *args,
            payments=[late],
            retrospective_vintage_ms=VINTAGE - 1,
            retrospective_actions=[action(late)],
            **kwargs,
        )
    with pytest.raises(ValueError):
        PayableEquityBacktester(
            *args, payments=payments, retrospective_vintage_ms=VINTAGE, **kwargs
        )


@pytest.mark.parametrize("weight", [0.1, -0.1])
def test_split_then_dividend_parity(tmp_path, weight):
    args, kwargs, _, start, end = setup(tmp_path, dividend=False)
    from alphaforge.core.calendar import calendar_for
    from alphaforge.core.time import Timeframe
    from alphaforge.core.types import AssetClass

    sessions = list(calendar_for(AssetClass.EQUITY).expected_bar_opens(start, end, Timeframe.D1))
    split_date, ex_date = ms("2026-01-15"), ms("2026-01-20")
    split = CorporateAction(
        instrument_id=IID,
        action_type=CorporateActionType.SPLIT,
        ex_date=split_date,
        available_at=start,
        ratio=2.0,
        cash_amount=None,
    )
    pay = DividendPayment("split-div", IID, ex_date, ex_date + DAY, start, Decimal("2"))
    actions = [split, action(pay)]
    writer = LakeWriter(args[0]._paths)
    writer.write(
        Dataset.OHLCV_1D,
        ohlcv_table(
            [
                bar_row(
                    IID,
                    t,
                    open_=100 if t < split_date else (50 if t < ex_date else 48),
                    close=100 if t < split_date else (50 if t < ex_date else 48),
                    quote_volume=1e8,
                )
                for t in sessions
            ]
        ),
    )
    writer.write(
        Dataset.CORPORATE_ACTIONS,
        pa.Table.from_pylist(
            [
                {
                    "instrument_id": a.instrument_id,
                    "action_type": a.action_type.value,
                    "ex_date": a.ex_date,
                    "available_at": a.available_at,
                    "ratio": a.ratio,
                    "cash_amount": a.cash_amount,
                    "ingested_at": start,
                }
                for a in actions
            ],
            schema=CORPORATE_ACTIONS_SCHEMA,
        ),
    )
    script = {ms("2026-01-13"): {IID: weight}}
    timely = PayableEquityBacktester(*args, payments=[pay], **kwargs).run(
        ScriptedStrategy(script), [IID], start=start, end=end
    )
    retro = PayableEquityBacktester(
        *args,
        payments=[replace(pay, observed_ms=VINTAGE)],
        retrospective_vintage_ms=VINTAGE,
        retrospective_actions=[replace(a, available_at=VINTAGE) for a in actions],
        **kwargs,
    ).run(ScriptedStrategy(script), [IID], start=start, end=end)
    pd.testing.assert_series_equal(timely.equity, retro.equity, check_exact=True)
    pd.testing.assert_frame_equal(
        timely.corporate_actions, retro.corporate_actions, check_exact=True
    )
    assert len(retro.corporate_actions) == 2
    assert retro.config["dividend_settlements"] == timely.config["dividend_settlements"]


def test_runner_preserves_late_schedule_and_requires_opt_in(tmp_path):
    paired, mapping, snapshots, start, end, sessions = inputs()
    ex = sessions[320]
    snapshots["A"] = replace(
        snapshots["A"], observed_ms=VINTAGE, actions=(Action("div", "A", ex, "dividend", 1.0),)
    )
    payments = [DividendPayment("div", "XUSE:CASH:AUSD", ex, ex + 7 * DAY, VINTAGE, Decimal("1"))]
    kwargs = {
        "instrument_symbols": mapping,
        "snapshots": snapshots,
        "payments": payments,
        "mode": "DIAGNOSTIC_CURRENT_VINTAGE",
    }
    with pytest.raises(ObservationError):
        TrendRunnerBundle(paired, **kwargs)
    bundle = TrendRunnerBundle(paired, retrospective_vintage_ms=VINTAGE, **kwargs)
    bundle.prepare(tmp_path / "bundle")
    from alphaforge.config.settings import Settings
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.core.types import AssetClass

    settings = Settings()
    settings = settings.model_copy(
        update={"data": settings.data.model_copy(update={"asset_class": AssetClass.EQUITY})}
    )
    with InstrumentStore(tmp_path / "ops.sqlite") as store:
        from test_backtest_engine import make_instrument

        from alphaforge.backtest.engine import StaticCostInputs
        from alphaforge.core.types import MarketType

        for iid, symbol in mapping.items():
            store.upsert(
                replace(
                    make_instrument("BINANCE:PERP:BTCUSDT"),
                    instrument_id=iid,
                    asset_class=AssetClass.EQUITY,
                    market_type=MarketType.CASH,
                    base=symbol,
                    quote="USD",
                    funding_interval_hours=None,
                ),
                as_of=1,
            )
        engine = bundle.engine(
            store, settings, cost_inputs=StaticCostInputs(adv_quote=1e8, sigma_daily=0.02)
        )
        result = engine.run(
            ScriptedStrategy({sessions[310]: {"XUSE:CASH:AUSD": 0.1}}),
            list(mapping),
            start=sessions[300],
            end=end,
        )
        assert len(result.corporate_actions) == 1
        assert result.config["dividend_settlements"][0]["cashflow_quote"] > 0
        assert result.config["point_in_time_proven"] is False
        loaded = engine._load_corporate_actions(list(mapping), start=start, end=end)
        assert loaded["XUSE:CASH:AUSD"][0].available_at == VINTAGE
        assert engine._payments[0].observed_ms == VINTAGE
    assert bundle.binding["point_in_time_proven"] is False
