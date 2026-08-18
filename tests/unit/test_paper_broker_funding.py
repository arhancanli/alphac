"""PaperBroker.apply_funding — the cashflow the live carry sleeve never received.

WHY THIS FILE EXISTS
--------------------
`Ledger.apply_funding` was called from exactly one place, the BACKTEST engine. The live
PaperBroker moved cash only on fills, so a funding-carry sleeve ran live without ever
booking funding. That is ~51% of the strategy's lifetime backtest PnL
(`artifacts/walkforward/crypto_carry_wk/summary.txt`: funding_net 19500.02 of 38236 total).

This project's own stated lesson, written after the July reverse-split incident, is that
"a fix is not done until a test pins the path that RUNS". These tests pin the broker path.
"""

from __future__ import annotations

import math

import pytest

from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, Fill, Liquidity, MarketType, Side
from alphaforge.execution.paper import PaperBroker, PaperPosition

PERP = "BINANCE:PERP:BTCUSDT"


def _instruments() -> dict[str, Instrument]:
    inst = Instrument(
        instrument_id=PERP,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=4.0,
        funding_interval_hours=8,
        listed_ts=0,
        delisted_ts=None,
    )
    return {PERP: inst}


def _broker(cash: float = 100_000.0) -> PaperBroker:
    return PaperBroker(_instruments(), _ZeroCost(), book_source=None, initial_cash=cash)


class _ZeroCost:
    """Cost model stub: this file tests funding, not fees."""

    def fee(self, *_a: object, **_k: object) -> float:
        return 0.0

    def __getattr__(self, _name: str) -> object:  # tolerate whatever the broker asks for
        return lambda *a, **k: 0.0


def _open(broker: PaperBroker, qty: float, price: float) -> None:
    """Seed a signed position. Funding is what is under test here, not the fill path
    (that is covered by the execution suite), so the position is set directly and the
    cash left untouched: every assertion below is about the funding delta alone."""
    broker._state.positions[PERP] = PaperPosition(
        instrument_id=PERP, qty=qty, avg_entry_price=price, opened_ts=1_000
    )


class TestSignConvention:
    """payment = -qty * mark * rate. Longs pay shorts when the rate is positive."""

    def test_long_pays_when_rate_positive(self) -> None:
        b = _broker()
        _open(b, qty=2.0, price=50_000.0)
        cash_before = b._state.cash
        payment = b.apply_funding(PERP, ts_funding=2_000, rate=1e-4, mark_price=50_000.0)
        assert payment == pytest.approx(-2.0 * 50_000.0 * 1e-4)
        assert payment < 0.0
        assert b._state.cash == pytest.approx(cash_before + payment)

    def test_short_receives_when_rate_positive(self) -> None:
        b = _broker()
        _open(b, qty=-2.0, price=50_000.0)
        payment = b.apply_funding(PERP, ts_funding=2_000, rate=1e-4, mark_price=50_000.0)
        assert payment == pytest.approx(+2.0 * 50_000.0 * 1e-4)
        assert payment > 0.0

    def test_negative_rate_inverts_both_sides(self) -> None:
        long_b, short_b = _broker(), _broker()
        _open(long_b, qty=1.0, price=50_000.0)
        _open(short_b, qty=-1.0, price=50_000.0)
        p_long = long_b.apply_funding(PERP, ts_funding=2_000, rate=-1e-4, mark_price=50_000.0)
        p_short = short_b.apply_funding(PERP, ts_funding=2_000, rate=-1e-4, mark_price=50_000.0)
        assert p_long > 0.0 and p_short < 0.0
        assert p_long == pytest.approx(-p_short)

    def test_matches_the_ledger_exactly(self) -> None:
        """Two conventions would be worse than none: the broker must equal the ledger."""
        from alphaforge.backtest.ledger import Ledger

        ledger = Ledger(100_000.0, _instruments())
        ledger.apply_fill(
            Fill(
                client_order_id="seed",
                instrument_id=PERP,
                side=Side.BUY,
                qty=3.0,
                price=40_000.0,
                fee_quote=0.0,
                liquidity=Liquidity.TAKER,
                ts=1_000,
            )
        )
        b = _broker()
        _open(b, qty=3.0, price=40_000.0)
        for rate in (1e-4, -5e-5, 3.7e-4):
            assert b.apply_funding(
                PERP, ts_funding=2_000, rate=rate, mark_price=41_000.0
            ) == pytest.approx(
                ledger.apply_funding(PERP, ts_funding=2_000, rate=rate, mark_price=41_000.0)
            )


class TestSafety:
    def test_flat_book_is_a_no_op(self) -> None:
        """Safe to call for every settlement in a window without checking holdings first."""
        b = _broker()
        cash_before = b._state.cash
        assert b.apply_funding(PERP, ts_funding=2_000, rate=1e-4, mark_price=50_000.0) == 0.0
        assert b._state.cash == cash_before

    def test_rejects_non_finite_rate(self) -> None:
        b = _broker()
        _open(b, qty=1.0, price=50_000.0)
        for bad in (math.nan, math.inf):
            with pytest.raises(ValueError, match="finite"):
                b.apply_funding(PERP, ts_funding=2_000, rate=bad, mark_price=50_000.0)

    def test_rejects_bad_mark(self) -> None:
        b = _broker()
        _open(b, qty=1.0, price=50_000.0)
        for bad in (0.0, -1.0, math.nan):
            with pytest.raises(ValueError):
                b.apply_funding(PERP, ts_funding=2_000, rate=1e-4, mark_price=bad)

    def test_equity_reflects_funding(self) -> None:
        """The account snapshot must move with funding, not just the cash field."""
        from alphaforge.execution.broker import OrderBook

        class _FixedBook:
            def snapshot(self, _iid: str, *, ts: int) -> OrderBook:
                return OrderBook(
                    instrument_id=PERP, ts=ts,
                    bids=((49_990.0, 10.0),), asks=((50_010.0, 10.0),),
                )

        b = PaperBroker(
            _instruments(), _ZeroCost(), book_source=_FixedBook(), initial_cash=100_000.0
        )
        _open(b, qty=-2.0, price=50_000.0)
        eq_before = b.account_at(1_500).equity_quote
        payment = b.apply_funding(PERP, ts_funding=2_000, rate=2e-4, mark_price=50_000.0)
        eq_after = b.account_at(2_500).equity_quote
        assert payment > 0.0
        assert eq_after == pytest.approx(eq_before + payment, rel=1e-9)


class TestTheRegression:
    """The specific defect: cash must be reachable by something other than a fill."""

    def test_cash_moves_without_any_fill(self) -> None:
        b = _broker()
        _open(b, qty=-1.0, price=30_000.0)
        cash_after_fill = b._state.cash
        n_fills_before = len(b._state.fills)
        b.apply_funding(PERP, ts_funding=9_000, rate=5e-4, mark_price=30_000.0)
        assert b._state.cash != cash_after_fill
        assert len(b._state.fills) == n_fills_before, "funding must not fabricate a fill"
