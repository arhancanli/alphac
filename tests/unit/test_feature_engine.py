"""Unit tests for alphaforge.features.context and alphaforge.features.engine.

All tests run against a synthetic tmp_path lake built through LakeWriter (offline,
deterministic). Covers: compute_history shape/values/warmup-NaN/gap handling,
compute_asof minimal-window rows and history agreement, context bar/panel serving,
quality-flag masking at the window end, funding ``available_at`` gating and the
``funding_asof_join`` PIT guarantee (rate published at settlement + 5 min is invisible
to the decision taken at settlement), universe/instrument access, input validation,
and the engine's fn-output contract enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset, QualityFlag
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import FeatureContext, long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family, FeatureSpec

if TYPE_CHECKING:
    from collections.abc import Iterator

BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"
XRP = "BINANCE:PERP:XRPUSDT"  # never written to the lake

H1 = Timeframe.H1
HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h-aligned)
N_BARS = 48
GAP_K = 30  # BTC bar index deliberately missing from the lake
FLAGGED_K = 40  # BTC bar carrying OUTLIER_RETURN | BAD_PRINT_SUSPECT

FUNDING_8H = 8 * HOUR


def btc_close(k: int) -> float:
    return 100.0 + float(k)


def eth_close(k: int) -> float:
    return 50.0 + 0.5 * float(k)


# --------------------------------------------------------------------------- builders


def _bar_row(instrument_id: str, k: int, close: float, flags: int = 0) -> dict[str, object]:
    ts_open = T0 + k * HOUR
    return {
        "instrument_id": instrument_id,
        "ts_open": ts_open,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 10.0 + k,
        "quote_volume": 1_000.0 + k,
        "n_trades": 42,
        "quality_flags": flags,
        "ingested_at": ts_open + HOUR + 30_000,
    }


def _ohlcv_table(rows: list[dict[str, object]]) -> pa.Table:
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


def _funding_table(rows: list[tuple[str, int, float]]) -> pa.Table:
    """rows: (instrument_id, ts_funding, rate); available_at = ts_funding + 5 min."""
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array(
                [r[1] + MIN5 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
            "ingested_at": pa.array(
                [r[1] + MIN5 + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _universe_table(rows: list[tuple[str, int, int | None]]) -> pa.Table:
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "effective_from": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "effective_to": pa.array([r[2] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1 for _ in rows], type=pa.int32()),
            "reason": pa.array(["enter_top40" for _ in rows], type=pa.string()),
        }
    )


def _instrument(instrument_id: str, base: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=base,
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=8,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


@dataclass(frozen=True)
class Env:
    paths: LakePaths
    reader: PITDataReader
    instruments: InstrumentStore
    universe: UniverseStore
    engine: FeatureEngine


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    paths = LakePaths(tmp_path / "lake")
    writer = LakeWriter(paths)

    bars: list[dict[str, object]] = []
    for k in range(N_BARS):
        if k != GAP_K:
            flags = (
                int(QualityFlag.OUTLIER_RETURN | QualityFlag.BAD_PRINT_SUSPECT)
                if k == FLAGGED_K
                else 0
            )
            bars.append(_bar_row(BTC, k, btc_close(k), flags))
        bars.append(_bar_row(ETH, k, eth_close(k)))
    writer.write(Dataset.OHLCV, _ohlcv_table(bars))

    funding_rows: list[tuple[str, int, float]] = []
    for j in range(6):  # settlements at T0, T0+8h, ..., T0+40h
        funding_rows.append((BTC, T0 + j * FUNDING_8H, 0.0001 * (j + 1)))
        if j >= 2:  # ETH funding history starts only at T0+16h
            funding_rows.append((ETH, T0 + j * FUNDING_8H, -0.0001 * (j + 1)))
    writer.write(Dataset.FUNDING, _funding_table(funding_rows))

    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table([(BTC, T0, None), (ETH, T0 + 24 * HOUR, None)]))

    instruments = InstrumentStore(tmp_path / "instruments.db")
    instruments.upsert(_instrument(BTC, "BTC"), as_of=T0 - 30 * 24 * HOUR)
    instruments.upsert(_instrument(ETH, "ETH"), as_of=T0 - 30 * 24 * HOUR)

    reader = PITDataReader(paths)
    yield Env(
        paths=paths,
        reader=reader,
        instruments=instruments,
        universe=universe,
        engine=FeatureEngine(reader, instruments, universe),
    )
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get("ret_log_1"), registry.get("close_px")]


def _context(
    env: Env, *, start: int, end: int, ids: tuple[str, ...] = (BTC, ETH)
) -> FeatureContext:
    return FeatureContext(
        reader=env.reader,
        instruments=env.instruments,
        universe=env.universe,
        instrument_ids=ids,
        start=start,
        end=end,
    )


# --------------------------------------------------------------------- compute_history


class TestComputeHistory:
    def test_shape_index_and_columns(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        assert isinstance(out.index, pd.MultiIndex)
        assert out.index.names == ["ts_open", "instrument_id"]
        # Complete grid x instruments: the BTC gap bar still has its (NaN) row.
        assert len(out) == N_BARS * 2
        assert list(out.columns) == ["ret_log_1", "close_px"]
        assert all(dtype == np.float64 for dtype in out.dtypes)

    def test_close_px_values_and_gap_nan(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        px = out["close_px"]
        assert px.loc[(T0 + 5 * HOUR, BTC)] == btc_close(5)
        assert px.loc[(T0 + 5 * HOUR, ETH)] == eth_close(5)
        assert np.isnan(px.loc[(T0 + GAP_K * HOUR, BTC)])  # missing bar => NaN row
        assert px.loc[(T0 + GAP_K * HOUR, ETH)] == eth_close(GAP_K)

    def test_ret_log_1_values(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        ret = out["ret_log_1"]
        expected = float(np.log(btc_close(7) / btc_close(6)))
        assert ret.loc[(T0 + 7 * HOUR, BTC)] == expected

    def test_warmup_nan_at_history_origin(self, env: Env) -> None:
        # The lake starts at T0: headroom is empty, so the first return is NaN.
        out = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        assert np.isnan(out["ret_log_1"].loc[(T0, BTC)])
        assert np.isnan(out["ret_log_1"].loc[(T0, ETH)])

    def test_headroom_warms_up_first_output_bar(self, env: Env) -> None:
        # Starting one bar in, the engine's lookback headroom supplies bar T0,
        # so the value at the requested start is already real.
        out = env.engine.compute_history(_specs(), [BTC], start=T0 + HOUR, end=T0 + 2 * HOUR)
        expected = float(np.log(btc_close(1) / btc_close(0)))
        assert out["ret_log_1"].loc[(T0 + HOUR, BTC)] == expected

    def test_gap_makes_return_nan_on_both_sides(self, env: Env) -> None:
        # No return is silently computed ACROSS a missing bar (grid semantics).
        out = env.engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)
        ret = out["ret_log_1"]
        assert np.isnan(ret.loc[(T0 + GAP_K * HOUR, BTC)])
        assert np.isnan(ret.loc[(T0 + (GAP_K + 1) * HOUR, BTC)])
        expected = float(np.log(btc_close(GAP_K + 2) / btc_close(GAP_K + 1)))
        assert ret.loc[(T0 + (GAP_K + 2) * HOUR, BTC)] == expected

    def test_instrument_without_data_is_all_nan(self, env: Env) -> None:
        out = env.engine.compute_history(_specs(), [BTC, XRP], start=T0, end=T0 + 4 * HOUR)
        xrp = out.xs(XRP, level="instrument_id")
        assert len(xrp) == 4
        assert xrp.isna().all().all()

    def test_validation_errors(self, env: Env) -> None:
        specs = _specs()
        with pytest.raises(ValueError, match="end > start"):
            env.engine.compute_history(specs, [BTC], start=T0, end=T0)
        with pytest.raises(ValueError, match="FeatureSpec"):
            env.engine.compute_history([], [BTC], start=T0, end=T0 + HOUR)
        with pytest.raises(ValueError, match="instrument_id"):
            env.engine.compute_history(specs, [], start=T0, end=T0 + HOUR)
        with pytest.raises(ValueError, match="duplicate"):
            env.engine.compute_history([specs[0], specs[0]], [BTC], start=T0, end=T0 + HOUR)


# ----------------------------------------------------------------------- compute_asof


class TestComputeAsof:
    def test_decision_bar_and_agreement_with_history(self, env: Env) -> None:
        as_of = T0 + 10 * HOUR + 30 * 60_000  # mid-bar: last available bar opened T0+9h
        out = env.engine.compute_asof(_specs(), [BTC, ETH], as_of=as_of)
        t_star = T0 + 9 * HOUR
        assert list(out.index) == [(t_star, BTC), (t_star, ETH)]
        hist = env.engine.compute_history(_specs(), [BTC, ETH], start=T0, end=T0 + N_BARS * HOUR)
        pd.testing.assert_frame_equal(out, hist.loc[out.index], check_exact=True)

    def test_as_of_exactly_at_bar_close_uses_that_bar(self, env: Env) -> None:
        out = env.engine.compute_asof(_specs(), [BTC], as_of=T0 + 10 * HOUR)
        assert list(out.index) == [(T0 + 9 * HOUR, BTC)]
        assert out["close_px"].iloc[0] == btc_close(9)

    def test_warmup_nan_in_minimal_window(self, env: Env) -> None:
        # First bar of history: close_px exists, the 1-bar return cannot.
        out = env.engine.compute_asof(_specs(), [BTC], as_of=T0 + HOUR)
        assert out["close_px"].iloc[0] == btc_close(0)
        assert np.isnan(out["ret_log_1"].iloc[0])

    def test_instrument_without_data_gets_nan_row(self, env: Env) -> None:
        out = env.engine.compute_asof(_specs(), [BTC, XRP], as_of=T0 + 10 * HOUR)
        assert np.isnan(out.loc[(T0 + 9 * HOUR, XRP)]).all()
        assert not np.isnan(out.loc[(T0 + 9 * HOUR, BTC)]).any()


# ------------------------------------------------------- fail-closed EQUITY/D1 guard


class TestEquityD1Guard:
    """The fail-closed guard (engine.py:_guard_equity_unverified, SPINE_ARC §4).

    Until the equity as-of window + forward_returns/blend session hops are verified,
    ``FeatureEngine`` MUST reject EQUITY/D1 specs loudly rather than silently compute
    on the partially-migrated path. This is the single most important safety line in
    the spine arc; without these tests a future edit could delete the guard (or flip
    the ``is``/``or`` logic) and the suite would stay green while equity compute ran
    on a broken path. Both trigger branches (``asset_class is EQUITY`` and
    ``anchor_tf is D1``) are exercised on BOTH compute paths, and the crypto default
    is asserted to NOT trip the guard (byte-identity invariant).
    """

    def _engine(
        self, env: Env, *, anchor_tf: Timeframe, asset_class: AssetClass
    ) -> FeatureEngine:
        return FeatureEngine(
            env.reader,
            env.instruments,
            env.universe,
            anchor_tf=anchor_tf,
            asset_class=asset_class,
        )

    def test_equity_asset_class_rejected_on_compute_history(self, env: Env) -> None:
        engine = self._engine(env, anchor_tf=H1, asset_class=AssetClass.EQUITY)
        with pytest.raises(NotImplementedError, match="EQUITY/D1"):
            engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)

    def test_equity_asset_class_rejected_on_compute_asof(self, env: Env) -> None:
        engine = self._engine(env, anchor_tf=H1, asset_class=AssetClass.EQUITY)
        with pytest.raises(NotImplementedError, match="EQUITY/D1"):
            engine.compute_asof(_specs(), [BTC], as_of=T0 + 10 * HOUR)

    def test_d1_anchor_rejected_on_compute_history(self, env: Env) -> None:
        # The other trigger branch: a D1 anchor even with a crypto asset class.
        engine = self._engine(env, anchor_tf=Timeframe.D1, asset_class=AssetClass.CRYPTO_PERP)
        with pytest.raises(NotImplementedError, match="EQUITY/D1"):
            engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)

    def test_d1_anchor_rejected_on_compute_asof(self, env: Env) -> None:
        engine = self._engine(env, anchor_tf=Timeframe.D1, asset_class=AssetClass.CRYPTO_PERP)
        with pytest.raises(NotImplementedError, match="EQUITY/D1"):
            engine.compute_asof(_specs(), [BTC], as_of=T0 + 10 * HOUR)

    def test_crypto_default_does_not_trip_guard(self, env: Env) -> None:
        # The byte-identity invariant: CRYPTO_PERP / H1 (the default engine) computes
        # normally — the guard must NOT fire on the unchanged crypto path.
        out = env.engine.compute_history(_specs(), [BTC], start=T0, end=T0 + N_BARS * HOUR)
        assert len(out) == N_BARS
        asof = env.engine.compute_asof(_specs(), [BTC], as_of=T0 + 10 * HOUR)
        assert list(asof.index) == [(T0 + 9 * HOUR, BTC)]


# -------------------------------------------------------------- engine fn validation


def _make_spec(name: str, fn: object, lookback: int = 2) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        family=Family.MARKET,
        direction=0,
        cross_sectional=False,
        lookback_bars=lookback,
        params={},
        fn=fn,  # type: ignore[arg-type]
    )


class TestFnOutputContract:
    def test_non_series_output_rejected(self, env: Env) -> None:
        spec = _make_spec("bad_frame", lambda ctx, s: ctx.panel("close"))
        with pytest.raises(TypeError, match="Series"):
            env.engine.compute_history([spec], [BTC], start=T0, end=T0 + 4 * HOUR)

    def test_flat_index_rejected(self, env: Env) -> None:
        spec = _make_spec("bad_flat", lambda ctx, s: pd.Series([1.0], index=[T0], dtype="float64"))
        with pytest.raises(ValueError, match="2-level"):
            env.engine.compute_history([spec], [BTC], start=T0, end=T0 + 4 * HOUR)

    def test_duplicate_index_rejected(self, env: Env) -> None:
        dup_index = pd.MultiIndex.from_tuples(
            [(T0, BTC), (T0, BTC)], names=("ts_open", "instrument_id")
        )
        spec = _make_spec(
            "bad_dup",
            lambda ctx, s: pd.Series([1.0, 2.0], index=dup_index, dtype="float64"),
        )
        with pytest.raises(ValueError, match="duplicate"):
            env.engine.compute_history([spec], [BTC], start=T0, end=T0 + 4 * HOUR)


# --------------------------------------------------------------------- FeatureContext


class TestContextBarsAndPanel:
    def test_bars_columns_and_dtypes(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + 8 * HOUR)
        bars = ctx.bars()
        assert list(bars.columns) == [
            "instrument_id",
            "ts_open",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "quality_flags",
        ]
        assert bars["ts_open"].dtype == np.int64
        assert "ingested_at" not in bars.columns  # audit column withheld from features

    def test_bars_pit_at_window_end(self, env: Env) -> None:
        # Window end is the availability cutoff: the bar opening at end - 1h closes
        # exactly at end (visible); nothing at or after end is served.
        ctx = _context(env, start=T0, end=T0 + 8 * HOUR)
        bars = ctx.bars()
        assert bars["ts_open"].max() == T0 + 7 * HOUR

    def test_mutating_served_frame_does_not_corrupt_cache(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + 8 * HOUR)
        first = ctx.bars()
        first.loc[:, "close"] = -1.0
        again = ctx.bars()
        assert (again["close"] > 0).all()

    def test_panel_complete_grid_with_gap_nan(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + N_BARS * HOUR)
        panel = ctx.panel("close")
        assert list(panel.columns) == [BTC, ETH]
        assert len(panel) == N_BARS  # complete grid, including the BTC gap slot
        assert np.isnan(panel.loc[T0 + GAP_K * HOUR, BTC])
        assert panel.loc[T0 + GAP_K * HOUR, ETH] == eth_close(GAP_K)

    def test_panel_unknown_column_rejected(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + 4 * HOUR)
        with pytest.raises(ValueError, match="panel column"):
            ctx.panel("ingested_at")

    def test_flags_masked_at_window_end(self, env: Env) -> None:
        # BAD_PRINT_SUSPECT (lag 2) on the bar opening at T0+40h is visible only from
        # T0+43h; OUTLIER_RETURN (lag 0) from its close T0+41h (leakage finding 5).
        flagged_ts = T0 + FLAGGED_K * HOUR

        ctx_early = _context(env, start=T0, end=flagged_ts + 2 * HOUR)
        flags_early = ctx_early.bars().set_index(["ts_open", "instrument_id"])["quality_flags"]
        assert flags_early.loc[(flagged_ts, BTC)] == int(QualityFlag.OUTLIER_RETURN)

        ctx_late = _context(env, start=T0, end=flagged_ts + 3 * HOUR)
        flags_late = ctx_late.bars().set_index(["ts_open", "instrument_id"])["quality_flags"]
        assert flags_late.loc[(flagged_ts, BTC)] == int(
            QualityFlag.OUTLIER_RETURN | QualityFlag.BAD_PRINT_SUSPECT
        )

    def test_context_validation(self, env: Env) -> None:
        with pytest.raises(ValueError, match="end > start"):
            _context(env, start=T0, end=T0)
        with pytest.raises(ValueError, match="instrument_id"):
            _context(env, start=T0, end=T0 + HOUR, ids=())


class TestContextFunding:
    def test_funding_prefiltered_by_available_at(self, env: Env) -> None:
        settlement = T0 + FUNDING_8H
        # End 2 minutes after settlement: the rate publishes at +5 min => invisible.
        ctx = _context(env, start=T0 - HOUR, end=settlement + 2 * 60_000)
        assert ctx.funding()["ts_funding"].max() == T0  # only the first settlement
        # End exactly at publication: visible (available_at <= end).
        ctx2 = _context(env, start=T0 - HOUR, end=settlement + MIN5)
        assert ctx2.funding()["ts_funding"].max() == settlement

    def test_funding_asof_join_respects_available_at(self, env: Env) -> None:
        settlement = T0 + FUNDING_8H  # rate 0.0002, published settlement + 5 min
        ctx = _context(env, start=T0 - HOUR, end=T0 + 12 * HOUR)
        index = pd.MultiIndex.from_tuples(
            [
                (settlement - HOUR, BTC),  # decision AT settlement: not yet published
                (settlement, BTC),  # decision settlement + 1h: published
            ],
            names=("ts_open", "instrument_id"),
        )
        joined = ctx.funding_asof_join(index)
        assert joined.loc[(settlement - HOUR, BTC)] == 0.0001  # previous settlement
        assert joined.loc[(settlement, BTC)] == 0.0002

    def test_funding_asof_join_nan_before_first_publication(self, env: Env) -> None:
        # ETH funding history starts at T0+16h: earlier decisions know nothing.
        ctx = _context(env, start=T0, end=T0 + 24 * HOUR)
        index = pd.MultiIndex.from_tuples(
            [(T0 + 4 * HOUR, ETH), (T0 + 16 * HOUR, ETH)],
            names=("ts_open", "instrument_id"),
        )
        joined = ctx.funding_asof_join(index)
        assert np.isnan(joined.loc[(T0 + 4 * HOUR, ETH)])
        assert joined.loc[(T0 + 16 * HOUR, ETH)] == -0.0001 * 3

    def test_funding_asof_join_requires_multiindex(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + 4 * HOUR)
        with pytest.raises(ValueError, match="2-level"):
            ctx.funding_asof_join(pd.MultiIndex.from_arrays([[T0]], names=("ts_open",)))


class TestContextReferenceData:
    def test_universe_asof_is_pit(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + N_BARS * HOUR)
        assert ctx.universe_asof(T0 + HOUR) == frozenset({BTC})
        assert ctx.universe_asof(T0 + 25 * HOUR) == frozenset({BTC, ETH})

    def test_universe_asof_beyond_cutoff_raises(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + 4 * HOUR)
        with pytest.raises(LookaheadError):
            ctx.universe_asof(T0 + 4 * HOUR + 1)

    def test_instrument_scd2_lookup(self, env: Env) -> None:
        ctx = _context(env, start=T0, end=T0 + 4 * HOUR)
        inst = ctx.instrument(BTC)
        assert inst.funding_interval_hours == 8
        with pytest.raises(KeyError, match="XRPUSDT"):
            ctx.instrument(XRP)


class TestLongSeries:
    def test_round_trip_values_and_order(self) -> None:
        wide = pd.DataFrame(
            [[1.0, 2.0], [3.0, np.nan]],
            index=pd.Index([T0, T0 + HOUR], name="ts_open"),
            columns=pd.Index([BTC, ETH], name="instrument_id"),
        )
        out = long_series(wide, name="x")
        assert out.name == "x"
        assert out.dtype == np.float64
        assert list(out.index) == [(T0, BTC), (T0, ETH), (T0 + HOUR, BTC), (T0 + HOUR, ETH)]
        assert out.loc[(T0, ETH)] == 2.0
        assert np.isnan(out.loc[(T0 + HOUR, ETH)])


class TestInstrumentEarliestFallback:
    """Historical replay windows predating seed-time SCD2 versions fall back to the
    earliest known version (documented bounded anachronism: the store records when
    WE learned facts, not when they became true on the venue)."""

    def test_window_before_all_versions_falls_back_to_earliest(self, env: Env) -> None:
        # end=1ms predates the seed as_of (T0 - 30d) by decades
        ctx = _context(env, start=0, end=1)
        inst = ctx.instrument(BTC)
        assert inst.instrument_id == BTC
        assert inst.funding_interval_hours == 8

    def test_unknown_instrument_still_raises(self, env: Env) -> None:
        ctx = _context(env, start=0, end=1)
        with pytest.raises(KeyError, match="unknown to the SCD2 store"):
            ctx.instrument("BINANCE:PERP:NOSUCHUSDT")
