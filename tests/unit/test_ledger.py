"""Unit tests for the backtest Ledger (execDesign.md §4.3).

Every cash/avg_entry/realized number in the multi-fill scenario is hand-computed
to the cent with the arithmetic spelled out in comments. The fundamental equity
identity

    equity == initial_cash + realized + unrealized - fees + funding

is asserted after every event.
"""

from __future__ import annotations

import math

import pytest

from alphaforge.backtest import Ledger
from alphaforge.core.instruments import Instrument
from alphaforge.core.types import AssetClass, Fill, Liquidity, MarketType, Side

PERP_ID = "BINANCE:PERP:BTCUSDT"
SPOT_ID = "BINANCE:SPOT:BTCUSDT"


def _perp() -> Instrument:
    return Instrument(
        instrument_id=PERP_ID,
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


def _spot() -> Instrument:
    return Instrument(
        instrument_id=SPOT_ID,
        asset_class=AssetClass.CRYPTO_SPOT,
        market_type=MarketType.SPOT,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=False,
        maker_fee_bps=10.0,
        taker_fee_bps=10.0,
        funding_interval_hours=None,
        listed_ts=0,
        delisted_ts=None,
    )


def _fill(
    side: Side,
    qty: float,
    price: float,
    fee: float,
    ts: int,
    instrument_id: str = PERP_ID,
) -> Fill:
    return Fill(
        client_order_id=f"o-{ts}",
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        price=price,
        fee_quote=fee,
        liquidity=Liquidity.TAKER,
        ts=ts,
    )


def _assert_identity(ledger: Ledger, closes: dict[str, float], ts: int) -> None:
    """equity == initial + realized + unrealized - fees + funding + borrow, continuously
    (total_borrow is <= 0 and 0 unless a short paid borrow, so this is unchanged for the
    existing crypto tests)."""
    state = ledger.mark(closes, ts)
    unrealized = sum(
        p.qty * (closes[iid] - p.avg_entry_price) for iid, p in ledger.positions().items()
    )
    expected = (
        ledger.initial_cash
        + sum(ledger.realized_pnl().values())
        + unrealized
        - ledger.total_fees
        + ledger.total_funding
        + ledger.total_borrow
    )
    assert state.equity_quote == pytest.approx(expected, abs=1e-9)


@pytest.fixture
def ledger() -> Ledger:
    return Ledger(initial_cash=100_000.0, instruments={PERP_ID: _perp(), SPOT_ID: _spot()})


class TestConstruction:
    def test_rejects_nonpositive_initial_cash(self) -> None:
        with pytest.raises(ValueError, match="initial_cash"):
            Ledger(initial_cash=0.0, instruments={})
        with pytest.raises(ValueError, match="initial_cash"):
            Ledger(initial_cash=-1.0, instruments={})

    def test_rejects_nonfinite_initial_cash(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            Ledger(initial_cash=math.nan, instruments={})
        with pytest.raises(ValueError, match="finite"):
            Ledger(initial_cash=math.inf, instruments={})

    def test_starts_flat(self, ledger: Ledger) -> None:
        assert ledger.cash == 100_000.0
        assert ledger.positions() == {}
        assert ledger.realized_pnl() == {}
        assert ledger.total_fees == 0.0
        assert ledger.total_funding == 0.0
        assert ledger.equity_curve().empty


class TestMultiFillScenario:
    """Open → add → partial close → flip → close, every intermediate hand-computed."""

    def test_full_lifecycle_to_the_cent(self, ledger: Ledger) -> None:
        # --- Fill 1: BUY 2 @ 100, fee 0.20 (open long) ---------------------
        # cash = 100000 - 2*100 - 0.20 = 99799.80; qty=+2, avg=100
        ledger.apply_fill(_fill(Side.BUY, 2.0, 100.0, 0.20, ts=1_000))
        assert ledger.cash == pytest.approx(99_799.80, abs=1e-9)
        pos = ledger.positions()[PERP_ID]
        assert pos.qty == pytest.approx(2.0)
        assert pos.avg_entry_price == pytest.approx(100.0)
        assert pos.opened_ts == 1_000
        assert ledger.realized_pnl() == {}
        _assert_identity(ledger, {PERP_ID: 101.0}, ts=1_000)

        # --- Fill 2: BUY 2 @ 110, fee 0.22 (VWAP add) -----------------------
        # cash = 99799.80 - 2*110 - 0.22 = 99579.58
        # avg  = (2*100 + 2*110)/4 = 105; qty=+4; opened_ts unchanged
        ledger.apply_fill(_fill(Side.BUY, 2.0, 110.0, 0.22, ts=2_000))
        assert ledger.cash == pytest.approx(99_579.58, abs=1e-9)
        pos = ledger.positions()[PERP_ID]
        assert pos.qty == pytest.approx(4.0)
        assert pos.avg_entry_price == pytest.approx(105.0)
        assert pos.opened_ts == 1_000
        _assert_identity(ledger, {PERP_ID: 108.0}, ts=2_000)

        # --- Fill 3: SELL 1 @ 120, fee 0.12 (partial close) -----------------
        # realized = 1*(120-105)*(+1) = +15.00
        # cash = 99579.58 + 1*120 - 0.12 = 99699.46; qty=+3, avg unchanged 105
        ledger.apply_fill(_fill(Side.SELL, 1.0, 120.0, 0.12, ts=3_000))
        assert ledger.cash == pytest.approx(99_699.46, abs=1e-9)
        pos = ledger.positions()[PERP_ID]
        assert pos.qty == pytest.approx(3.0)
        assert pos.avg_entry_price == pytest.approx(105.0)
        assert ledger.realized_pnl()[PERP_ID] == pytest.approx(15.0, abs=1e-9)
        _assert_identity(ledger, {PERP_ID: 118.0}, ts=3_000)

        # --- Fill 4: SELL 5 @ 90, fee 0.45 (flip long 3 -> short 2) ---------
        # realize the FULL old long at the fill price: 3*(90-105) = -45
        # cumulative realized = 15 - 45 = -30
        # cash = 99699.46 + 5*90 - 0.45 = 100149.01
        # new qty = +3 - 5 = -2; avg_entry RESTARTS at flip price 90; opened_ts=4000
        ledger.apply_fill(_fill(Side.SELL, 5.0, 90.0, 0.45, ts=4_000))
        assert ledger.cash == pytest.approx(100_149.01, abs=1e-9)
        pos = ledger.positions()[PERP_ID]
        assert pos.qty == pytest.approx(-2.0)
        assert pos.avg_entry_price == pytest.approx(90.0)
        assert pos.opened_ts == 4_000
        assert ledger.realized_pnl()[PERP_ID] == pytest.approx(-30.0, abs=1e-9)
        _assert_identity(ledger, {PERP_ID: 92.0}, ts=4_000)

        # --- Fill 5: BUY 2 @ 80, fee 0.16 (close short exactly) -------------
        # realized on short = 2*(80-90)*(-1) = +20; cumulative = -30+20 = -10
        # cash = 100149.01 - 2*80 - 0.16 = 99988.85; flat
        ledger.apply_fill(_fill(Side.BUY, 2.0, 80.0, 0.16, ts=5_000))
        assert ledger.cash == pytest.approx(99_988.85, abs=1e-9)
        assert ledger.positions() == {}
        assert ledger.realized_pnl()[PERP_ID] == pytest.approx(-10.0, abs=1e-9)

        # total fees = 0.20+0.22+0.12+0.45+0.16 = 1.15
        assert ledger.total_fees == pytest.approx(1.15, abs=1e-12)
        # flat book: equity == cash == initial + realized - fees
        #          = 100000 - 10 - 1.15 = 99988.85
        state = ledger.mark({}, ts=5_000)
        assert state.equity_quote == pytest.approx(99_988.85, abs=1e-9)
        _assert_identity(ledger, {}, ts=5_000)

    def test_fill_unknown_instrument_raises(self, ledger: Ledger) -> None:
        with pytest.raises(KeyError, match="unknown instrument"):
            ledger.apply_fill(
                _fill(Side.BUY, 1.0, 100.0, 0.1, ts=1, instrument_id="BINANCE:PERP:ETHUSDT")
            )

    def test_fills_log_records_per_fill_realized(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 2.0, 100.0, 0.20, ts=1_000))
        ledger.apply_fill(_fill(Side.SELL, 1.0, 110.0, 0.11, ts=2_000))
        log = ledger.fills_log()
        assert list(log.columns) == [
            "ts",
            "instrument_id",
            "side",
            "qty",
            "price",
            "fee_quote",
            "liquidity",
            "realized_pnl_quote",
            "client_order_id",
        ]
        assert len(log) == 2
        assert log.loc[0, "realized_pnl_quote"] == pytest.approx(0.0)
        # realized on the reduce: 1*(110-100) = +10
        assert log.loc[1, "realized_pnl_quote"] == pytest.approx(10.0)
        assert log.loc[1, "side"] == "sell"


class TestFundingSignMatrix:
    """payment = -qty * mark * rate — all four {long,short} x {rate>0,rate<0} cells."""

    @pytest.mark.parametrize(
        ("side", "rate", "expected_payment"),
        [
            # long, rate>0: longs PAY  => -2*100*0.0001 = -0.02
            (Side.BUY, 1e-4, -0.02),
            # long, rate<0: longs RECEIVE => -2*100*(-0.0001) = +0.02
            (Side.BUY, -1e-4, 0.02),
            # short, rate>0: shorts RECEIVE => -(-2)*100*0.0001 = +0.02
            (Side.SELL, 1e-4, 0.02),
            # short, rate<0: shorts PAY => -(-2)*100*(-0.0001) = -0.02
            (Side.SELL, -1e-4, -0.02),
        ],
    )
    def test_sign_matrix_exact(
        self, ledger: Ledger, side: Side, rate: float, expected_payment: float
    ) -> None:
        ledger.apply_fill(_fill(side, 2.0, 100.0, 0.0, ts=1_000))
        cash_before = ledger.cash
        payment = ledger.apply_funding(PERP_ID, ts_funding=2_000, rate=rate, mark_price=100.0)
        assert payment == pytest.approx(expected_payment, abs=1e-12)
        assert ledger.cash == pytest.approx(cash_before + expected_payment, abs=1e-12)
        assert ledger.total_funding == pytest.approx(expected_payment, abs=1e-12)
        _assert_identity(ledger, {PERP_ID: 100.0}, ts=2_000)

    def test_no_position_is_noop_and_unlogged(self, ledger: Ledger) -> None:
        payment = ledger.apply_funding(PERP_ID, ts_funding=1_000, rate=1e-4, mark_price=100.0)
        assert payment == 0.0
        assert ledger.cash == 100_000.0
        assert ledger.funding_log().empty

    def test_funding_on_spot_raises(self, ledger: Ledger) -> None:
        with pytest.raises(ValueError, match="perp"):
            ledger.apply_funding(SPOT_ID, ts_funding=1_000, rate=1e-4, mark_price=100.0)

    def test_funding_unknown_instrument_raises(self, ledger: Ledger) -> None:
        with pytest.raises(KeyError, match="unknown instrument"):
            ledger.apply_funding("BINANCE:PERP:ETHUSDT", ts_funding=1, rate=1e-4, mark_price=1.0)

    def test_funding_rejects_nonfinite_rate_and_bad_mark(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 1.0, 100.0, 0.0, ts=1_000))
        with pytest.raises(ValueError, match="finite"):
            ledger.apply_funding(PERP_ID, ts_funding=2_000, rate=math.nan, mark_price=100.0)
        with pytest.raises(ValueError, match="mark_price"):
            ledger.apply_funding(PERP_ID, ts_funding=2_000, rate=1e-4, mark_price=0.0)

    def test_funding_log_contents(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.SELL, 3.0, 200.0, 0.0, ts=1_000))
        ledger.apply_funding(PERP_ID, ts_funding=2_000, rate=5e-5, mark_price=210.0)
        log = ledger.funding_log()
        assert list(log.columns) == [
            "ts_funding",
            "instrument_id",
            "rate",
            "mark_price",
            "position_qty",
            "payment_quote",
        ]
        assert len(log) == 1
        # payment = -(-3)*210*5e-5 = +0.0315 (short receives)
        assert log.loc[0, "payment_quote"] == pytest.approx(0.0315, abs=1e-12)
        assert log.loc[0, "position_qty"] == pytest.approx(-3.0)
        assert log.loc[0, "ts_funding"] == 2_000


class TestMarkAndEquityCurve:
    def test_mark_returns_account_state(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 2.0, 100.0, 0.50, ts=1_000))
        state = ledger.mark({PERP_ID: 105.0}, ts=1_000)
        # equity = cash + qty*close = (100000 - 200 - 0.5) + 2*105 = 100009.50
        assert state.equity_quote == pytest.approx(100_009.50, abs=1e-9)
        assert state.cash_quote == pytest.approx(99_799.50, abs=1e-9)
        assert state.ts == 1_000
        assert len(state.positions) == 1
        assert state.positions[0].instrument_id == PERP_ID

    def test_equity_curve_series(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 1.0, 100.0, 0.0, ts=1_000))
        ledger.mark({PERP_ID: 100.0}, ts=1_000)
        ledger.mark({PERP_ID: 110.0}, ts=2_000)
        curve = ledger.equity_curve()
        assert list(curve.index) == [1_000, 2_000]
        assert curve.loc[1_000] == pytest.approx(100_000.0)
        assert curve.loc[2_000] == pytest.approx(100_010.0)
        assert curve.index.name == "ts"
        assert curve.dtype == "float64"

    def test_remark_same_ts_overwrites(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 1.0, 100.0, 0.0, ts=1_000))
        ledger.mark({PERP_ID: 100.0}, ts=1_000)
        ledger.mark({PERP_ID: 120.0}, ts=1_000)
        curve = ledger.equity_curve()
        assert len(curve) == 1
        assert curve.loc[1_000] == pytest.approx(100_020.0)

    def test_mark_decreasing_ts_raises(self, ledger: Ledger) -> None:
        ledger.mark({}, ts=2_000)
        with pytest.raises(ValueError, match="non-decreasing"):
            ledger.mark({}, ts=1_000)

    def test_mark_missing_close_for_open_position_raises(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 1.0, 100.0, 0.0, ts=1_000))
        with pytest.raises(ValueError, match="missing close"):
            ledger.mark({}, ts=1_000)

    def test_mark_nonfinite_close_raises(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 1.0, 100.0, 0.0, ts=1_000))
        with pytest.raises(ValueError, match="finite"):
            ledger.mark({PERP_ID: math.nan}, ts=1_000)

    def test_positions_view_is_a_copy(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 1.0, 100.0, 0.0, ts=1_000))
        view = ledger.positions()
        view.clear()
        assert PERP_ID in ledger.positions()


class TestBorrow:
    """The short-borrow carry leg (equity long/short financing analogue of funding)."""

    RATE = 0.5 / 365.0  # 50 bp/yr general collateral as a per-day fraction

    def test_short_pays_borrow_over_calendar_days(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.SELL, 2.0, 100.0, 0.0, ts=1_000))  # short 2 @ 100
        cash_before = ledger.cash
        # 3 calendar days (a Fri->Mon hold), mark 100 -> notional 200 -> cost 200*rate*3
        payment = ledger.apply_borrow(
            PERP_ID, ts=2_000, borrow_frac_per_day=self.RATE, days=3.0, mark_price=100.0
        )
        expected = -2.0 * 100.0 * self.RATE * 3.0  # qty<0 -> payment<0 (a cost)
        assert payment == pytest.approx(expected, abs=1e-12)
        assert payment < 0.0
        assert ledger.cash == pytest.approx(cash_before + expected, abs=1e-12)
        assert ledger.total_borrow == pytest.approx(expected, abs=1e-12)
        _assert_identity(ledger, {PERP_ID: 100.0}, ts=2_000)

    def test_long_and_flat_never_borrow(self, ledger: Ledger) -> None:
        ledger.apply_fill(_fill(Side.BUY, 2.0, 100.0, 0.0, ts=1_000))  # long
        cash_after_fill = ledger.cash  # the buy spent cash; borrow must not move it
        assert (
            ledger.apply_borrow(
                PERP_ID, ts=2_000, borrow_frac_per_day=self.RATE, days=1.0, mark_price=100.0
            )
            == 0.0
        )
        # flat instrument
        assert (
            ledger.apply_borrow(
                SPOT_ID, ts=2_000, borrow_frac_per_day=self.RATE, days=1.0, mark_price=100.0
            )
            == 0.0
        )
        assert ledger.cash == cash_after_fill
        assert ledger.total_borrow == 0.0

    def test_zero_rate_is_noop_byte_identity(self, ledger: Ledger) -> None:
        """borrow_frac_per_day == 0 (every crypto perp) is a pure no-op — the byte-identity
        guarantee that the equity-only leg never perturbs a crypto book."""
        ledger.apply_fill(_fill(Side.SELL, 5.0, 100.0, 0.0, ts=1_000))
        cash_before = ledger.cash
        assert (
            ledger.apply_borrow(
                PERP_ID, ts=2_000, borrow_frac_per_day=0.0, days=10.0, mark_price=100.0
            )
            == 0.0
        )
        assert ledger.cash == cash_before
        assert ledger.total_borrow == 0.0

    def test_borrow_unknown_instrument_raises(self, ledger: Ledger) -> None:
        with pytest.raises(KeyError, match="unknown instrument"):
            ledger.apply_borrow(
                "BINANCE:PERP:ETHUSDT",
                ts=1,
                borrow_frac_per_day=self.RATE,
                days=1.0,
                mark_price=1.0,
            )
