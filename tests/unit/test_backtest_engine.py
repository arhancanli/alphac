"""Unit tests for alphaforge.backtest.engine — the truth engine.

Centerpiece: a 2-asset, 16-bar scripted golden master with every fill, fee,
funding payment, and equity point hand-computed to the cent (arithmetic in the
comments; the Phase-5 mini golden master — the auditor builds the full 3-asset
one). Also covered: the no-lookahead contract end to end, final-bar orders
producing zero fills, gap-at-t+1 drops, delisting force-flat, the no-trade
band, mixed 8h/4h funding intervals driven purely by the STORED events table,
PIT truncation of the strategy's data window, the RankStrategy demo, and the
LakeCostInputs ADV/sigma provider.

All lakes are built in tmp_path (offline, deterministic); no real data dirs.
"""

from __future__ import annotations

import math
from pathlib import Path

import pyarrow as pa
import pytest

from alphaforge.backtest.engine import (
    EventDrivenBacktester,
    LakeCostInputs,
    RankStrategy,
    ScriptedStrategy,
    StaticCostInputs,
    StrategyContext,
)
from alphaforge.backtest.result import BacktestResult
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Ms, Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter

HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z — UTC midnight (1h/4h/8h aligned)
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z

BTC = "BINANCE:PERP:BTCUSDT"  # 8h funding
ETH = "BINANCE:PERP:ETHUSDT"  # 4h funding (mixed-interval coverage, finding 6)

# Cost model defaults exercised throughout: hs 2.5 bps, latency 2 bps, perp
# taker 5 bps, impact Y = 1.0; StaticCostInputs pins ADV / sigma so every
# number below is reproducible by hand.
ADV = 1e8
SIGMA = 0.02
CASH0 = 100_000.0


def imp(notional: float) -> float:
    """Square-root impact: Y * sigma * sqrt(Q/ADV) with the fixture constants."""
    return 1.0 * SIGMA * math.sqrt(notional / ADV)


def slip(notional: float) -> float:
    """Half-spread + impact + latency (the fill-price shift fraction)."""
    return 2.5e-4 + imp(notional) + 2e-4


# ------------------------------------------------------------------- fixtures


def make_instrument(instrument_id: str, *, funding_hours: int = 8) -> Instrument:
    symbol = instrument_id.split(":")[2]
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=symbol.removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=10.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=funding_hours,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def bar_row(
    instrument_id: str,
    ts_open: int,
    *,
    open_: float,
    close: float,
    quote_volume: float = 1_000.0,
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "ts_open": ts_open,
        "open": open_,
        "high": max(open_, close) * 1.01,
        "low": min(open_, close) * 0.99,
        "close": close,
        "volume": 10.0,
        "quote_volume": quote_volume,
        "n_trades": 42,
        "quality_flags": 0,
        "ingested_at": ts_open + HOUR + 30_000,
    }


def ohlcv_table(rows: list[dict[str, object]]) -> pa.Table:
    def ts(name: str) -> pa.Array:
        return pa.array([r[name] for r in rows], type=pa.timestamp("ms", tz="UTC"))

    def f64(name: str) -> pa.Array:
        return pa.array([r[name] for r in rows], type=pa.float64())

    return pa.table(
        {
            "instrument_id": pa.array([r["instrument_id"] for r in rows], type=pa.string()),
            "ts_open": ts("ts_open"),
            "open": f64("open"),
            "high": f64("high"),
            "low": f64("low"),
            "close": f64("close"),
            "volume": f64("volume"),
            "quote_volume": f64("quote_volume"),
            "n_trades": pa.array([r["n_trades"] for r in rows], type=pa.int64()),
            "quality_flags": pa.array([r["quality_flags"] for r in rows], type=pa.int32()),
            "ingested_at": ts("ingested_at"),
        }
    )


def funding_table(rows: list[tuple[str, int, float]]) -> pa.Table:
    # available_at == ts_funding (zero publication lag) so events settling at
    # the run end are visible to the engine's as_of=end read.
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "ingested_at": pa.array(
                [r[1] + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def build_engine(
    tmp_path: Path,
    bars: list[dict[str, object]],
    funding: list[tuple[str, int, float]],
    instruments: list[Instrument],
    *,
    use_static_cost_inputs: bool = True,
    no_trade_band_frac: float = 0.001,
) -> EventDrivenBacktester:
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV, ohlcv_table(bars))
    if funding:
        writer.write(Dataset.FUNDING, funding_table(funding))
    store = InstrumentStore(tmp_path / "ops.sqlite")
    for inst in instruments:
        store.upsert(inst, as_of=1)
    return EventDrivenBacktester(
        PITDataReader(paths),
        store,
        TransactionCostModel(),
        cost_inputs=(
            StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA) if use_static_cost_inputs else None
        ),
        no_trade_band_frac=no_trade_band_frac,
    )


def two_asset_bars(n_bars: int = 16) -> list[dict[str, object]]:
    """BTC: 100/100 through bar 5, bar 6 opens 100 closes 104, then 104/104.
    ETH: 50/50 throughout."""
    rows: list[dict[str, object]] = []
    for k in range(n_bars):
        if k <= 5:
            b_open, b_close = 100.0, 100.0
        elif k == 6:
            b_open, b_close = 100.0, 104.0
        else:
            b_open, b_close = 104.0, 104.0
        rows.append(bar_row(BTC, T0 + k * HOUR, open_=b_open, close=b_close))
        rows.append(bar_row(ETH, T0 + k * HOUR, open_=50.0, close=50.0))
    return rows


GOLDEN_FUNDING: list[tuple[str, int, float]] = [
    (BTC, T0 + 8 * HOUR, 1e-4),  # BTC flat at C8 -> stored but NOT applied
    (BTC, T0 + 16 * HOUR, 1e-4),  # BTC short 40 -> applied (shorts receive)
    (ETH, T0 + 4 * HOUR, 2e-4),
    (ETH, T0 + 8 * HOUR, -1e-4),
    (ETH, T0 + 12 * HOUR, 5e-5),
    (ETH, T0 + 16 * HOUR, 1e-4),
]

GOLDEN_SCRIPT: dict[Ms, dict[str, float]] = {
    T0 + 1 * HOUR: {BTC: 0.10, ETH: 0.05},  # open both longs
    T0 + 6 * HOUR: {BTC: 0.0},  # flatten BTC (decided at close 100, BEFORE the pump)
    T0 + 9 * HOUR: {BTC: -0.05},  # short BTC at 104
}


class Golden:
    """Hand-computed golden-master expectations (every figure derived in comments)."""

    def __init__(self) -> None:
        # --- C2 fills (decided at C1, executed at bar-1 opens) -------------
        # BTC BUY 100 @ open 100: N=10_000, Q/ADV=1e-4, sqrt=0.01,
        #   impact=2e-4, slip=6.5e-4 -> p=100.065, fee=5e-4*100*p=5.00325
        self.p1 = 100.0 * (1.0 + slip(10_000.0))  # = 100.065
        self.fee1 = 5e-4 * 100.0 * self.p1  # = 5.00325
        # ETH BUY 100 @ open 50: N=5_000 -> impact=0.02*sqrt(5e-5)
        self.p2 = 50.0 * (1.0 + slip(5_000.0))
        self.fee2 = 5e-4 * 100.0 * self.p2
        cash2 = CASH0 - (100.0 * self.p1 + self.fee1) - (100.0 * self.p2 + self.fee2)
        # --- C7 fill (flatten BTC, decided at C6 close=100, filled at bar-6
        #     open=100; bar 6 then CLOSES at 104 — the pump never helps us:
        #     that is the no-lookahead contract visible in money) -----------
        self.p3 = 100.0 * (1.0 - slip(10_000.0))  # = 99.935
        self.fee3 = 5e-4 * 100.0 * self.p3  # = 4.99675
        # realized on the flatten: 100 * (99.935 - 100.065) = -13.00 exactly
        self.realized3 = 100.0 * (self.p3 - self.p1)
        cash4 = cash2 - 1.0  # ETH funding C4: -100*50*2e-4 = -1.00 (long pays)
        cash7 = cash4 + 100.0 * self.p3 - self.fee3
        cash8 = cash7 + 0.5  # ETH funding C8: -100*50*(-1e-4) = +0.50
        # --- C9 decision: short BTC 5% of equity at close 104 ---------------
        e9 = cash8 + 100.0 * 50.0  # BTC flat, ETH marked at 50
        self.qty4 = float(math.floor(0.05 * e9 / 104.0 + 1e-9))  # lot 1.0 -> 40.0
        # --- C10 fill: SELL qty4 @ open 104 ---------------------------------
        n4 = self.qty4 * 104.0
        self.p4 = 104.0 * (1.0 - slip(n4))
        self.fee4 = 5e-4 * self.qty4 * self.p4
        cash10 = cash8 + self.qty4 * self.p4 - self.fee4
        cash12 = cash10 - 0.25  # ETH funding C12: -100*50*5e-5 = -0.25
        # --- C16 funding: BTC short receives -(-40)*104*1e-4 = +0.416;
        #     ETH long pays  -100*50*1e-4 = -0.50 ---------------------------
        self.btc_pay16 = self.qty4 * 104.0 * 1e-4  # -(-40)*104*1e-4 = +0.416
        cash16 = cash12 + self.btc_pay16 - 0.5

        mark_eth = 100.0 * 50.0
        mark_btc_long = 100.0 * 100.0
        e2 = cash2 + mark_btc_long + mark_eth
        e4 = e2 - 1.0
        e7 = cash7 + mark_eth
        e8 = e7 + 0.5
        e10 = cash10 - self.qty4 * 104.0 + mark_eth
        e12 = e10 - 0.25
        e16 = cash16 - self.qty4 * 104.0 + mark_eth
        # equity at every close C1..C16 (the mini golden master curve)
        self.equity = [
            CASH0,  # C1: no fills yet
            e2,  # C2: both longs on
            e2,  # C3
            e4,  # C4: ETH funding -1.00
            e4,  # C5
            e4,  # C6 (decision close; BTC still 100)
            e7,  # C7: BTC flat at 99.935; close 104 does NOT help us
            e8,  # C8: ETH funding +0.50; BTC 8h event skipped (flat)
            e8,  # C9 (short decided here)
            e10,  # C10: short 40 on at p4
            e10,  # C11
            e12,  # C12: ETH funding -0.25
            e12,  # C13
            e12,  # C14
            e12,  # C15
            e16,  # C16: BTC +0.416 (short receives), ETH -0.50
        ]
        self.total_fees = self.fee1 + self.fee2 + self.fee3 + self.fee4
        self.total_funding = -1.0 + 0.5 - 0.25 + self.btc_pay16 - 0.5
        self.final_cash = cash16


@pytest.fixture(scope="module")
def golden_result(tmp_path_factory: pytest.TempPathFactory) -> BacktestResult:
    tmp = tmp_path_factory.mktemp("golden")
    engine = build_engine(
        tmp,
        two_asset_bars(),
        GOLDEN_FUNDING,
        [make_instrument(BTC, funding_hours=8), make_instrument(ETH, funding_hours=4)],
    )
    return engine.run(
        ScriptedStrategy(GOLDEN_SCRIPT),
        [BTC, ETH],
        start=T0,
        end=T0 + 16 * HOUR,
        initial_cash=CASH0,
    )


# ----------------------------------------------------------- golden master


class TestGoldenMaster:
    def test_equity_curve_to_the_cent(self, golden_result: BacktestResult) -> None:
        g = Golden()
        expected_index = [T0 + k * HOUR for k in range(1, 17)]
        assert list(golden_result.equity.index) == expected_index
        for ts, actual, expected in zip(
            expected_index, golden_result.equity.to_numpy(), g.equity, strict=True
        ):
            assert actual == pytest.approx(expected, abs=1e-9), f"equity at {ts}"

    def test_fills_exact(self, golden_result: BacktestResult) -> None:
        g = Golden()
        fills = golden_result.fills
        assert list(fills["ts"]) == [T0 + 1 * HOUR, T0 + 1 * HOUR, T0 + 6 * HOUR, T0 + 9 * HOUR]
        assert list(fills["instrument_id"]) == [BTC, ETH, BTC, BTC]
        assert list(fills["side"]) == ["buy", "buy", "sell", "sell"]
        assert list(fills["qty"]) == [100.0, 100.0, 100.0, g.qty4]
        for actual, expected in zip(fills["price"], [g.p1, g.p2, g.p3, g.p4], strict=True):
            assert actual == pytest.approx(expected, abs=1e-12)
        for actual, expected in zip(fills["fee"], [g.fee1, g.fee2, g.fee3, g.fee4], strict=True):
            assert actual == pytest.approx(expected, abs=1e-12)
        # flattening BTC realized exactly 100*(p3 - p1) = -13.00
        assert fills["realized_pnl_quote"].iloc[2] == pytest.approx(g.realized3, abs=1e-9)
        assert fills["realized_pnl_quote"].iloc[2] == pytest.approx(-13.0, abs=1e-9)
        assert (fills["liquidity"] == "taker").all()
        assert (fills["reason"] == "target_weight").all()
        # notional column = qty * executed price
        for _, row in fills.iterrows():
            assert row["notional"] == pytest.approx(row["qty"] * row["price"], abs=1e-9)

    def test_funding_matches_stored_events_exactly(self, golden_result: BacktestResult) -> None:
        # 6 events stored in-window; the BTC 08:00 event finds a FLAT book and
        # must NOT settle; the other 5 settle interval-aware (4h ETH vs 8h BTC)
        # purely off the events table — no clock anywhere.
        g = Golden()
        funding = golden_result.funding_events
        assert len(funding) == 5
        assert golden_result.counters["funding_events_applied"] == 5
        expected = [
            (ETH, T0 + 4 * HOUR, 2e-4, 50.0, 100.0, -1.0),
            (ETH, T0 + 8 * HOUR, -1e-4, 50.0, 100.0, 0.5),
            (ETH, T0 + 12 * HOUR, 5e-5, 50.0, 100.0, -0.25),
            (BTC, T0 + 16 * HOUR, 1e-4, 104.0, -g.qty4, g.btc_pay16),
            (ETH, T0 + 16 * HOUR, 1e-4, 50.0, 100.0, -0.5),
        ]
        for row, (iid, ts, rate, mark, qty, payment) in zip(
            funding.itertuples(index=False), expected, strict=True
        ):
            assert row.instrument_id == iid
            assert row.ts_funding == ts
            assert row.rate == rate
            assert row.mark_price == mark
            assert row.position_qty == pytest.approx(qty, abs=1e-12)
            assert row.payment_quote == pytest.approx(payment, abs=1e-12)
        # the skipped event is genuinely absent
        btc_rows = funding[funding["instrument_id"] == BTC]
        assert (btc_rows["ts_funding"] != T0 + 8 * HOUR).all()

    def test_counters_summary_and_identity(self, golden_result: BacktestResult) -> None:
        g = Golden()
        c = golden_result.counters
        assert c["bars_processed"] == 16
        assert c["orders_decided"] == 4  # C1: 2, C6: 1, C9: 1
        assert c["fills_applied"] == 4
        assert c["unfilled_final_bar"] == 0
        assert c["dropped_missing_next_bar"] == 0
        assert c["forced_flat"] == 0
        s = golden_result.summary
        assert s.final_equity == pytest.approx(g.equity[-1], abs=1e-9)
        assert s.fees_paid == pytest.approx(g.total_fees, abs=1e-9)
        assert s.funding_net == pytest.approx(g.total_funding, abs=1e-9)
        # fundamental identity: equity == cash + sum(qty*mark) at the end
        assert g.equity[-1] == pytest.approx(g.final_cash - g.qty4 * 104.0 + 100.0 * 50.0, abs=1e-9)
        # final positions snapshot: BTC short qty4, ETH long 100
        last = golden_result.positions[golden_result.positions["ts"] == T0 + 16 * HOUR]
        by_id = {row.instrument_id: row for row in last.itertuples(index=False)}
        assert by_id[BTC].qty == pytest.approx(-g.qty4)
        assert by_id[ETH].qty == pytest.approx(100.0)
        # orders frame: all four decisions filled
        assert list(golden_result.orders["status"]) == ["filled"] * 4
        # config echo
        assert golden_result.config["start"] == T0
        assert golden_result.config["end"] == T0 + 16 * HOUR
        assert golden_result.config["instrument_ids"] == [BTC, ETH]


# -------------------------------------------------------------- contract edges


def test_signal_on_final_bar_yields_zero_fills_and_no_exception(tmp_path: Path) -> None:
    bars = two_asset_bars(4)
    engine = build_engine(tmp_path, bars, [], [make_instrument(BTC), make_instrument(ETH)])
    final_close = T0 + 4 * HOUR
    result = engine.run(
        ScriptedStrategy({final_close: {BTC: 0.5}}),
        [BTC, ETH],
        start=T0,
        end=T0 + 4 * HOUR,
    )
    assert result.counters["unfilled_final_bar"] == 1
    assert result.counters["fills_applied"] == 0
    assert len(result.fills) == 0
    assert list(result.orders["status"]) == ["unfilled_final_bar"]


def test_gap_at_next_bar_drops_order(tmp_path: Path) -> None:
    # ETH is missing the bar opening at the decision close (T0+1h): its order
    # must be DROPPED (never filled later / at a synthetic price). BTC fills.
    bars = [
        r
        for r in two_asset_bars(6)
        if not (r["instrument_id"] == ETH and r["ts_open"] == T0 + HOUR)
    ]
    engine = build_engine(tmp_path, bars, [], [make_instrument(BTC), make_instrument(ETH)])
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.1, ETH: 0.1}}),
        [BTC, ETH],
        start=T0,
        end=T0 + 6 * HOUR,
    )
    assert result.counters["dropped_missing_next_bar"] == 1
    assert result.counters["fills_applied"] == 1
    assert list(result.fills["instrument_id"]) == [BTC]
    status = dict(zip(result.orders["instrument_id"], result.orders["status"], strict=True))
    assert status[ETH] == "dropped_missing_next_bar"
    assert status[BTC] == "filled"


def test_delisting_force_flat_at_last_close(tmp_path: Path) -> None:
    # ETH bars stop after ts_open T0+5h (last close T0+6h) while BTC and the
    # run continue to T0+12h: the open ETH position is force-flatted at its
    # last close (50.0) with taker fee — counted, logged, conservative.
    bars = [r for r in two_asset_bars(12) if r["instrument_id"] == BTC]
    bars += [bar_row(ETH, T0 + k * HOUR, open_=50.0, close=50.0) for k in range(6)]
    engine = build_engine(tmp_path, bars, [], [make_instrument(BTC), make_instrument(ETH)])
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {ETH: 0.1}}),
        [BTC, ETH],
        start=T0,
        end=T0 + 12 * HOUR,
    )
    assert result.counters["forced_flat"] == 1
    # buy 200 @ ~50 at C2, force-flat 200 @ exactly 50.0 at C6
    fills = result.fills
    assert len(fills) == 2
    flat = fills.iloc[1]
    assert flat["instrument_id"] == ETH
    assert flat["side"] == "sell"
    assert flat["qty"] == 200.0
    assert flat["price"] == 50.0  # last available close, no slippage model
    assert flat["fee"] == pytest.approx(5e-4 * 200.0 * 50.0, abs=1e-12)  # taker cost
    assert flat["ts"] == T0 + 6 * HOUR
    assert flat["reason"] == "forced_flat"
    # position is gone for the rest of the run
    late = result.positions[result.positions["ts"] > T0 + 6 * HOUR]
    assert (late["instrument_id"] != ETH).all()
    assert "forced_flat" in set(result.orders["status"])


def test_no_trade_band_skips_small_deltas(tmp_path: Path) -> None:
    # |delta| = 0.0005 * equity = 50 < band 0.001 * 100_000 = 100 -> suppressed.
    engine = build_engine(
        tmp_path, two_asset_bars(4), [], [make_instrument(BTC), make_instrument(ETH)]
    )
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.0005}}),
        [BTC, ETH],
        start=T0,
        end=T0 + 4 * HOUR,
    )
    assert result.counters["skipped_no_trade_band"] == 1
    assert result.counters["fills_applied"] == 0
    assert list(result.orders["status"]) == ["skipped_no_trade_band"]


def test_min_notional_filter_skips(tmp_path: Path) -> None:
    # delta 150 > band 100; qty rounds to 1 lot -> notional 100 < min_notional
    # 150 -> skipped_below_min (v1 lot/min discretization).
    inst = Instrument(
        instrument_id=BTC,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=150.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )
    bars = [r for r in two_asset_bars(4) if r["instrument_id"] == BTC]
    engine = build_engine(tmp_path, bars, [], [inst])
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.0015}}),  # delta = 150 USDT
        [BTC],
        start=T0,
        end=T0 + 4 * HOUR,
    )
    assert result.counters["skipped_below_min"] == 1
    assert result.counters["fills_applied"] == 0


def test_unknown_target_instrument_raises(tmp_path: Path) -> None:
    bars = [r for r in two_asset_bars(4) if r["instrument_id"] == BTC]
    engine = build_engine(tmp_path, bars, [], [make_instrument(BTC)])
    with pytest.raises(ValueError, match="unknown instrument"):
        engine.run(
            ScriptedStrategy({T0 + HOUR: {"BINANCE:PERP:XRPUSDT": 0.1}}),
            [BTC],
            start=T0,
            end=T0 + 4 * HOUR,
        )


class _PITProbe:
    """Strategy that records any bar visible beyond the decision close."""

    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        self.violations: list[tuple[int, int]] = []
        self.calls = 0

    def on_bar_close(self, ctx: StrategyContext) -> dict[str, float]:
        self.calls += 1
        tbl = ctx.bars(self.ids, 6)
        for v in tbl.column("ts_open").cast(pa.int64()).to_pylist():
            # newest legal bar OPEN is ts - 1h (it closes exactly at ts)
            if int(v) > ctx.ts - HOUR:
                self.violations.append((ctx.ts, int(v)))
        return {}


def test_strategy_context_is_pit_truncated(tmp_path: Path) -> None:
    engine = build_engine(
        tmp_path, two_asset_bars(8), [], [make_instrument(BTC), make_instrument(ETH)]
    )
    probe = _PITProbe([BTC, ETH])
    engine.run(probe, [BTC, ETH], start=T0, end=T0 + 8 * HOUR)
    assert probe.calls == 8
    assert probe.violations == []


def test_rank_strategy_demo_buys_top_performer(tmp_path: Path) -> None:
    # ETH trends up, BTC is flat: with top_k=1 the demo must go long ETH only,
    # at the first rebalance with a full lookback window, filling at t+1 open.
    rows: list[dict[str, object]] = []
    for k in range(12):
        rows.append(bar_row(BTC, T0 + k * HOUR, open_=100.0, close=100.0))
        rows.append(bar_row(ETH, T0 + k * HOUR, open_=50.0 + 0.5 * k, close=50.0 + 0.5 * k))
    engine = build_engine(tmp_path, rows, [], [make_instrument(BTC), make_instrument(ETH)])
    strategy = RankStrategy(top_k=1, lookback_bars=4, rebalance_bars=6)
    result = engine.run(strategy, [BTC, ETH], start=T0, end=T0 + 12 * HOUR)
    # first attempt at C1 lacks a full window ({} -> no orders); the rebalance
    # at C7 ranks ETH > BTC and emits {ETH: 1.0, BTC: 0.0}
    assert result.counters["fills_applied"] == 1
    fill = result.fills.iloc[0]
    assert fill["instrument_id"] == ETH
    assert fill["side"] == "buy"
    assert fill["ts"] == T0 + 7 * HOUR  # decided at C7, filled at bar-7 open
    # BTC explicit 0.0 with no position -> suppressed by the band
    assert result.counters["skipped_no_trade_band"] >= 1


# ------------------------------------------------------------ cost inputs


def hourly_bars(
    instrument_id: str, start: int, n_bars: int, *, qv: float = 1_000.0
) -> list[dict[str, object]]:
    """Alternating 100/101 closes: |log return| constant -> exact EWMA sigma."""
    rows = []
    for k in range(n_bars):
        close = 101.0 if k % 2 else 100.0
        rows.append(
            bar_row(instrument_id, start + k * HOUR, open_=100.0, close=close, quote_volume=qv)
        )
    return rows


def test_lake_cost_inputs_exact_values(tmp_path: Path) -> None:
    # 34 days of warmup bars before the run start; constant quote_volume 1000
    # -> every complete UTC day sums to 24_000 -> 30d median = 24_000 exactly.
    # Alternating 100/101 closes -> r^2 = ln(1.01)^2 constant -> EWMA variance
    # equals it exactly once min_periods pass -> sigma = ln(1.01) * sqrt(24).
    start = T0
    end = T0 + 2 * HOUR
    bars = hourly_bars(BTC, start - 34 * DAY, 34 * 24 + 2)
    paths = LakePaths(tmp_path / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, ohlcv_table(bars))
    provider = LakeCostInputs(PITDataReader(paths), [BTC], start=start, end=end)
    adv, sigma = provider.cost_inputs(BTC, start + HOUR)
    assert adv == pytest.approx(24_000.0, abs=1e-9)
    assert sigma == pytest.approx(math.log(1.01) * math.sqrt(24.0), rel=1e-9)


def test_lake_cost_inputs_unavailable_is_nan(tmp_path: Path) -> None:
    bars = hourly_bars(BTC, T0, 12)
    paths = LakePaths(tmp_path / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, ohlcv_table(bars))
    provider = LakeCostInputs(PITDataReader(paths), [BTC], start=T0, end=T0 + 12 * HOUR)
    adv, sigma = provider.cost_inputs(BTC, T0 + 11 * HOUR)  # nowhere near 30d of history
    assert math.isnan(adv) and math.isnan(sigma)
    adv2, sigma2 = provider.cost_inputs("BINANCE:PERP:XRPUSDT", T0 + 11 * HOUR)
    assert math.isnan(adv2) and math.isnan(sigma2)
    adv3, sigma3 = provider.cost_inputs(BTC, T0 + 11 * HOUR + 1)  # off-grid ts
    assert math.isnan(adv3) and math.isnan(sigma3)


def test_default_provider_drops_orders_without_history(tmp_path: Path) -> None:
    # No injected provider + a 16-bar lake: LakeCostInputs yields NaN, so the
    # order is dropped LOUDLY (counter + status) instead of guessing a cost.
    engine = build_engine(
        tmp_path,
        two_asset_bars(16),
        [],
        [make_instrument(BTC), make_instrument(ETH)],
        use_static_cost_inputs=False,
    )
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.1}}),
        [BTC, ETH],
        start=T0,
        end=T0 + 16 * HOUR,
    )
    assert result.counters["dropped_no_cost_inputs"] == 1
    assert result.counters["fills_applied"] == 0
    assert list(result.orders["status"]) == ["dropped_no_cost_inputs"]


# ------------------------------------------------------------- run validation


def test_run_validation_errors(tmp_path: Path) -> None:
    engine = build_engine(
        tmp_path, two_asset_bars(4), [], [make_instrument(BTC), make_instrument(ETH)]
    )
    strat = ScriptedStrategy({})
    with pytest.raises(ValueError, match="non-empty"):
        engine.run(strat, [], start=T0, end=T0 + 4 * HOUR)
    with pytest.raises(ValueError, match="must be >"):
        engine.run(strat, [BTC], start=T0, end=T0)
    with pytest.raises(ValueError, match="aligned"):
        engine.run(strat, [BTC], start=T0 + 1, end=T0 + 4 * HOUR)
    with pytest.raises(ValueError, match="unknown instrument"):
        engine.run(strat, ["BINANCE:PERP:XRPUSDT"], start=T0, end=T0 + 4 * HOUR)
    with pytest.raises(ValueError, match="initial_cash"):
        engine.run(strat, [BTC], start=T0, end=T0 + 4 * HOUR, initial_cash=0.0)
    with pytest.raises(ValueError, match="at least 2 bar closes"):
        # bars exist only from T0; an empty earlier window has no closes
        engine.run(strat, [BTC], start=T0 - 4 * HOUR, end=T0)


def test_default_cost_inputs_rejects_non_h1(tmp_path: Path) -> None:
    paths = LakePaths(tmp_path / "lake")
    store = InstrumentStore(tmp_path / "ops.sqlite")
    with pytest.raises(ValueError, match="1h-only"):
        EventDrivenBacktester(PITDataReader(paths), store, TransactionCostModel(), tf=Timeframe.H4)


def test_equity_series_is_consumable_by_analytics(golden_result: BacktestResult) -> None:
    # summarize() ran inside the engine; spot-check the per-bar diagnostics
    # exist and the curve is well-formed (strictly increasing int index).
    eq = golden_result.equity
    assert eq.dtype == "float64"
    assert list(eq.index) == sorted(set(eq.index))
    assert golden_result.summary.n_periods == 15
    assert golden_result.summary.initial_equity == pytest.approx(CASH0)


# ------------------------------------------------- equity D1 session-grid (P2)

# Real XNYS sessions around a weekend: Thu/Fri/Mon/Tue (Sat+Sun absent).
EQ_THU = 1_704_326_400_000  # 2024-01-04T00:00:00Z (Thursday session open)
EQ_FRI = 1_704_412_800_000  # 2024-01-05T00:00:00Z (Friday)
EQ_MON = 1_704_672_000_000  # 2024-01-08T00:00:00Z (Monday — Sat/Sun hopped)
EQ_TUE = 1_704_758_400_000  # 2024-01-09T00:00:00Z (Tuesday)
EQ_WED = 1_704_844_800_000  # 2024-01-10T00:00:00Z (Wednesday — run end)
AAPL = "XNAS:CASH:AAPLUSD"  # canonical equity id (<EXCHANGE>:CASH:<TICKER>USD)


def make_equity_instrument(instrument_id: str) -> Instrument:
    ticker = instrument_id.split(":")[2].removesuffix("USD")
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.EQUITY,
        market_type=MarketType.CASH,
        base=ticker,
        quote="USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=1.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=0.0,
        taker_fee_bps=0.0,
        funding_interval_hours=None,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def test_equity_d1_fills_via_next_session_open_hopping_weekend(tmp_path: Path) -> None:
    # The §3.3 fix: on the XNYS session calendar an order whose decision bar is the
    # FRIDAY session fills at MONDAY's open (the next *session*), never dropped as a
    # missing Saturday slot. A weekend bar never prints, yet the fill lands. The grid
    # value for a decision on the Friday-close is EQ_MON == next_bar_open(EQ_FRI), and
    # the order then fills against bars.get(EQ_MON) = the Monday bar's open.
    bars = [
        bar_row(AAPL, EQ_THU, open_=100.0, close=100.0),
        bar_row(AAPL, EQ_FRI, open_=100.0, close=100.0),
        bar_row(AAPL, EQ_MON, open_=110.0, close=120.0),  # Monday opens at 110
        bar_row(AAPL, EQ_TUE, open_=120.0, close=120.0),
    ]
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV_1D, ohlcv_table(bars))  # D1 reads route to ohlcv_1d
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(make_equity_instrument(AAPL), as_of=1)
    engine = EventDrivenBacktester(
        PITDataReader(paths),
        store,
        TransactionCostModel(),
        tf=Timeframe.D1,
        asset_class=AssetClass.EQUITY,
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
        no_trade_band_frac=0.0,
    )
    # Decide a long on the FRIDAY session (grid value EQ_MON = next_bar_open(EQ_FRI),
    # whose floor_bar(EQ_MON-1) decision bar is the Friday session); the order must
    # fill at Monday's open (110.0), hopping Sat/Sun — not at a phantom weekend slot.
    result = engine.run(
        ScriptedStrategy({EQ_MON: {AAPL: 1.0}}),
        [AAPL],
        start=EQ_THU,
        end=EQ_WED,
    )
    assert result.counters["dropped_missing_next_bar"] == 0
    assert result.counters["fills_applied"] == 1
    assert len(result.fills) == 1
    fill = result.fills.iloc[0]
    assert fill["instrument_id"] == AAPL
    # Fill at the MONDAY open (110.0 + buy slippage), not a phantom weekend slot.
    assert fill["price"] == pytest.approx(110.0, rel=2e-3)
    assert int(fill["ts"]) == EQ_MON  # fills at the Monday bar's open ts
    assert result.config["asset_class"] == AssetClass.EQUITY.value
    assert result.config["tf"] == Timeframe.D1.value


def test_equity_d1_grid_hops_sessions_not_calendar_days(tmp_path: Path) -> None:
    # The decision grid is the set of session closes mapped to next-session opens:
    # {Fri, Mon, Tue, Wed} — four steps, NOT a calendar-day grid that would insert
    # phantom Sat/Sun rows. bars_processed counts exactly the four grid steps.
    bars = [
        bar_row(AAPL, EQ_THU, open_=100.0, close=100.0),
        bar_row(AAPL, EQ_FRI, open_=100.0, close=100.0),
        bar_row(AAPL, EQ_MON, open_=100.0, close=100.0),
        bar_row(AAPL, EQ_TUE, open_=100.0, close=100.0),
    ]
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV_1D, ohlcv_table(bars))  # D1 reads route to ohlcv_1d
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(make_equity_instrument(AAPL), as_of=1)
    engine = EventDrivenBacktester(
        PITDataReader(paths),
        store,
        TransactionCostModel(),
        tf=Timeframe.D1,
        asset_class=AssetClass.EQUITY,
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
    )
    result = engine.run(ScriptedStrategy({}), [AAPL], start=EQ_THU, end=EQ_WED)
    # grid = {nbo(Thu)=Fri, nbo(Fri)=Mon, nbo(Mon)=Tue, nbo(Tue)=Wed} -> 4 steps.
    assert result.counters["bars_processed"] == 4
