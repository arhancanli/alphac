from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pyarrow as pa
import pytest
from test_backtest_engine import bar_row, make_instrument, ohlcv_table

from alphaforge.backtest.engine import EventDrivenBacktester, ScriptedStrategy, StaticCostInputs
from alphaforge.backtest.payable_engine import PayableEquityBacktester
from alphaforge.core.calendar import calendar_for
from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import CORPORATE_ACTIONS_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.execution.financing import FinancingQuote, StaticFinancingDataProvider
from alphaforge.validation.trend_dividend_settlement import DividendPayment

IID = "XUSE:CASH:TESTUSD"
DAY = 86400000


def ms(date):
    return int(pd.Timestamp(date, tz="UTC").timestamp() * 1000)


def setup(tmp_path, *, dividend=True, financing=False, pay=None):
    start, end = ms("2026-01-12"), ms("2026-01-23")
    sessions = list(calendar_for(AssetClass.EQUITY).expected_bar_opens(start, end, Timeframe.D1))
    ex = ms("2026-01-15")
    pay = ms("2026-01-17") if pay is None else pay
    bars = [
        bar_row(
            IID,
            t,
            open_=98.0 if dividend and t >= ex else 100.0,
            close=98.0 if dividend and t >= ex else 100.0,
            quote_volume=1e8,
        )
        for t in sessions
    ]
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV_1D, ohlcv_table(bars))
    if dividend:
        writer.write(
            Dataset.CORPORATE_ACTIONS,
            pa.Table.from_pylist(
                [
                    {
                        "instrument_id": IID,
                        "action_type": "dividend",
                        "ex_date": ex,
                        "available_at": start,
                        "ratio": 1.0,
                        "cash_amount": 2.0,
                        "ingested_at": start,
                    }
                ],
                schema=CORPORATE_ACTIONS_SCHEMA,
            ),
        )
    store = InstrumentStore(tmp_path / "ops.sqlite")
    inst = replace(
        make_instrument("BINANCE:PERP:BTCUSDT"),
        instrument_id=IID,
        asset_class=AssetClass.EQUITY,
        market_type=MarketType.CASH,
        base="TEST",
        quote="USD",
        funding_interval_hours=None,
    )
    store.upsert(inst, as_of=1)
    kwargs = {
        "tf": Timeframe.D1,
        "asset_class": AssetClass.EQUITY,
        "cost_inputs": StaticCostInputs(adv_quote=1e8, sigma_daily=0.02),
    }
    if financing:
        kwargs["financing_data"] = StaticFinancingDataProvider(
            quotes=(
                FinancingQuote(
                    currency="USD",
                    observed_ts=start,
                    available_at=start,
                    valid_from=start,
                    valid_until=end + 7 * DAY,
                    credit_rate_bps=400.0,
                    debit_rate_bps=700.0,
                    short_proceeds_rate_bps=0.0,
                    source="fixture",
                ),
            )
        )
    payments = [DividendPayment("div1", IID, ex, pay, start, Decimal("2"))] if dividend else []
    args = PITDataReader(paths), store, TransactionCostModel()
    return args, kwargs, payments, start, end


def test_clean_loop_parity_without_financing_or_actions(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path, dividend=False)
    script = {ms("2026-01-13"): {IID: 0.1}, ms("2026-01-16"): {IID: 0.0}}
    base = EventDrivenBacktester(*args, **kwargs).run(
        ScriptedStrategy(script), [IID], start=start, end=end
    )
    new = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy(script), [IID], start=start, end=end
    )
    pd.testing.assert_frame_equal(base.fills, new.fills, check_exact=True)
    pd.testing.assert_series_equal(base.equity, new.equity, check_exact=True)


def test_weekend_payment_after_sale_and_financing_segments(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path, financing=True)
    result = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy({ms("2026-01-13"): {IID: 0.1}, ms("2026-01-16"): {IID: 0.0}}),
        [IID],
        start=start,
        end=end,
    )
    earned = result.corporate_actions.iloc[0]
    assert int(earned.action_ts) == ms("2026-01-15")
    assert earned.cashflow_quote > 0
    paid = result.config["dividend_settlements"]
    assert len(paid) == 1 and paid[0]["ts"] == ms("2026-01-17")
    assert paid[0]["cashflow_quote"] == earned.cashflow_quote
    assert result.config["terminal_pending_dividends"] == 0
    financing = result.financing_events
    before = financing[financing.end_ts == ms("2026-01-17")].iloc[0]
    after = financing[financing.start_ts == ms("2026-01-17")].iloc[0]
    assert after.cash_balance == pytest.approx(
        before.cash_balance + before.payment_quote + earned.cashflow_quote
    )
    # Purchase is replayed before that interval's financing uses its cash base.
    bought = financing[financing.start_ts == ms("2026-01-13")].iloc[0]
    assert bought.cash_balance < 95000


def test_buying_at_ex_open_gets_no_entitlement(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path)
    result = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy({ms("2026-01-15"): {IID: 0.1}}), [IID], start=start, end=end
    )
    assert result.corporate_actions.empty
    assert sum(x["cashflow_quote"] for x in result.config["dividend_settlements"]) == 0


def test_unpaid_terminal_entitlement_is_preserved(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path, pay=ms("2026-02-01"))
    result = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy({ms("2026-01-13"): {IID: 0.1}}), [IID], start=start, end=end
    )
    assert result.config["terminal_pending_dividends"] > 0
    assert result.config["dividend_settlements"] == ()


def test_short_owes_dividend_at_payment(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path)
    result = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy({ms("2026-01-13"): {IID: -0.1}}), [IID], start=start, end=end
    )
    earned = result.corporate_actions.iloc[0].cashflow_quote
    assert earned < 0
    assert result.config["dividend_settlements"][0]["cashflow_quote"] == earned
    assert result.config["terminal_pending_dividends"] == 0


def test_missing_schedule_is_not_ex_date_cash_fallback(tmp_path):
    args, kwargs, _, start, end = setup(tmp_path)
    with pytest.raises(ValueError, match="payment-date"):
        PayableEquityBacktester(*args, payments=[], **kwargs).run(
            ScriptedStrategy({ms("2026-01-13"): {IID: 0.1}}), [IID], start=start, end=end
        )


def test_same_ex_payment_settles_once(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path, pay=ms("2026-01-15"))
    result = PayableEquityBacktester(*args, payments=payments, **kwargs).run(
        ScriptedStrategy({ms("2026-01-13"): {IID: 0.1}}), [IID], start=start, end=end
    )
    paid = result.config["dividend_settlements"]
    assert len(paid) == 1 and paid[0]["ts"] == ms("2026-01-15")
    assert paid[0]["cashflow_quote"] == result.corporate_actions.iloc[0].cashflow_quote


def test_missing_union_session_fails(tmp_path):
    args, kwargs, payments, start, end = setup(tmp_path, dividend=False)

    class MissingSession(PayableEquityBacktester):
        def _load_bars(self, *args, **kwargs):
            rows = super()._load_bars(*args, **kwargs)
            rows[IID].pop(ms("2026-01-14"))
            return rows

    with pytest.raises(ValueError, match="Missing union session"):
        MissingSession(*args, payments=payments, **kwargs).run(
            ScriptedStrategy({}), [IID], start=start, end=end
        )
