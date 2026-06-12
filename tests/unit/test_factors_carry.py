"""Unit tests for alphaforge.features.library.carry (alphaDesign.md §2.5).

Covers: the explicit sign convention on a hand-exact fixture (constant +0.01% per
8h funding => CARRY = -0.0001 * 3 * 365 exactly), interval-aware annualization
(a 4h-interval instrument annualizes with 8760/4, never a hard-coded 3*365 —
leakage finding 6), spot instruments => NaN, point-in-time gating on the stored
``available_at`` (a rate published after the decision instant is invisible: both
the standard 5-minute publication lag and a pathological 2h-late publication —
leakage findings 6/18), the ``min_periods = K`` warmup boundary, registered-spec
metadata (direction +1, cross-sectional, lookbacks derived from params), and
truncation invariance via ``verify_truncation`` for BOTH registered carry specs
(finite-window contract: max_abs_diff == 0.0).

All lake-backed tests run against a deterministic synthetic tmp lake (offline).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pytest

from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.carry import (
    HOURS_PER_YEAR,
    MAX_FUNDING_INTERVAL_HOURS,
)
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = "BINANCE:PERP:BTCUSDT"  # 8h interval, constant +0.0001 funding
ETH = "BINANCE:PERP:ETHUSDT"  # 4h interval, constant -0.0002 funding
DOGE = "BINANCE:PERP:DOGEUSDT"  # 8h interval, 0.0002 with two planted shock rates
XRP = "BINANCE:SPOT:XRPUSDT"  # spot: no funding leg => NaN carry

HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h- and 8h-aligned)
N_BARS = 800

SHOCK_RATE = 0.0086
SHOCK_LATE_J = 50  # settlement T0 + 400h, published 2h late
SHOCK_5MIN_J = 75  # settlement T0 + 600h, standard 5-min publication

CARRY_SPEC_NAMES = ("carry_fund_21", "carry_fund_90")


# --------------------------------------------------------------------------- builders


def _ohlcv_table(instrument_ids: list[str], n: int) -> pa.Table:
    """Flat deterministic bars; carry only needs the grid, not price dynamics."""
    iids: list[str] = []
    ts: list[int] = []
    for iid in instrument_ids:
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
    n_rows = len(iids)
    px = [100.0] * n_rows
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(px, type=pa.float64()),
            "high": pa.array([101.0] * n_rows, type=pa.float64()),
            "low": pa.array([99.0] * n_rows, type=pa.float64()),
            "close": pa.array(px, type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1000.0] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _funding_table(rows: list[tuple[str, int, float, int]]) -> pa.Table:
    """rows: (instrument_id, ts_funding, rate, available_at) — explicit publication."""
    return pa.table(
        {
            "instrument_id": pa.array([r[0] for r in rows], type=pa.string()),
            "ts_funding": pa.array([r[1] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "rate": pa.array([r[2] for r in rows], type=pa.float64()),
            "available_at": pa.array([r[3] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "ingested_at": pa.array(
                [r[3] + 1_000 for r in rows], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _instrument(
    instrument_id: str, base: str, market_type: MarketType, interval: int | None
) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=(
            AssetClass.CRYPTO_PERP if market_type is MarketType.PERP else AssetClass.CRYPTO_SPOT
        ),
        market_type=market_type,
        base=base,
        quote="USDT",
        tick_size=0.1,
        lot_size=0.001,
        min_qty=0.001,
        min_notional=5.0,
        can_short=True,
        maker_fee_bps=2.0,
        taker_fee_bps=5.0,
        funding_interval_hours=interval,
        listed_ts=T0 - 365 * 24 * HOUR,
        delisted_ts=None,
    )


def _doge_rate(j: int) -> float:
    return SHOCK_RATE if j in (SHOCK_LATE_J, SHOCK_5MIN_J) else 0.0002


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_carry")
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV, _ohlcv_table([BTC, ETH, DOGE, XRP], N_BARS))

    funding_rows: list[tuple[str, int, float, int]] = []
    for j in range(N_BARS // 8):  # settlements every 8h from T0
        ts = T0 + j * 8 * HOUR
        funding_rows.append((BTC, ts, 0.0001, ts + MIN5))
        # DOGE: standard 5-min publication except the deliberately LATE one (+2h).
        lag = 2 * HOUR if j == SHOCK_LATE_J else MIN5
        funding_rows.append((DOGE, ts, _doge_rate(j), ts + lag))
    for j in range(N_BARS // 4):  # ETH settles every 4h (interval-aware fixture)
        ts = T0 + j * 4 * HOUR
        funding_rows.append((ETH, ts, -0.0002, ts + MIN5))
    writer.write(Dataset.FUNDING, _funding_table(funding_rows))

    instruments = InstrumentStore(tmp / "instruments.db")
    instruments.upsert(_instrument(BTC, "BTC", MarketType.PERP, 8), as_of=T0 - 1000)
    instruments.upsert(_instrument(ETH, "ETH", MarketType.PERP, 4), as_of=T0 - 1000)
    instruments.upsert(_instrument(DOGE, "DOGE", MarketType.PERP, 8), as_of=T0 - 1000)
    instruments.upsert(_instrument(XRP, "XRP", MarketType.SPOT, None), as_of=T0 - 1000)

    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    yield Env(engine=engine)
    instruments.close()


def _specs() -> list[FeatureSpec]:
    registry = default_registry()
    return [registry.get(name) for name in CARRY_SPEC_NAMES]


def _value(env: Env, name: str, ts: int, iid: str) -> float:
    out = env.engine.compute_history(
        [default_registry().get(name)], [BTC, ETH, DOGE, XRP], start=ts, end=ts + HOUR
    )
    return float(out.loc[(ts, iid), name])


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        expected_lookbacks = {
            "carry_fund_21": (21 + 1) * MAX_FUNDING_INTERVAL_HOURS + 1,  # 177
            "carry_fund_90": (90 + 1) * MAX_FUNDING_INTERVAL_HOURS + 1,  # 729
        }
        for name, lookback in expected_lookbacks.items():
            spec = registry.get(name)
            assert spec.family is Family.CARRY
            assert spec.direction == +1  # higher carry => higher expected fwd return
            assert spec.cross_sectional is True
            assert spec.lookback_bars == lookback
            assert not spec.is_ewma_family  # finite window: parity atol = 0
        assert registry.get("carry_fund_21").params["n_settlements"] == 21
        assert registry.get("carry_fund_90").params["n_settlements"] == 90

    def test_annualizer_constants(self) -> None:
        assert HOURS_PER_YEAR == 8760
        assert HOURS_PER_YEAR / 8 == 3 * 365  # classic 8h interval == the design's 3*365


# ------------------------------------------------------------------ sign & annualizing


class TestSignAndAnnualization:
    def test_constant_positive_funding_gives_exact_negative_carry(self, env: Env) -> None:
        # Binance convention: f > 0 means longs PAY shorts, so constant +0.01% per
        # 8h settlement is an exact annualized carry of -0.0001 * 3 * 365 = -0.1095.
        ts = T0 + 780 * HOUR
        for name in CARRY_SPEC_NAMES:
            value = _value(env, name, ts, BTC)
            assert value == pytest.approx(-0.0001 * 3 * 365, rel=1e-12)
            assert value < 0.0  # longs pay => negative expected carry for a long

    def test_negative_funding_means_longs_get_paid(self, env: Env) -> None:
        # May-2021-style negative funding: shorts pay longs => CARRY > 0.
        ts = T0 + 780 * HOUR
        assert _value(env, "carry_fund_21", ts, ETH) > 0.0

    def test_interval_aware_annualization_4h(self, env: Env) -> None:
        # ETH settles every 4h: the multiplier must be 8760/4 = 2190 read from the
        # SCD2 instrument record — a hard-coded 3*365 would halve the value.
        ts = T0 + 780 * HOUR
        for name in CARRY_SPEC_NAMES:
            value = _value(env, name, ts, ETH)
            assert value == pytest.approx(0.0002 * (8760 / 4), rel=1e-12)

    def test_spot_instrument_is_nan(self, env: Env) -> None:
        out = env.engine.compute_history(
            _specs(), [BTC, XRP], start=T0 + 760 * HOUR, end=T0 + 790 * HOUR
        )
        for name in CARRY_SPEC_NAMES:
            xrp = out[name].xs(XRP, level="instrument_id")
            assert xrp.isna().all()  # no funding leg: carry undefined, never 0
            assert out[name].xs(BTC, level="instrument_id").notna().all()


# ----------------------------------------------------------------------- PIT gating


class TestPointInTime:
    def test_rate_published_5min_after_settlement_invisible_at_settlement(self, env: Env) -> None:
        # DOGE shock settlement S2 published S2 + 5 min. The bar S2 - 1h decides at
        # S2 (< publication): it must use rates ending at S2 - 8h only.
        s2 = T0 + SHOCK_5MIN_J * 8 * HOUR
        before = _value(env, "carry_fund_21", s2 - HOUR, DOGE)
        after = _value(env, "carry_fund_21", s2, DOGE)  # decides at S2 + 1h >= pub
        assert before == pytest.approx(-0.0002 * 3 * 365, rel=1e-12)
        shocked_mean = (20 * 0.0002 + SHOCK_RATE) / 21
        assert after == pytest.approx(-shocked_mean * 3 * 365, rel=1e-12)

    def test_late_published_rate_invisible_until_available_at(self, env: Env) -> None:
        # DOGE settlement S published 2h LATE: the bar at S decides at S + 1h, which
        # is BEFORE publication — joining on ts_funding would wrongly include it
        # (leakage findings 6/18). It enters at the bar deciding at S + 2h.
        s = T0 + SHOCK_LATE_J * 8 * HOUR
        at_settlement_bar = _value(env, "carry_fund_21", s, DOGE)
        next_bar = _value(env, "carry_fund_21", s + HOUR, DOGE)
        assert at_settlement_bar == pytest.approx(-0.0002 * 3 * 365, rel=1e-12)
        shocked_mean = (20 * 0.0002 + SHOCK_RATE) / 21
        assert next_bar == pytest.approx(-shocked_mean * 3 * 365, rel=1e-12)

    def test_nan_until_k_settlements_published(self, env: Env) -> None:
        # 21st BTC settlement (j=20) at T0+160h, published +5 min: first decision
        # bar that sees all 21 is ts_open = T0+160h (decides T0+161h).
        assert np.isnan(_value(env, "carry_fund_21", T0 + 159 * HOUR, BTC))
        assert np.isfinite(_value(env, "carry_fund_21", T0 + 160 * HOUR, BTC))
        # 90th settlement (j=89) at T0+712h.
        assert np.isnan(_value(env, "carry_fund_90", T0 + 711 * HOUR, BTC))
        assert np.isfinite(_value(env, "carry_fund_90", T0 + 712 * HOUR, BTC))


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_both_carry_specs_exact_under_truncation(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars) must reproduce full-history
        # batch values bit-for-bit; this also proves the declared lookback covers
        # K settlements at the slowest interval (DOGE's shocks add variation).
        ids = [BTC, ETH, DOGE, XRP]
        ts_samples = [T0 + 780 * HOUR + 19 * 60_000, T0 + 795 * HOUR]
        for spec in _specs():
            report = verify_truncation(env.engine, spec, ids, ts_samples, history_start=T0)
            result = report.result(spec.name)
            assert result.passed, f"{spec.name}: {result}"
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0
            assert result.n_points == 8
            # Non-vacuous: perps are real numbers, spot is NaN on BOTH paths.
            live = env.engine.compute_asof([spec], ids, as_of=ts_samples[0])
            assert live[spec.name].xs(XRP, level="instrument_id").isna().all()
            perp_rows = live[spec.name].drop(XRP, level="instrument_id")
            assert perp_rows.notna().all()
