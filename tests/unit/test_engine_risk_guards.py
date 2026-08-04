"""Risk-guard tests for alphaforge.backtest.engine — honest-curve fixes.

Two reviewed defects, closed and pinned here (the cardinal rule: every number
the engine shows must be honest about what produced it):

* **F-F (curve correctness)** — a risk-REDUCING order must always execute,
  however small: it bypasses the no-trade band AND the min_qty/min_notional
  skip and is emitted ``reduce_only=True``, counted ``flatten_residual_forced``
  when it slips past the min filters. An all-zero target therefore reaches
  EXACTLY flat (no orphaned sub-min residual silently accruing PnL/funding),
  while a sub-min OPENING order is still ``skipped_below_min``.
* **F-C-ADV (cost correctness)** — a non-reduce-only order whose fill notional
  exceeds 1% of the decision bar's ADV is CLAMPED to exactly 1% of ADV (lot-
  floored) and counted ``orders_adv_clamped``, keeping the sqrt-impact law in
  its valid band; a within-band order is untouched, fills/fees unchanged.

All lakes are built in tmp_path (offline, deterministic); no real data dirs.
"""

from __future__ import annotations

import math
from pathlib import Path

import pyarrow as pa
import pytest

from alphaforge.backtest.engine import COUNTER_NAMES, EventDrivenBacktester, ScriptedStrategy
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Ms
from alphaforge.core.types import AssetClass, MarketType, OrderRequest, OrderType, Side
from alphaforge.costs import MAX_ADV_PARTICIPATION, TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter

HOUR = 3_600_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z — UTC midnight (1h aligned)
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z

BTC = "BINANCE:PERP:BTCUSDT"

SIGMA = 0.02
CASH0 = 100_000.0


def imp(notional: float, adv: float) -> float:
    """Square-root impact: Y * sigma * sqrt(Q/ADV) with Y = 1.0 and SIGMA."""
    return 1.0 * SIGMA * math.sqrt(notional / adv)


def slip(notional: float, adv: float) -> float:
    """Half-spread (2.5 bps) + impact + latency (2 bps): the fill-price shift."""
    return 2.5e-4 + imp(notional, adv) + 2e-4


# ------------------------------------------------------------------- fixtures


def make_instrument(
    *,
    instrument_id: str = BTC,
    lot_size: float = 1.0,
    min_qty: float = 1.0,
    min_notional: float = 10.0,
) -> Instrument:
    symbol = instrument_id.split(":")[2]
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=symbol.removesuffix("USDT"),
        quote="USDT",
        tick_size=0.1,
        lot_size=lot_size,
        min_qty=min_qty,
        min_notional=min_notional,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def bar_row(ts_open: int, *, close: float = 100.0) -> dict[str, object]:
    return {
        "instrument_id": BTC,
        "ts_open": ts_open,
        "open": 100.0,  # constant open keeps every fill hand-computable
        "high": max(100.0, close) * 1.01,
        "low": min(100.0, close) * 0.99,
        "close": close,
        "volume": 10.0,
        "quote_volume": 1_000.0,
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


class _StaticCostInputs:
    """Local fixed (adv_quote, sigma_daily) provider so tests pin ADV exactly."""

    def __init__(self, *, adv_quote: float, sigma_daily: float = SIGMA) -> None:
        self._adv = adv_quote
        self._sigma = sigma_daily

    def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
        del instrument_id, decision_ts
        return (self._adv, self._sigma)


def build_engine(
    tmp_path: Path,
    bars: list[dict[str, object]],
    inst: Instrument,
    *,
    adv_quote: float,
    no_trade_band_frac: float = 0.001,
    max_order_adv_frac: float = 0.01,
    clamp_reduce_only_adv: bool = False,
) -> EventDrivenBacktester:
    paths = LakePaths(tmp_path / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, ohlcv_table(bars))
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(inst, as_of=1)
    return EventDrivenBacktester(
        PITDataReader(paths),
        store,
        TransactionCostModel(),
        cost_inputs=_StaticCostInputs(adv_quote=adv_quote),
        no_trade_band_frac=no_trade_band_frac,
        max_order_adv_frac=max_order_adv_frac,
        clamp_reduce_only_adv=clamp_reduce_only_adv,
    )


def flat_bars(n_bars: int, *, close: float = 100.0) -> list[dict[str, object]]:
    return [bar_row(T0 + k * HOUR, close=close) for k in range(n_bars)]


def _final_position_qty(result: object, ts: int) -> float:
    pos = result.positions[result.positions["ts"] == ts]  # type: ignore[attr-defined]
    rows = list(pos.itertuples(index=False))
    return float(rows[0].qty) if rows else 0.0


# ------------------------------------------------------------- counter contract


def test_new_counters_in_counter_names() -> None:
    # The result always carries these (0 if unused): verifying the tuple is the
    # single source of truth that the build_result loop initializes from.
    assert "flatten_residual_forced" in COUNTER_NAMES
    assert "orders_adv_clamped" in COUNTER_NAMES
    assert len(set(COUNTER_NAMES)) == len(COUNTER_NAMES)  # no duplicates


# ---------------------------------------------------------------- F-F: reduce-only


def test_all_zero_target_reaches_exactly_flat(tmp_path: Path) -> None:
    # Open 100 @ 100 (notional 10_000), then target 0.0: the flatten is above
    # min so it is reduce_only (not a forced residual) and the book ends EXACTLY
    # flat — the absorbing flatten can never orphan the position.
    inst = make_instrument(min_notional=10.0)
    engine = build_engine(tmp_path, flat_bars(8), inst, adv_quote=1e8)
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.10}, T0 + 4 * HOUR: {BTC: 0.0}}),
        [BTC],
        start=T0,
        end=T0 + 8 * HOUR,
        initial_cash=CASH0,
    )
    assert result.counters["fills_applied"] == 2  # open + flatten
    # the flatten leg is full-size (>= min) -> a normal reduce, not forced
    assert result.counters["flatten_residual_forced"] == 0
    # book is flat for every snapshot after the flatten executes (C6 open)
    flat_after = result.positions[result.positions["ts"] >= T0 + 5 * HOUR]
    assert flat_after.empty or (flat_after["qty"] == 0.0).all()
    assert _final_position_qty(result, T0 + 8 * HOUR) == 0.0


def test_sub_min_flatten_residual_is_forced_through(tmp_path: Path) -> None:
    # Open 100 @ 100 (notional 10_000, >= min_notional 500), then target a
    # weight leaving 97 held: the reduce is 3 lots = 300 notional < min_notional
    # 500. A naive min-filter would SKIP it, orphaning the residual. The fix
    # FORCES it (reduce_only) and counts flatten_residual_forced.
    inst = make_instrument(min_notional=500.0)
    engine = build_engine(tmp_path, flat_bars(8), inst, adv_quote=1e8)
    # equity stays ~ initial cash; 0.097 * ~equity / 100 floors to 97 held.
    result = engine.run(
        ScriptedStrategy(
            {
                T0 + HOUR: {BTC: 0.10},  # open ~100 long (notional 10_000)
                T0 + 4 * HOUR: {BTC: 0.097},  # reduce by ~3 lots (300 < 500)
            }
        ),
        [BTC],
        start=T0,
        end=T0 + 8 * HOUR,
        initial_cash=CASH0,
    )
    assert result.counters["flatten_residual_forced"] == 1
    assert result.counters["skipped_below_min"] == 0
    assert result.counters["fills_applied"] == 2  # open + forced reduce
    # the forced order traded a sub-min size and the book de-risked toward zero
    final_qty = _final_position_qty(result, T0 + 8 * HOUR)
    assert 90.0 <= final_qty < 100.0  # reduced, not skipped, not flat
    # the reducing fill is a SELL of 3 (shrinks the long)
    reduce_fill = result.fills.iloc[1]
    assert reduce_fill["side"] == "sell"
    assert reduce_fill["qty"] == pytest.approx(100.0 - final_qty)


def test_sub_min_opening_order_is_still_skipped(tmp_path: Path) -> None:
    # No position held; target a weight whose order rounds to 1 lot = 100
    # notional < min_notional 500: an OPENING order below min is still skipped
    # (the exemption is for de-risking only, never for putting risk ON).
    inst = make_instrument(min_notional=500.0)
    engine = build_engine(tmp_path, flat_bars(6), inst, adv_quote=1e8)
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.0015}}),  # delta ~150 -> 1 lot, 100 notional
        [BTC],
        start=T0,
        end=T0 + 6 * HOUR,
        initial_cash=CASH0,
    )
    assert result.counters["skipped_below_min"] == 1
    assert result.counters["flatten_residual_forced"] == 0
    assert result.counters["fills_applied"] == 0
    assert list(result.orders["status"]) == ["skipped_below_min"]


def test_reduce_bypasses_no_trade_band(tmp_path: Path) -> None:
    # Open 100, then reduce by a delta SMALLER than the no-trade band: a tiny
    # de-risk must still execute (you can always shrink risk), so it does NOT
    # get suppressed as skipped_no_trade_band. band = 0.001*equity ~ 100 USDT.
    inst = make_instrument(min_notional=10.0)
    engine = build_engine(tmp_path, flat_bars(8), inst, adv_quote=1e8, no_trade_band_frac=0.01)
    # band ~ 0.01*100_000 = 1_000; reduce by 1 lot (100) is below band but is a
    # de-risk -> must trade. (A 0.099 target on a 100-held book reduces by 1.)
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.10}, T0 + 4 * HOUR: {BTC: 0.099}}),
        [BTC],
        start=T0,
        end=T0 + 8 * HOUR,
        initial_cash=CASH0,
    )
    assert result.counters["fills_applied"] == 2  # open + sub-band reduce
    reduce_fill = result.fills.iloc[1]
    assert reduce_fill["side"] == "sell"
    assert reduce_fill["qty"] == pytest.approx(1.0)


# ------------------------------------------------------------- F-C-ADV: clamp


def test_oversized_order_clamped_to_one_percent_of_adv(tmp_path: Path) -> None:
    # adv_quote = 200_000 -> 1% cap = 2_000 notional. Target asks for ~10_000
    # notional (qty 100 @ open 100). The order is CLAMPED to floor(2_000/100) =
    # 20 lots and counted; the impact law then sees only the in-band 2_000.
    adv = 200_000.0
    inst = make_instrument(min_notional=10.0)
    engine = build_engine(tmp_path, flat_bars(6), inst, adv_quote=adv, max_order_adv_frac=0.01)
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.10}}),  # ~10_000 notional requested
        [BTC],
        start=T0,
        end=T0 + 6 * HOUR,
        initial_cash=CASH0,
    )
    assert result.counters["orders_adv_clamped"] == 1
    assert result.counters["fills_applied"] == 1
    fill = result.fills.iloc[0]
    assert fill["qty"] == pytest.approx(20.0)  # exactly 1% of ADV at the open
    # the artifact (orders frame) reflects the size that actually traded
    assert float(result.orders.iloc[0]["qty"]) == pytest.approx(20.0)
    # price priced at the CLAMPED notional (2_000), in the sqrt-law's valid band
    expected_price = 100.0 * (1.0 + slip(20.0 * 100.0, adv))
    assert fill["price"] == pytest.approx(expected_price, abs=1e-12)
    assert fill["fee"] == pytest.approx(5e-4 * 20.0 * expected_price, abs=1e-12)


def test_within_band_order_is_untouched_to_the_cent(tmp_path: Path) -> None:
    # adv_quote = 200_000 -> 1% cap = 2_000. Target asks for 1_000 notional
    # (qty 10 @ open 100) < cap: NOT clamped, fills/fees identical to the
    # no-guard engine. Golden-master-style: hand-computed to the cent.
    adv = 200_000.0
    inst = make_instrument(min_notional=10.0)
    engine = build_engine(tmp_path, flat_bars(6), inst, adv_quote=adv, max_order_adv_frac=0.01)
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.01}}),  # 0.01 * 100_000 = 1_000 notional
        [BTC],
        start=T0,
        end=T0 + 6 * HOUR,
        initial_cash=CASH0,
    )
    assert result.counters["orders_adv_clamped"] == 0
    assert result.counters["fills_applied"] == 1
    fill = result.fills.iloc[0]
    assert fill["qty"] == pytest.approx(10.0)  # untouched
    # BUY 10 @ open 100: N = 1_000, p = 100*(1+slip(1_000,200_000)), to the cent
    p = 100.0 * (1.0 + slip(1_000.0, adv))
    fee = 5e-4 * 10.0 * p
    assert fill["price"] == pytest.approx(p, abs=1e-12)
    assert fill["fee"] == pytest.approx(fee, abs=1e-12)
    # equity == cash + qty*mark at the end (fundamental identity, to the cent)
    cash = CASH0 - (10.0 * p + fee)
    expected_equity = cash + 10.0 * 100.0
    assert result.equity.iloc[-1] == pytest.approx(expected_equity, abs=1e-9)


def test_reduce_only_order_bypasses_adv_clamp(tmp_path: Path) -> None:
    # A de-risking order is exempt from the ADV cap (execDesign §7.1 check 7:
    # you must always be able to flatten). Open 100 with a generous ADV, then
    # flatten with a tighter ADV (300_000): the flatten's 10_000 notional is
    # 3.3% of ADV -> ABOVE the 1% clamp (would clamp a non-reduce order) but
    # still inside the cost model's 5% sqrt-law band, so it prices and is NOT
    # clamped because it is reduce_only.
    inst = make_instrument(min_notional=10.0)
    paths = LakePaths(tmp_path / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, ohlcv_table(flat_bars(8)))
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(inst, as_of=1)

    class _StepAdv:
        # generous ADV at the open decision, tighter ADV at the flatten decision.
        def cost_inputs(self, instrument_id: str, decision_ts: Ms) -> tuple[float, float]:
            del instrument_id
            return (1e8 if decision_ts <= T0 + HOUR else 300_000.0, SIGMA)

    engine = EventDrivenBacktester(
        PITDataReader(paths),
        store,
        TransactionCostModel(),
        cost_inputs=_StepAdv(),
        max_order_adv_frac=0.01,
    )
    result = engine.run(
        ScriptedStrategy({T0 + HOUR: {BTC: 0.10}, T0 + 4 * HOUR: {BTC: 0.0}}),
        [BTC],
        start=T0,
        end=T0 + 8 * HOUR,
        initial_cash=CASH0,
    )
    # flatten is reduce_only -> exempt from the clamp; both legs fill at full size
    assert result.counters["orders_adv_clamped"] == 0
    assert result.counters["fills_applied"] == 2
    assert result.fills.iloc[1]["qty"] == pytest.approx(100.0)  # full flatten, uncapped
    assert _final_position_qty(result, T0 + 8 * HOUR) == 0.0


def test_max_order_adv_frac_validation(tmp_path: Path) -> None:
    # Invalid frac is rejected at construction (finite and within (0, 5% ADV]).
    reader = PITDataReader(LakePaths(tmp_path / "lake"))
    store = InstrumentStore(tmp_path / "ops.sqlite")
    for bad in (0.0, -0.01, 0.06, math.nan, math.inf):
        with pytest.raises(ValueError, match="max_order_adv_frac"):
            EventDrivenBacktester(
                reader,
                store,
                TransactionCostModel(),
                max_order_adv_frac=bad,
            )


# ------------------------------------------------- F-C-ADV: reduce-only de-risk clamp (opt-in)


def test_reduce_only_clamp_opt_in(tmp_path: Path) -> None:
    """A reduce-only (de-risking) flatten larger than 5% of ADV bypasses the cap by default
    (the golden-master contract: de-risking is never blocked), but with
    ``clamp_reduce_only_adv`` ON it clamps at the 5%-ADV impact-law edge — de-risking fast
    while staying priceable — instead of crashing the sqrt-impact model. The remainder closes
    on the next bar(s)."""
    adv = 200_000.0  # 5% = 10_000 notional = 100 qty @ ref 100; 1% build cap = 2_000
    inst = make_instrument()
    big_reduce = OrderRequest(
        client_order_id="t-reduce",
        instrument_id=BTC,
        side=Side.SELL,
        qty=200.0,  # 200 @ ref 100 = 20_000 notional = 10% of ADV (> the 5% law edge)
        order_type=OrderType.MARKET,
        reduce_only=True,
        decision_ts=T0 + HOUR,
        decision_price=100.0,
        reason="flatten",
    )

    # default OFF -> bypass entirely, full de-risk in one bar (unchanged behaviour)
    eng_off = build_engine(tmp_path / "off", flat_bars(2), inst, adv_quote=adv)
    counters_off = dict.fromkeys(COUNTER_NAMES, 0)
    out_off = eng_off._clamp_to_adv(big_reduce, inst, 100.0, adv, counters_off, {})
    assert out_off.qty == pytest.approx(200.0)
    assert counters_off["orders_reduce_adv_clamped"] == 0

    # ON -> clamp to 5% of ADV (floor(10_000 / 100) = 100 lots), counted, strictly in-band
    eng_on = build_engine(
        tmp_path / "on", flat_bars(2), inst, adv_quote=adv, clamp_reduce_only_adv=True
    )
    counters_on = dict.fromkeys(COUNTER_NAMES, 0)
    out_on = eng_on._clamp_to_adv(big_reduce, inst, 100.0, adv, counters_on, {})
    assert out_on.qty == pytest.approx(100.0)
    assert out_on.qty * 100.0 <= MAX_ADV_PARTICIPATION * adv  # priceable: never > 5% of ADV
    assert counters_on["orders_reduce_adv_clamped"] == 1


def test_reduce_only_within_band_untouched_either_way(tmp_path: Path) -> None:
    """A small reduce-only order (<= 5% of ADV) is never clamped, ON or OFF — the opt-in only
    bites the oversized-flatten case, so normal de-risking is byte-identical."""
    adv = 200_000.0  # 5% = 10_000 notional; a 50-qty reduce = 5_000 notional is in-band
    inst = make_instrument()
    small_reduce = OrderRequest(
        client_order_id="t-small",
        instrument_id=BTC,
        side=Side.SELL,
        qty=50.0,
        order_type=OrderType.MARKET,
        reduce_only=True,
        decision_ts=T0 + HOUR,
        decision_price=100.0,
        reason="reduce",
    )
    eng_on = build_engine(
        tmp_path, flat_bars(2), inst, adv_quote=adv, clamp_reduce_only_adv=True
    )
    counters = dict.fromkeys(COUNTER_NAMES, 0)
    out = eng_on._clamp_to_adv(small_reduce, inst, 100.0, adv, counters, {})
    assert out.qty == pytest.approx(50.0)
    assert counters["orders_reduce_adv_clamped"] == 0
