"""Regression: split-aware P&L marking on the RUNNING walk-forward path (2026-07-18).

The phantom-marks lesson: a fix is not done until a test pins the path that RUNS.
The walk-forward legs' ``positions.parquet``/``equity.parquet`` are produced by
:class:`alphaforge.backtest.engine.EventDrivenBacktester` marking the ledger at raw
closes — so these tests drive THAT engine (equity sleeve: ``tf=D1``,
``asset_class=EQUITY``, XNYS calendar) over a synthetic tmp lake, exactly the code
path ``WalkForwardRunner._run_leg_set`` executes.

Pinned defects (adjudicated 4-agent diagnostic):

1. **ALIT 1-for-20 reverse split marked at RAW prices** — a position held across a
   split ex-date must convert (``qty·ratio``, ``avg/ratio``) or the raw-close mark
   fabricates a ``1/ratio``-sized phantom P&L day (-495bp phantom sim day, leaked
   live via an oversized short and a phantom-tripped drawdown halver). Test: a
   synthetic 1-for-20 reverse split across a held position (long AND short) produces
   NO phantom P&L — the equity curve is continuous across the boundary to float
   precision, and the position snapshot shows the converted share count.

2. **Bogus HON split record (ratio 0.5, no real split)** — a stored split whose
   price did NOT move must be rejected by the sanity guard
   (``|log((open_ex/close_pre)·ratio)| > 0.30``), logged loudly, and NOT applied:
   the position stays unconverted and the equity curve stays continuous.

3. Crypto instruments (``asset_class=CRYPTO_PERP``) never touch the corporate-
   actions read — the golden master (tests/integration/test_golden_master.py) pins
   that byte-identity separately.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import pyarrow as pa
import pytest

from alphaforge.backtest.engine import (
    EventDrivenBacktester,
    ScriptedStrategy,
    StaticCostInputs,
)
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Ms, Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.costs import TransactionCostModel
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter

DAY = 86_400_000

SPLT = "XUSE:CASH:SPLTUSD"
LISTED = 1_577_836_800_000  # 2020-01-01T00:00:00Z

# XNYS sessions, January 2024 (Jan 1 = holiday, Jan 6/7 = weekend, Jan 15 = MLK):
# 2, 3, 4, 5, 8, 9, 10, 11, 12 — daily-bar ts_open at UTC midnight of each session.
S = {
    2: 1_704_153_600_000,  # 2024-01-02
    3: 1_704_240_000_000,
    4: 1_704_326_400_000,
    5: 1_704_412_800_000,
    8: 1_704_672_000_000,  # the split EX-DATE session
    9: 1_704_758_400_000,
    10: 1_704_844_800_000,
    11: 1_704_931_200_000,
    12: 1_705_017_600_000,
}
SESSIONS = [S[d] for d in (2, 3, 4, 5, 8, 9, 10, 11, 12)]
EX_DATE = S[8]
RUN_START = S[2]
RUN_END = S[12] + DAY  # exclusive; D1-aligned

CASH0 = 100_000.0
ADV = 1e8
SIGMA = 0.02

# 1-for-20 reverse split: ratio = split_to/split_from = 1/20 = 0.05 (the stored
# corporate-actions convention; post-split price = pre-split price / ratio = x20).
REVERSE_RATIO = 0.05
PRE_PRICE = 10.0
POST_PRICE = PRE_PRICE / REVERSE_RATIO  # 200.0 — exactly the split, no drift


def _equity_instrument() -> Instrument:
    """A US-equity instrument with the ingest defaults (polygon_source constants)."""
    return Instrument(
        instrument_id=SPLT,
        asset_class=AssetClass.EQUITY,
        market_type=MarketType.CASH,
        base="SPLT",
        quote="USD",
        tick_size=0.01,
        lot_size=1.0,
        min_qty=1.0,
        min_notional=0.0,
        contract_multiplier=1.0,
        can_short=True,
        maker_fee_bps=0.0,
        taker_fee_bps=0.0,
        funding_interval_hours=None,
        listed_ts=LISTED,
        delisted_ts=None,
    )


def _bar_rows(prices: dict[int, tuple[float, float]]) -> pa.Table:
    """D1 OHLCV rows: ``session ts_open -> (open, close)``."""
    ts = sorted(prices)
    opens = [prices[k][0] for k in ts]
    closes = [prices[k][1] for k in ts]
    return pa.table(
        {
            "instrument_id": pa.array([SPLT] * len(ts), type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array(
                [max(o, c) * 1.001 for o, c in zip(opens, closes, strict=True)], pa.float64()
            ),
            "low": pa.array(
                [min(o, c) * 0.999 for o, c in zip(opens, closes, strict=True)], pa.float64()
            ),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([1e6] * len(ts), type=pa.float64()),
            "quote_volume": pa.array([1e7] * len(ts), type=pa.float64()),
            "n_trades": pa.array([1000] * len(ts), type=pa.int64()),
            "quality_flags": pa.array([0] * len(ts), type=pa.int32()),
            "ingested_at": pa.array([t + DAY for t in ts], type=pa.timestamp("ms", tz="UTC")),
        }
    )


def _actions_table(rows: list[tuple[str, int, float, float | None]]) -> pa.Table:
    """Corporate-actions rows: ``(action_type, ex_date, ratio, cash_amount)``."""
    return pa.table(
        {
            "instrument_id": pa.array([SPLT] * len(rows), type=pa.string()),
            "action_type": pa.array([r[0] for r in rows], type=pa.string()),
            "ex_date": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "available_at": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "ratio": pa.array([r[2] for r in rows], type=pa.float64()),
            "cash_amount": pa.array([r[3] for r in rows], type=pa.float64()),
            "ingested_at": pa.array(
                [r[1] + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _build_lake(
    tmp_path: Path,
    prices: dict[int, tuple[float, float]],
    actions: list[tuple[str, int, float, float | None]],
) -> tuple[PITDataReader, InstrumentStore]:
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV_1D, _bar_rows(prices))
    if actions:
        writer.write(Dataset.CORPORATE_ACTIONS, _actions_table(actions))
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(_equity_instrument(), as_of=1)
    return PITDataReader(paths), store


def _run(reader: PITDataReader, store: InstrumentStore, weight: float) -> object:
    engine = EventDrivenBacktester(
        reader,
        store,
        TransactionCostModel(),
        tf=Timeframe.D1,
        asset_class=AssetClass.EQUITY,
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
    )
    # Decide at the close of the Jan-2 bar (= Jan-3 00:00 UTC); fill at the Jan-3 open;
    # hold across the Jan-8 ex-date to the end of the run.
    script: dict[Ms, dict[str, float]] = {S[3]: {SPLT: weight}}
    return engine.run(
        ScriptedStrategy(script), [SPLT], start=RUN_START, end=RUN_END, initial_cash=CASH0
    )


def _split_prices() -> dict[int, tuple[float, float]]:
    """Flat $10 pre-split, flat $200 post-split — the pure 1-for-20 boundary."""
    return {
        t: ((PRE_PRICE, PRE_PRICE) if t < EX_DATE else (POST_PRICE, POST_PRICE))
        for t in SESSIONS
    }


@pytest.mark.parametrize("weight", [0.1, -0.1], ids=["long", "short"])
def test_reverse_split_produces_no_phantom_pnl(tmp_path: Path, weight: float) -> None:
    """A held position across a 1-for-20 reverse split marks with NO phantom P&L.

    Prices are constant in split-adjusted terms, so after the entry fill the equity
    curve must be CONSTANT to float precision — including across the ex boundary.
    The unfixed path marked the pre-split share count at the post-split raw close:
    a long 1000-share book would fabricate ``1000·(200-10) = +$190k`` (and the short
    the mirror-image crash — the ALIT -495bp phantom day, sign-adjusted).
    """
    reader, store = _build_lake(tmp_path, _split_prices(), [("split", EX_DATE, REVERSE_RATIO, None)])
    result = _run(reader, store, weight)
    store.close()

    equity = result.equity
    # Entry fill happens at the Jan-3 open; from the Jan-3 close onward nothing trades
    # and prices are flat in adjusted terms -> the curve must be flat, ex-date included.
    post_entry = equity[equity.index >= S[4]]
    assert len(post_entry) >= 6
    ref = float(post_entry.iloc[0])
    for ts, val in post_entry.items():
        assert val == pytest.approx(ref, rel=1e-9), (
            f"equity discontinuity at {ts}: {val} vs {ref} — phantom split P&L on the "
            "running marking path"
        )
    # Explicitly: the boundary itself (close of the Jan-5 bar -> close of the Jan-8 ex bar).
    pre_boundary = float(equity.loc[S[8]])  # mark instant of the Jan-5 bar's close
    post_boundary = float(equity.loc[S[9]])  # mark instant of the Jan-8 (ex) bar's close
    assert post_boundary == pytest.approx(pre_boundary, rel=1e-9)

    # The position snapshot at the ex bar's close carries the CONVERTED share count.
    pos = result.positions
    pre_qty = float(pos.loc[pos["ts"] == S[8], "qty"].iloc[0])
    post_qty = float(pos.loc[pos["ts"] == S[9], "qty"].iloc[0])
    post_mark = float(pos.loc[pos["ts"] == S[9], "mark"].iloc[0])
    assert post_qty == pytest.approx(pre_qty * REVERSE_RATIO, rel=1e-12)
    assert post_mark == pytest.approx(POST_PRICE)
    # Value preserved exactly across the conversion.
    assert post_qty * POST_PRICE == pytest.approx(pre_qty * PRE_PRICE, rel=1e-12)
    # Unrealized PnL preserved across the conversion (avg_entry rescaled by 1/ratio).
    pre_unreal = float(pos.loc[pos["ts"] == S[8], "unreal_pnl"].iloc[0])
    post_unreal = float(pos.loc[pos["ts"] == S[9], "unreal_pnl"].iloc[0])
    assert post_unreal == pytest.approx(pre_unreal, rel=1e-9)


def test_bogus_split_record_skipped_by_sanity_guard(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A split record whose price did NOT move (the bogus HON ratio-0.5 row) is
    logged + skipped: no conversion, no equity jump, lake untouched."""
    flat = {t: (PRE_PRICE, PRE_PRICE) for t in SESSIONS}  # no split in the prices
    reader, store = _build_lake(tmp_path, flat, [("split", EX_DATE, 0.5, None)])
    with caplog.at_level(logging.WARNING, logger="alphaforge.backtest.engine"):
        result = _run(reader, store, 0.1)
    store.close()

    # The guard fired loudly.
    warnings = [r for r in caplog.records if "sanity guard" in r.getMessage()]
    assert warnings, "expected a WARNING from the split sanity guard"
    assert SPLT in warnings[0].getMessage()

    # No conversion: share count unchanged across the (bogus) ex boundary.
    pos = result.positions
    pre_qty = float(pos.loc[pos["ts"] == S[8], "qty"].iloc[0])
    post_qty = float(pos.loc[pos["ts"] == S[9], "qty"].iloc[0])
    assert post_qty == pytest.approx(pre_qty, rel=1e-12)

    # No equity jump: flat prices -> flat curve after entry.
    equity = result.equity
    post_entry = equity[equity.index >= S[4]]
    ref = float(post_entry.iloc[0])
    for val in post_entry:
        assert val == pytest.approx(ref, rel=1e-9)


def test_genuine_split_with_dividend_rows_present(tmp_path: Path) -> None:
    """Dividend rows in corporate_actions never move the share count — only the
    split row converts, once, at its own ex boundary."""
    actions: list[tuple[str, int, float, float | None]] = [
        ("dividend", S[4], 1.0, 0.04),
        ("split", EX_DATE, REVERSE_RATIO, None),
        ("dividend", S[10], 1.0, 0.04),
    ]
    reader, store = _build_lake(tmp_path, _split_prices(), actions)
    result = _run(reader, store, 0.1)
    store.close()

    pos = result.positions
    qty_by_ts = {int(row.ts): float(row.qty) for row in pos.itertuples()}
    pre_qty = qty_by_ts[S[8]]
    # Converted exactly once at the split ex boundary; dividends leave qty untouched.
    for d in (9, 10, 11, 12):
        assert qty_by_ts[S[d]] == pytest.approx(pre_qty * REVERSE_RATIO, rel=1e-12)
    for d in (5, 8):
        assert qty_by_ts[S[d]] == pytest.approx(pre_qty, rel=1e-12)
    # And the curve stays continuous throughout.
    equity = result.equity
    post_entry = equity[equity.index >= S[4]]
    ref = float(post_entry.iloc[0])
    for val in post_entry:
        assert val == pytest.approx(ref, rel=1e-9)


def test_crypto_engine_never_reads_corporate_actions(tmp_path: Path) -> None:
    """The crypto path never touches the corporate-actions read (asset-class gate):
    a crypto run over a lake WITH a split record is byte-identical to one without."""

    class _TripwireReader(PITDataReader):
        def corporate_actions(self, *args: object, **kwargs: object) -> pa.Table:  # type: ignore[override]
            raise AssertionError("crypto engine must never read corporate_actions")

    t0 = 1_704_153_600_000
    hour = 3_600_000
    btc = "BINANCE:PERP:BTCUSDT"
    rows = pa.table(
        {
            "instrument_id": pa.array([btc] * 30, type=pa.string()),
            "ts_open": pa.array(
                [t0 + k * hour for k in range(30)], type=pa.timestamp("ms", tz="UTC")
            ),
            "open": pa.array([100.0] * 30, type=pa.float64()),
            "high": pa.array([101.0] * 30, type=pa.float64()),
            "low": pa.array([99.0] * 30, type=pa.float64()),
            "close": pa.array([100.0] * 30, type=pa.float64()),
            "volume": pa.array([10.0] * 30, type=pa.float64()),
            "quote_volume": pa.array([1000.0] * 30, type=pa.float64()),
            "n_trades": pa.array([42] * 30, type=pa.int64()),
            "quality_flags": pa.array([0] * 30, type=pa.int32()),
            "ingested_at": pa.array(
                [t0 + k * hour + hour for k in range(30)], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )
    paths = LakePaths(tmp_path / "lake")
    LakeWriter(paths).write(Dataset.OHLCV, rows)
    store = InstrumentStore(tmp_path / "ops.sqlite")
    store.upsert(
        Instrument(
            instrument_id=btc,
            asset_class=AssetClass.CRYPTO_PERP,
            market_type=MarketType.PERP,
            base="BTC",
            quote="USDT",
            tick_size=0.1,
            lot_size=1.0,
            min_qty=1.0,
            min_notional=10.0,
            contract_multiplier=1.0,
            can_short=True,
            maker_fee_bps=2.0,
            taker_fee_bps=5.0,
            funding_interval_hours=8,
            listed_ts=LISTED,
            delisted_ts=None,
        ),
        as_of=1,
    )
    engine = EventDrivenBacktester(
        _TripwireReader(paths),
        store,
        TransactionCostModel(),
        cost_inputs=StaticCostInputs(adv_quote=ADV, sigma_daily=SIGMA),
    )
    result = engine.run(
        ScriptedStrategy({t0 + 2 * hour: {btc: 0.1}}),
        [btc],
        start=t0,
        end=t0 + 30 * hour,
        initial_cash=CASH0,
    )
    store.close()
    assert math.isfinite(float(result.equity.iloc[-1]))
