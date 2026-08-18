"""Phase-5 FULL golden master — the execDesign.md §4.5 acceptance gate.

Part 1 (offline, tmp_path): a 3-instrument, 30-bar scripted run exercising
opens, an add, a partial close, a long->short FLIP, a gap-drop (missing next
bar), mixed 8h/4h funding straight from the STORED events table (including
events stored while flat, which must NOT settle), and a final-bar signal that
can never fill. EVERY fill price, fee, funding payment and the final equity is
asserted from hand-written arithmetic (derivations in the comments, rounded to
the cent there; assertions carry full float64 per the documented rounding
policy: internal full precision, rounding only at report render).

Part 2 (drift guard): LakeCostInputs (the engine's local ADV/sigma provider)
asserted NUMERICALLY EQUAL to the registered feature-library definitions
``adv_quote_30d`` / ``sigma_daily`` on a shared fixture — no silent formula
fork between the backtester and features/library/market.py.

Part 3 (reality check, READ-ONLY on the real lake at <repo>/data/lake,
skipped if absent): BTCUSDT, 2024-03-01 .. 2024-03-08 — the stored funding
table must contain exactly 21 settlements (3/day x 7, the Binance 8h
schedule), and an engine run holding a long the whole week must settle
exactly those events with ``payment == -qty * close_proxy * rate`` where
``close_proxy`` is the close of the 1h bar ending at the first grid close
>= ``ts_funding`` (the engine's documented mark proxy). Our events ARE
Binance's, and the engine reproduces them — never a hard-coded clock
(leakageCritique.md finding 6).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.backtest.engine import (
    EventDrivenBacktester,
    LakeCostInputs,
    ScriptedStrategy,
    StaticCostInputs,
)
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Ms
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry

HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_704_153_600_000  # 2024-01-02T00:00:00Z — UTC midnight (1h/4h/8h aligned)
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z

BTC = "BINANCE:PERP:BTCUSDT"  # 8h funding
ETH = "BINANCE:PERP:ETHUSDT"  # 4h funding (the mixed-interval instrument)
SOL = "BINANCE:PERP:SOLUSDT"  # 8h funding; bar 15 is a GAP (missing)

# Cost-model constants pinned for hand arithmetic: perp taker 5 bps,
# half-spread 2.5 bps, latency 2 bps, impact Y = 1.0 with StaticCostInputs
# ADV = 1e8 / sigma_daily = 0.02 — so for an order of notional N at ref price R:
#   impact   = 0.02 * sqrt(N / 1e8)
#   slip(N)  = 2.5e-4 + impact + 2e-4         (half_spread + impact + latency)
#   P_fill   = R * (1 + side_sign * slip(N))
#   fee      = 5e-4 * qty * P_fill
ADV = 1e8
SIGMA = 0.02
CASH0 = 100_000.0


def slip(notional: float) -> float:
    """half_spread + impact + latency for the pinned fixture constants."""
    return 2.5e-4 + SIGMA * math.sqrt(notional / ADV) + 2e-4


# ------------------------------------------------------------------ builders


def make_instrument(instrument_id: str, *, funding_hours: int) -> Instrument:
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


# ---------------------------------------------------------------- the script
#
# Bars k = 0..29 at T0 + k h (close of bar k prints at T0 + (k+1) h):
#   BTC: 100/100 through bar 9; bar 10 opens 100 closes 110 (the pump);
#        110/110 from bar 11.
#   ETH: 50/50 through bar 19; bar 20 opens 50 closes 48; 48/48 after.
#   SOL: 20/20 everywhere EXCEPT bar 15, which is MISSING (the gap).
#
# Stored funding events (12 stored; only 8 settle — the 4 ETH events that
# arrive while ETH is flat are stored but must never touch cash):
#   BTC 8h: +1e-4 @ +8h | +1e-4 @ +16h | -1e-4 @ +24h
#   ETH 4h: +1e-4 @ +4h | -2e-4 @ +8h | +1e-4 @ +12h | +3e-5 @ +16h   (flat!)
#           +5e-5 @ +20h | +1e-4 @ +24h | -2e-4 @ +28h                (held)
#   SOL 8h: -2e-4 @ +8h | +3e-4 @ +24h


def build_golden_lake(tmp_path: Path) -> tuple[PITDataReader, InstrumentStore]:
    rows: list[dict[str, object]] = []
    for k in range(30):
        if k <= 9:
            b_open, b_close = 100.0, 100.0
        elif k == 10:
            b_open, b_close = 100.0, 110.0
        else:
            b_open, b_close = 110.0, 110.0
        rows.append(bar_row(BTC, T0 + k * HOUR, open_=b_open, close=b_close))
        if k <= 19:
            e_open, e_close = 50.0, 50.0
        elif k == 20:
            e_open, e_close = 50.0, 48.0
        else:
            e_open, e_close = 48.0, 48.0
        rows.append(bar_row(ETH, T0 + k * HOUR, open_=e_open, close=e_close))
        if k != 15:  # the gap bar
            rows.append(bar_row(SOL, T0 + k * HOUR, open_=20.0, close=20.0))

    funding: list[tuple[str, int, float]] = [
        (BTC, T0 + 8 * HOUR, 1e-4),
        (BTC, T0 + 16 * HOUR, 1e-4),
        (BTC, T0 + 24 * HOUR, -1e-4),
        (ETH, T0 + 4 * HOUR, 1e-4),  # flat -> stored, never settles
        (ETH, T0 + 8 * HOUR, -2e-4),  # flat -> stored, never settles
        (ETH, T0 + 12 * HOUR, 1e-4),  # flat -> stored, never settles
        (ETH, T0 + 16 * HOUR, 3e-5),  # flat -> stored, never settles
        (ETH, T0 + 20 * HOUR, 5e-5),
        (ETH, T0 + 24 * HOUR, 1e-4),
        (ETH, T0 + 28 * HOUR, -2e-4),
        (SOL, T0 + 8 * HOUR, -2e-4),
        (SOL, T0 + 24 * HOUR, 3e-4),
    ]

    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV, ohlcv_table(rows))
    writer.write(Dataset.FUNDING, funding_table(funding))
    store = InstrumentStore(tmp_path / "ops.sqlite")
    for inst in (
        make_instrument(BTC, funding_hours=8),
        make_instrument(ETH, funding_hours=4),
        make_instrument(SOL, funding_hours=8),
    ):
        store.upsert(inst, as_of=1)
    return PITDataReader(paths), store


GOLDEN_SCRIPT: dict[Ms, dict[str, float]] = {
    T0 + 2 * HOUR: {BTC: 0.1005, SOL: 0.0401},  # OPEN both (fills at bar-2 opens)
    T0 + 5 * HOUR: {BTC: 0.1507},  # ADD to BTC
    T0 + 7 * HOUR: {SOL: 0.02},  # PARTIAL CLOSE SOL
    T0 + 11 * HOUR: {BTC: -0.05},  # FLIP BTC long 150 -> short 46
    T0 + 15 * HOUR: {SOL: 0.05},  # GAP-DROP: bar 15 missing -> dropped
    T0 + 17 * HOUR: {ETH: 0.04},  # OPEN ETH (4h funding goes live)
    T0 + 30 * HOUR: {BTC: 0.0},  # FINAL-BAR SIGNAL: no t+1, never fills
}


def test_golden_master_full(tmp_path: Path) -> None:
    reader, store = build_golden_lake(tmp_path)
    engine = EventDrivenBacktester(
        reader,
        store,
        TransactionCostModel(),
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
    )
    result = engine.run(
        ScriptedStrategy(GOLDEN_SCRIPT),
        [BTC, ETH, SOL],
        start=T0,
        end=T0 + 30 * HOUR,
        initial_cash=CASH0,
    )
    store.close()

    # ---------------------------------------------------------------- fills
    # F1: decided at C1 close (t = T0+2h, BTC close 100, equity 100_000):
    #     dN = 0.1005*100_000 = 10_050 -> 100.5 units -> floor 100 BUY.
    #     Filled at bar-2 OPEN 100 (the t+1 open, ts == decision_ts):
    #     N = 10_000, impact = 0.02*sqrt(1e-4) = 2e-4, slip = 6.5e-4,
    #     p1 = 100 * 1.00065 = 100.065;   fee1 = 5e-4*100*p1 = 5.00325
    p1 = 100.0 * (1.0 + slip(10_000.0))
    fee1 = 5e-4 * 100.0 * p1
    # F2: same decision, SOL: dN = 0.0401*100_000 = 4_010 -> 200.5 -> 200 BUY
    #     at bar-2 open 20: N = 4_000, impact = 0.02*sqrt(4e-5),
    #     p2 = 20*(1+slip) = 20.0115298...  (~20.01);  fee2 = 5e-4*200*p2 ~ 2.00
    p2 = 20.0 * (1.0 + slip(4_000.0))
    fee2 = 5e-4 * 200.0 * p2
    # cash after F1+F2 = 100_000 - (100*p1+fee1) - (200*p2+fee2)
    #                  = 100_000 - 10_011.50325 - 4_004.30712 = 85_984.18963
    cash = CASH0 - (100.0 * p1 + fee1) - (200.0 * p2 + fee2)
    # F3 (ADD): decided at C4 (t = T0+5h). Equity = cash + 100*100 + 200*20
    #     = 85_984.18963 + 14_000 = 99_984.18963.
    #     dN = 0.1507*99_984.18963 - 10_000 = 5_067.62 -> 50.68 -> 50 BUY
    #     at bar-5 open 100: N = 5_000, impact = 0.02*sqrt(5e-5),
    #     p3 = 100.0591421...;  fee3 = 5e-4*50*p3 ~ 2.50
    p3 = 100.0 * (1.0 + slip(5_000.0))
    fee3 = 5e-4 * 50.0 * p3
    cash -= 50.0 * p3 + fee3  # cash = 80_978.73105
    # BTC VWAP avg entry = (100*p1 + 50*p3)/150 = 100.06304737854124
    avg_btc = (100.0 * p1 + 50.0 * p3) / 150.0
    # F4 (PARTIAL CLOSE): decided at C6 (t = T0+7h). Equity = cash + 15_000
    #     + 4_000 = 99_978.73105. Target 0.02*E = 1_999.57; held 4_000;
    #     dN = -2_000.43 -> 100.02 -> 100 SELL at bar-7 open 20:
    #     N = 2_000, p4 = 20*(1 - slip(2_000)) = 19.9892111...;
    #     fee4 = 5e-4*100*p4 ~ 1.00;
    #     realized = 100*(p4 - p2) = -2.2318676510 (~ -2.23, a loss)
    p4 = 20.0 * (1.0 - slip(2_000.0))
    fee4 = 5e-4 * 100.0 * p4
    realized_sol = 100.0 * (p4 - p2)
    cash += 100.0 * p4 - fee4  # cash = 82_976.65270
    # Funding at t = T0+8h settles AFTER the same-close fills (post-fill book):
    #     BTC +1e-4 on 150 long @ mark 100 (close of bar 7): -150*100*1e-4 = -1.50
    #     SOL -2e-4 on 100 long (post-partial-close!) @ 20: -100*20*(-2e-4) = +0.40
    #     ETH events @ 4h/8h: flat -> skipped, NOT logged.
    cash += -1.5 + 0.4  # cash = 82_975.55270
    # F5 (FLIP): decided at C10 close (t = T0+11h) AT the pump close 110 —
    #     fills at bar-11 OPEN 110, never bar 10 (no lookahead).
    #     Equity = cash + 150*110 + 100*20 = 101_475.55270.
    #     Target -0.05*E = -5_073.78; held 16_500; dN = -21_573.78 ->
    #     196.13 -> 196 SELL: N = 21_560, p5 = 110*(1 - slip(21_560))
    #     = 109.9181967 (~109.92); fee5 = 5e-4*196*p5 ~ 10.77.
    #     Closes 150 long: realized = 150*(p5 - avg_btc) = +1_478.2723963
    #     (~ +1_478.27); restarts SHORT 46 @ avg p5.
    p5 = 110.0 * (1.0 - slip(21_560.0))
    fee5 = 5e-4 * 196.0 * p5
    realized_btc = 150.0 * (p5 - avg_btc)
    cash += 196.0 * p5 - fee5  # cash = 104_508.74793
    # GAP-DROP: decided at C14 (t = T0+15h) {SOL: 0.05} -> 153 BUY queued, but
    #     SOL bar 15 (ts_open = T0+15h) is MISSING -> dropped, zero fills.
    # Funding at t = T0+16h: BTC +1e-4 on 46 SHORT @ mark 110 (close of
    #     bar 15): -(-46)*110*1e-4 = +0.506 — shorts RECEIVE positive funding.
    #     ETH @16h: still flat -> skipped.
    cash += 0.506  # cash = 104_509.25393
    # F6 (OPEN ETH): decided at C16 (t = T0+17h).
    #     Equity = cash - 46*110 + 100*20 = 101_449.25393.
    #     dN = 0.04*E = 4_057.97 -> 81.16 -> 81 BUY at bar-17 open 50:
    #     N = 4_050, p6 = 50*(1+slip(4_050)) = 50.0288640 (~50.03);
    #     fee6 = 5e-4*81*p6 ~ 2.03.
    p6 = 50.0 * (1.0 + slip(4_050.0))
    fee6 = 5e-4 * 81.0 * p6
    cash -= 81.0 * p6 + fee6  # cash = 102_452.88914
    # Remaining funding (mark = close of the bar ending at the settle close):
    #     ETH +5e-5 @ +20h on 81 long @ 50:        -81*50*5e-5  = -0.2025
    #     BTC -1e-4 @ +24h on 46 short @ 110:      -(-46)*110*(-1e-4) = -0.506
    #         (shorts PAY negative funding)
    #     ETH +1e-4 @ +24h on 81 long @ 48 (the bar-20 drop re-marked):
    #                                              -81*48*1e-4  = -0.3888
    #     SOL +3e-4 @ +24h on 100 long @ 20:       -100*20*3e-4 = -0.6000
    #     ETH -2e-4 @ +28h on 81 long @ 48:        -81*48*(-2e-4) = +0.7776
    cash += -0.2025 - 0.506 - 0.3888 - 0.6 + 0.7776  # cash = 102_451.96944
    # FINAL-BAR SIGNAL: {BTC: 0.0} decided at the last close T0+30h -> 46 BUY
    #     queued with no t+1 -> unfilled_final_bar, zero fills.

    fills = result.fills
    assert len(fills) == 6
    expected = [
        # (ts,           iid, side,  qty,    price, fee,  realized)
        (T0 + 2 * HOUR, BTC, "buy", 100.0, p1, fee1, 0.0),
        (T0 + 2 * HOUR, SOL, "buy", 200.0, p2, fee2, 0.0),
        (T0 + 5 * HOUR, BTC, "buy", 50.0, p3, fee3, 0.0),
        (T0 + 7 * HOUR, SOL, "sell", 100.0, p4, fee4, realized_sol),
        (T0 + 11 * HOUR, BTC, "sell", 196.0, p5, fee5, realized_btc),
        (T0 + 17 * HOUR, ETH, "buy", 81.0, p6, fee6, 0.0),
    ]
    for row, (ts, iid, side, qty, price, fee, realized) in zip(
        fills.itertuples(index=False), expected, strict=True
    ):
        assert row.ts == ts
        assert row.instrument_id == iid
        assert row.side == side
        assert row.qty == qty
        assert row.price == pytest.approx(price, abs=1e-9)
        assert row.fee == pytest.approx(fee, abs=1e-9)
        assert row.realized_pnl_quote == pytest.approx(realized, abs=1e-9)

    # Cent-level spot checks of the headline figures (rounding at the report
    # boundary only — the assertions above carry full precision):
    assert round(p1, 2) == 100.06 and round(fee1, 2) == 5.00  # p1 = 100.065
    # exactly (float 100.065 sits a hair below the midpoint, so 2dp -> 100.06)
    assert round(p5, 2) == 109.92 and round(fee5, 2) == 10.77
    assert round(realized_btc, 2) == 1478.27
    assert round(realized_sol, 2) == -2.23

    # -------------------------------------------------------------- funding
    funding = result.funding_events
    expected_funding = [
        # (ts_funding,     iid, rate,  mark,  qty,    payment)
        (T0 + 8 * HOUR, BTC, 1e-4, 100.0, 150.0, -1.5),
        (T0 + 8 * HOUR, SOL, -2e-4, 20.0, 100.0, 0.4),
        (T0 + 16 * HOUR, BTC, 1e-4, 110.0, -46.0, 0.506),
        (T0 + 20 * HOUR, ETH, 5e-5, 50.0, 81.0, -0.2025),
        (T0 + 24 * HOUR, BTC, -1e-4, 110.0, -46.0, -0.506),
        (T0 + 24 * HOUR, ETH, 1e-4, 48.0, 81.0, -0.3888),
        (T0 + 24 * HOUR, SOL, 3e-4, 20.0, 100.0, -0.6),
        (T0 + 28 * HOUR, ETH, -2e-4, 48.0, 81.0, 0.7776),
    ]
    assert len(funding) == len(expected_funding)  # 8 of the 12 stored settle
    for row, (ts, iid, rate, mark, qty, payment) in zip(
        funding.itertuples(index=False), expected_funding, strict=True
    ):
        assert row.ts_funding == ts
        assert row.instrument_id == iid
        assert row.rate == rate
        assert row.mark_price == mark
        assert row.position_qty == qty
        assert row.payment_quote == pytest.approx(payment, abs=1e-12)
    # The 4 ETH events stored while flat never settled:
    flat_eth = {T0 + 4 * HOUR, T0 + 8 * HOUR, T0 + 12 * HOUR, T0 + 16 * HOUR}
    settled_eth = set(funding.loc[funding["instrument_id"] == ETH, "ts_funding"])
    assert settled_eth.isdisjoint(flat_eth)

    # ------------------------------------------------------------- counters
    assert result.counters == {
        "bars_processed": 30,
        "orders_decided": 8,
        "fills_applied": 6,
        "skipped_no_trade_band": 0,
        "skipped_below_min": 0,
        # No reducing order is forced past the min filters in this script (every
        # reducer clears min_qty/min_notional) and no order exceeds 1% of the
        # StaticCostInputs ADV, so both new risk-guard counters stay 0 here.
        "flatten_residual_forced": 0,
        "orders_adv_clamped": 0,
        # New observability counter (de-risk ADV clamp, opt-in via risk.clamp_reduce_only_adv;
        # OFF here so reduce-only bypasses the cap exactly as before — every fill/fee/PnL above is
        # byte-identical, this key is inert 0). Not a re-bless of any computed value.
        "orders_reduce_adv_clamped": 0,
        "dropped_no_decision_bar": 0,
        "dropped_missing_next_bar": 1,  # the SOL gap at bar 15
        "dropped_no_cost_inputs": 0,
        "unfilled_final_bar": 1,  # the C29-close BTC flatten
        "forced_flat": 0,  # every instrument has bars to the end
        "funding_events_applied": 8,
        # Optional execution-realism providers are disabled in this crypto golden
        # master. Their zero counters prove the compatibility path remains inert.
        "corporate_actions_applied": 0,
        "cash_dividends_applied": 0,
        "financing_intervals_applied": 0,
        # Crypto perps have no borrow leg (borrow_frac_per_day == 0), so the short-borrow
        # accrual is skipped entirely -> 0 charges. This 0 is the byte-identity proof: the
        # equity-only borrow leg leaves the crypto golden master untouched.
        "borrow_charges_applied": 0,
    }
    orders = result.orders
    assert (orders["status"] == "dropped_missing_next_bar").sum() == 1
    assert (orders["status"] == "unfilled_final_bar").sum() == 1

    # --------------------------------------------------- equity, to the cent
    # Final book: BTC -46 @ mark 110, SOL +100 @ 20, ETH +81 @ 48.
    # equity = cash + (-46*110) + 100*20 + 81*48
    #        = 102_451.96944 - 5_060 + 2_000 + 3_888 = 101_281.96942
    final_equity = cash + (-46.0) * 110.0 + 100.0 * 20.0 + 81.0 * 48.0
    assert round(final_equity, 2) == 101_281.97
    assert float(result.equity.iloc[-1]) == pytest.approx(final_equity, abs=1e-9)
    # Two interior points, same arithmetic:
    #   t = T0+3h (first close after the C1 fills): 85_984.18963 + 14_000
    eq_3h = CASH0 - (100.0 * p1 + fee1) - (200.0 * p2 + fee2) + 14_000.0
    assert float(result.equity.loc[T0 + 3 * HOUR]) == pytest.approx(eq_3h, abs=1e-9)
    #   t = T0+11h (the pump close, pre-flip): 82_975.55270 + 16_500 + 2_000
    eq_11h = eq_3h - (50.0 * p3 + fee3) + (100.0 * p4 - fee4) - 1.1 + 2_500.0 + 2_000.0
    # (= cash@C8 + 150*110 + 100*20; the +2_500 is the 150-BTC mark move
    #  100 -> 110 net of the 14_000 -> 16_500 + 2_000 restatement)
    assert float(result.equity.loc[T0 + 11 * HOUR]) == pytest.approx(eq_11h, abs=1e-9)

    # Equity identity (ledger invariant, asserted end-to-end):
    #   equity == initial + realized + unrealized - fees + funding
    fees_total = fee1 + fee2 + fee3 + fee4 + fee5 + fee6
    funding_total = -1.5 + 0.4 + 0.506 - 0.2025 - 0.506 - 0.3888 - 0.6 + 0.7776
    unreal = (-46.0) * (110.0 - p5) + 100.0 * (20.0 - p2) + 81.0 * (48.0 - p6)
    identity = CASH0 + realized_sol + realized_btc + unreal - fees_total + funding_total
    assert final_equity == pytest.approx(identity, abs=1e-9)


# ---------------------------------------------------------------------------
# Part 2 — LakeCostInputs == features/library/market.py (no formula fork)
# ---------------------------------------------------------------------------


def test_lake_cost_inputs_match_feature_library(tmp_path: Path) -> None:
    """LakeCostInputs ADV/sigma numerically equal the registered features.

    Fixture: 36 UTC days of 1h bars for two instruments with day-varying
    quote volume and deterministic non-constant closes, lake data starting
    exactly at the provider's warmup read start (start - 33d), so both
    computations consume identical data. Every decision timestamp in the
    3-day run window is compared against ``adv_quote_30d`` / ``sigma_daily``
    computed by the FeatureEngine. ADV must match exactly; sigma to 1e-12
    relative (same EWMA recursion over the same window).
    """
    lake_start = T0 - 2 * DAY  # 2023-12-31T00:00Z, UTC midnight
    n_bars = 36 * 24
    rows: list[dict[str, object]] = []
    for k in range(n_bars):
        ts = lake_start + k * HOUR
        day = k // 24
        # closes: deterministic oscillation, distinct per instrument
        c_btc = 100.0 * (1.0 + 0.01 * math.sin(0.7 * k) + 0.0001 * k)
        c_eth = 50.0 * (1.0 + 0.02 * math.cos(0.3 * k))
        rows.append(bar_row(BTC, ts, open_=c_btc, close=c_btc, quote_volume=1_000.0 + 37.0 * day))
        rows.append(
            bar_row(ETH, ts, open_=c_eth, close=c_eth, quote_volume=500.0 + 11.0 * (day % 5))
        )
    paths = LakePaths(tmp_path / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, ohlcv_table(rows))
    reader = PITDataReader(paths)

    run_start = lake_start + 33 * DAY  # provider read_start == lake_start
    run_end = lake_start + 36 * DAY
    provider = LakeCostInputs(reader, [BTC, ETH], start=run_start, end=run_end)

    instruments = InstrumentStore(tmp_path / "ops.sqlite")
    for inst in (make_instrument(BTC, funding_hours=8), make_instrument(ETH, funding_hours=4)):
        instruments.upsert(inst, as_of=1)
    engine = FeatureEngine(reader, instruments, UniverseStore(paths))
    registry = default_registry()
    feats = engine.compute_history(
        [registry.get("adv_quote_30d"), registry.get("sigma_daily")],
        [BTC, ETH],
        start=run_start,
        end=run_end,
    )
    instruments.close()

    adv_col = feats["adv_quote_30d"].astype("float64")
    sigma_col = feats["sigma_daily"].astype("float64")
    n_checked = 0
    for ts_open in range(run_start, run_end, HOUR):
        decision_ts = ts_open + HOUR  # the close of the bar at ts_open
        for iid in (BTC, ETH):
            adv, sigma = provider.cost_inputs(iid, decision_ts)
            f_adv = cast("float", adv_col.at[(ts_open, iid)])
            f_sigma = cast("float", sigma_col.at[(ts_open, iid)])
            assert math.isfinite(adv) and math.isfinite(sigma)
            assert adv == pytest.approx(f_adv, abs=0.0)  # EXACT — same median
            assert sigma == pytest.approx(f_sigma, rel=1e-12)
            n_checked += 1
    assert n_checked == 2 * 72  # every decision in the 3-day window, both ids


# ---------------------------------------------------------------------------
# Part 3 — funding reproduction against the REAL lake (read-only)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_LAKE = REPO_ROOT / "data" / "lake"

WEEK_START = 1_709_251_200_000  # 2024-03-01T00:00:00Z
WEEK_END = 1_709_856_000_000  # 2024-03-08T00:00:00Z


@pytest.mark.skipif(
    not (REAL_LAKE / "funding").is_dir(), reason="real lake not present at data/lake"
)
def test_funding_reproduction_btcusdt_real_week(tmp_path: Path) -> None:
    """Our stored BTCUSDT funding events ARE Binance's, and the engine settles them.

    2024-03-01 .. 2024-03-08 (one week): the events table must hold exactly
    21 settlements (3/day x 7 on the 8h schedule, hours {0, 8, 16} UTC), and
    an engine run holding a BTC long the whole week must apply exactly those
    events with ``payment == -qty * close_proxy * rate`` where close_proxy is
    the close of the 1h bar ending at the first grid close >= ts_funding
    (the engine's documented mark proxy; Binance occasionally stamps
    settlements a few ms past the hour, which this rule absorbs).

    Read-only on the real lake; the InstrumentStore is a tmp_path synthetic
    (real ops state is never touched). The run end is extended one hour past
    the week so the 03-08T00:00 settlement (published minutes later) clears
    the engine's conservative ``as_of = end`` availability cut.
    """
    reader = PITDataReader(LakePaths(REAL_LAKE))

    # --- reality check on the stored table itself -------------------------
    events = reader.funding([BTC], start=WEEK_START + 1, end=WEEK_END + 1, as_of=WEEK_END + DAY)
    assert events.num_rows == 21  # 3/day x 7 — Binance's 8h cadence
    ts_funding = events.column("ts_funding").cast(pa.int64()).to_pylist()
    rates = events.column("rate").to_pylist()
    assert {(t // HOUR) % 24 for t in ts_funding} <= {0, 8, 16}
    assert all(math.isfinite(r) and abs(r) < 0.01 for r in rates)

    # --- independent expected payments from raw bars ----------------------
    bars = reader.ohlcv([BTC], start=WEEK_START, end=WEEK_END + HOUR, as_of=WEEK_END + DAY)
    close_by_open = dict(
        zip(
            bars.column("ts_open").cast(pa.int64()).to_pylist(),
            bars.column("close").to_pylist(),
            strict=True,
        )
    )

    def close_proxy(ts: int) -> float:
        settle_close = ((ts + HOUR - 1) // HOUR) * HOUR  # first grid close >= ts
        return float(close_by_open[settle_close - HOUR])

    # --- engine run: open a long at the first close, hold all week --------
    store = InstrumentStore(tmp_path / "ops.sqlite")
    inst = Instrument(
        instrument_id=BTC,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base="BTC",
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=10.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=LISTED,
        delisted_ts=None,
    )
    store.upsert(inst, as_of=1)
    engine = EventDrivenBacktester(
        PITDataReader(LakePaths(REAL_LAKE)),
        store,
        TransactionCostModel(),
    )
    result = engine.run(
        ScriptedStrategy({WEEK_START + HOUR: {BTC: 0.5}}),
        [BTC],
        start=WEEK_START,
        end=WEEK_END + HOUR,
        initial_cash=CASH0,
    )
    store.close()

    applied = result.funding_events
    qty = float(result.fills.iloc[0]["qty"])
    assert qty > 0.0  # long all week
    assert result.counters["fills_applied"] == 1
    # exactly the stored events settled — same timestamps, same rates
    assert list(applied["ts_funding"]) == ts_funding
    assert list(applied["rate"]) == rates
    assert len(applied) == 21

    total_expected = 0.0
    for row, ts, rate in zip(applied.itertuples(index=False), ts_funding, rates, strict=True):
        mark = close_proxy(ts)
        expected_payment = -qty * mark * rate
        assert row.position_qty == qty
        assert row.mark_price == pytest.approx(mark, abs=0.0)
        assert row.payment_quote == pytest.approx(expected_payment, rel=1e-12)
        total_expected += expected_payment
    # simulated funding == sum(stored rate * close_proxy) * (-qty), exactly
    assert float(applied["payment_quote"].sum()) == pytest.approx(total_expected, rel=1e-12)
    assert isinstance(result.equity, pd.Series)  # the run produced a real curve
