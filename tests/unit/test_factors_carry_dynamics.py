"""Unit tests for alphaforge.features.library.carry_dynamics (BUILD SLATE Pod B).

Covers the two funding-dynamics alphas ``carry_z_252`` (self-relative funding
z-score, fade sign) and ``carry_mom_21_63`` (funding-rate momentum, slope, fade
sign):

* hand-computed values on deterministic fixtures (z-score against a manual mean/std;
  slope against two manual trailing means), with the negation sign asserted;
* the orthogonality-by-construction priors stated in the module docstring made
  concrete -- a CONSTANT funder gives ``carry_z_252 == 0`` (z-score divides out the
  level) AND ``carry_mom_21_63 == 0`` (zero slope), i.e. neither factor re-prices the
  permanently-high level that ``carry_fund_*`` trades;
* the relative-eps sigma floor (a near-constant trailing window => NaN z, never a
  spurious large signal);
* interval-aware PIT gating (a 4h-interval ETH instrument; a 2h-late publication and a
  standard 5-min publication are invisible until ``available_at`` -- leakage findings
  6/18);
* the ``min_periods = K`` warmup boundary for both factors;
* spot instruments (no funding leg) => NaN;
* registered-spec metadata (direction +1, cross-sectional, lookbacks derived from
  params, finite window);
* truncation invariance via ``verify_truncation`` for BOTH specs (atol = 0).

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
    MAX_FUNDING_INTERVAL_HOURS,
    _carry_lookback_bars,
)
from alphaforge.features.library.carry_dynamics import Z_CLIP
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

# BTC: 8h interval, constant +0.0001 funding => z == 0, slope == 0 (orthogonality probe).
BTC = "BINANCE:PERP:BTCUSDT"
# ETH: 4h interval, a deterministic SLOPED ramp of rates (for carry_mom & a finite z).
ETH = "BINANCE:PERP:ETHUSDT"
# DOGE: 8h interval, constant 0.0002 with two planted SHOCK rates (z != 0, PIT gating).
DOGE = "BINANCE:PERP:DOGEUSDT"
# XRP: spot, no funding leg => NaN for both factors.
XRP = "BINANCE:SPOT:XRPUSDT"

HOUR = 3_600_000
MIN5 = 300_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h- and 8h-aligned)
N_BARS = 2400  # > carry_z_252 lookback (2025) so the slow factor is warm late in the run

SHOCK_RATE = 0.0086
SHOCK_LATE_J = 260  # settlement T0 + 260*8h, published 2h late
SHOCK_5MIN_J = 280  # settlement T0 + 280*8h, standard 5-min publication

SPEC_NAMES = ("carry_z_252", "carry_mom_21_63")


# --------------------------------------------------------------------------- builders


def _ohlcv_table(instrument_ids: list[str], n: int) -> pa.Table:
    """Flat deterministic bars; funding dynamics only need the grid, not price moves."""
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
    """rows: (instrument_id, ts_funding, rate, available_at) -- explicit publication."""
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


def _eth_rate(j: int) -> float:
    """Deterministic gently-sloped ramp for ETH (4h settlements) -- finite z & slope."""
    return 0.0001 + 1e-7 * j


def _doge_rate(j: int) -> float:
    return SHOCK_RATE if j in (SHOCK_LATE_J, SHOCK_5MIN_J) else 0.0002


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_carry_dynamics")
    paths = LakePaths(tmp / "lake")
    writer = LakeWriter(paths)
    writer.write(Dataset.OHLCV, _ohlcv_table([BTC, ETH, DOGE, XRP], N_BARS))

    funding_rows: list[tuple[str, int, float, int]] = []
    for j in range(N_BARS // 8):  # BTC & DOGE settle every 8h from T0
        ts = T0 + j * 8 * HOUR
        funding_rows.append((BTC, ts, 0.0001, ts + MIN5))  # CONSTANT funder
        lag = 2 * HOUR if j == SHOCK_LATE_J else MIN5
        funding_rows.append((DOGE, ts, _doge_rate(j), ts + lag))
    for j in range(N_BARS // 4):  # ETH settles every 4h (interval-aware fixture)
        ts = T0 + j * 4 * HOUR
        funding_rows.append((ETH, ts, _eth_rate(j), ts + MIN5))
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
    return [registry.get(name) for name in SPEC_NAMES]


def _value(env: Env, name: str, ts: int, iid: str) -> float:
    out = env.engine.compute_history(
        [default_registry().get(name)], [BTC, ETH, DOGE, XRP], start=ts, end=ts + HOUR
    )
    return float(out.loc[(ts, iid), name])


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        registry = default_registry()
        expected = {
            "carry_z_252": (_carry_lookback_bars(252), {"n_settlements": 252}),
            "carry_mom_21_63": (_carry_lookback_bars(63), {"k_fast": 21, "k_slow": 63}),
        }
        for name, (lookback, params) in expected.items():
            spec = registry.get(name)
            assert spec.family is Family.CARRY
            assert spec.direction == +1  # both fade => higher value = higher fwd return
            assert spec.cross_sectional is True
            assert spec.lookback_bars == lookback
            assert not spec.is_ewma_family  # finite window: parity atol = 0
            for key, val in params.items():
                assert spec.params[key] == val
        assert _carry_lookback_bars(252) == (252 + 1) * MAX_FUNDING_INTERVAL_HOURS + 1  # 2025
        assert _carry_lookback_bars(63) == (63 + 1) * MAX_FUNDING_INTERVAL_HOURS + 1  # 513


# ------------------------------------------------- orthogonality-by-construction probes


class TestOrthogonalToLevel:
    def test_constant_funder_has_zero_zscore(self, env: Env) -> None:
        # BTC funds a CONSTANT +0.0001 forever: its self-relative z-score is 0 (the
        # last rate equals the trailing mean), so carry_z_252 says NOTHING about the
        # (permanently high) level that carry_fund_* trades -- orthogonal by design.
        # A near-constant window trips the sigma floor => NaN, which is the correct
        # "no information" answer; we assert it is NOT a large spurious signal.
        ts = T0 + 2200 * HOUR
        val = _value(env, "carry_z_252", ts, BTC)
        assert np.isnan(val) or abs(val) < 1e-6

    def test_constant_funder_has_zero_slope(self, env: Env) -> None:
        # BTC constant funding => trailing 21-mean == trailing 63-mean => slope 0 =>
        # carry_mom_21_63 == 0. Again: zero overlap with the level factor.
        ts = T0 + 2200 * HOUR
        assert _value(env, "carry_mom_21_63", ts, BTC) == pytest.approx(0.0, abs=1e-15)


# --------------------------------------------------------------- carry_z_252 mechanics


class TestCarryZ:
    def test_zscore_matches_manual_and_fades(self, env: Env) -> None:
        # DOGE: settlements are 0.0002 except the two shocks (0.0086). Choose a
        # decision bar whose last 252 published settlements include exactly the
        # SHOCK_5MIN_J shock as the MOST RECENT rate (the z numerator = last - mean).
        # The settlement at j=SHOCK_5MIN_J is published at +5min; the first decision
        # bar that sees it as the newest rate is ts_open = j*8h (decides at j*8h + 1h).
        j = SHOCK_5MIN_J
        ts = T0 + j * 8 * HOUR
        # The 252 newest published rates at the decision time are j-251 .. j.
        window = np.array([_doge_rate(jj) for jj in range(j - 251, j + 1)], dtype="float64")
        mean = window.mean()
        std = window.std(ddof=1)
        last = window[-1]
        z = (last - mean) / std
        expected = -float(np.clip(z, -Z_CLIP, Z_CLIP))  # fade sign
        got = _value(env, "carry_z_252", ts, DOGE)
        assert got == pytest.approx(expected, rel=1e-10)
        assert got < 0.0  # an anomalously HIGH current funder is faded => negative

    def test_near_constant_window_is_nan_not_huge(self, env: Env) -> None:
        # A DOGE decision bar whose trailing-252 window is entirely 0.0002 (no shock
        # inside it): the sigma floor fires => NaN, never a divide-by-tiny blowup.
        # Window j-251..j must contain neither shock. SHOCK_LATE_J=260 is the first;
        # pick j so that j < 260 and j-251 >= 0 => j in [251, 259]. Use j = 255.
        j = 255
        ts = T0 + j * 8 * HOUR
        assert np.isnan(_value(env, "carry_z_252", ts, DOGE))


# ---------------------------------------------------------- carry_mom_21_63 mechanics


class TestCarryMom:
    def test_slope_matches_manual_and_signs(self, env: Env) -> None:
        # ETH funds a strictly increasing ramp at 4h settlements => the trailing
        # 21-mean is ABOVE the trailing 63-mean (the recent rates are larger), so the
        # slope is positive and carry_mom = -slope < 0 (a rising basis is bad carry).
        # Pick a late bar so both legs are warm. The 21 & 63 newest published ETH rates
        # at decision time are the last 21 / 63 settlements (4h cadence).
        j = 500  # ETH settlement index (4h apart)
        ts = T0 + j * 4 * HOUR
        fast = np.array([_eth_rate(jj) for jj in range(j - 20, j + 1)], dtype="float64").mean()
        slow = np.array([_eth_rate(jj) for jj in range(j - 62, j + 1)], dtype="float64").mean()
        expected = -(fast - slow)
        got = _value(env, "carry_mom_21_63", ts, ETH)
        assert got == pytest.approx(expected, rel=1e-10)
        assert got < 0.0  # rising funding trend => -slope < 0


# ----------------------------------------------------------------------- PIT gating


class TestPointInTime:
    def test_spot_instrument_is_nan(self, env: Env) -> None:
        out = env.engine.compute_history(
            _specs(), [BTC, XRP], start=T0 + 2200 * HOUR, end=T0 + 2204 * HOUR
        )
        for name in SPEC_NAMES:
            xrp = out[name].xs(XRP, level="instrument_id")
            assert xrp.isna().all()  # no funding leg: undefined, never 0

    def test_late_published_shock_invisible_until_available_at(self, env: Env) -> None:
        # DOGE shock settlement S (j=SHOCK_LATE_J) published 2h LATE: the bar at S
        # decides at S + 1h (BEFORE publication), so the shock must NOT enter the
        # z-window yet; it enters at the bar deciding at S + 2h. We probe via the
        # z-score becoming non-NaN/large only after the shock is visible.
        s = T0 + SHOCK_LATE_J * 8 * HOUR
        at_settlement_bar = _value(env, "carry_z_252", s, DOGE)  # decides S + 1h < pub
        next_bar = _value(env, "carry_z_252", s + 2 * HOUR, DOGE)  # decides S + 3h >= pub
        # Before publication the newest rate the trader sees is the prior 0.0002 batch
        # (constant window => NaN per the sigma floor). After, the shock is the newest
        # rate => a finite, fade-sign (negative) z.
        assert np.isnan(at_settlement_bar)
        assert np.isfinite(next_bar)
        assert next_bar < 0.0

    def test_nan_until_k_settlements_published(self, env: Env) -> None:
        # carry_z_252 needs 252 DOGE settlements before it can produce a value at all.
        # j=250 (T0+2000h) has only 251 published => NaN regardless of content.
        assert np.isnan(_value(env, "carry_z_252", T0 + 2000 * HOUR, DOGE))
        # Even once 252 settlements exist, a window that is entirely 0.0002 (no shock
        # inside it) trips the sigma floor => NaN (correct "no information" answer);
        # a finite z only appears once a shock enters the 252-window. The 5-min shock
        # j=280 (T0+2240h) is the newest rate at ts_open=T0+2240h (decides +1h >= pub),
        # giving a finite, fade-sign value. (See TestCarryZ for the exact value.)
        assert np.isfinite(_value(env, "carry_z_252", T0 + 280 * 8 * HOUR, DOGE))
        # carry_mom_21_63 needs 63 settlements: j=61 (T0+488h) has only 62 => NaN;
        # ETH ramps, so its 63rd-settlement bar is finite (a nonzero slope). ETH
        # settles every 4h: j=62 at T0+248h => ts_open=T0+248h decides T0+249h.
        assert np.isnan(_value(env, "carry_mom_21_63", T0 + 244 * HOUR, ETH))
        assert np.isfinite(_value(env, "carry_mom_21_63", T0 + 248 * HOUR, ETH))


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_both_specs_exact_under_truncation(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars) must reproduce full-history
        # batch values bit-for-bit; DOGE's shocks and ETH's ramp add real variation.
        ids = [BTC, ETH, DOGE, XRP]
        ts_samples = [T0 + 2300 * HOUR + 19 * 60_000, T0 + 2350 * HOUR]
        for spec in _specs():
            report = verify_truncation(env.engine, spec, ids, ts_samples, history_start=T0)
            result = report.result(spec.name)
            assert result.passed, f"{spec.name}: {result}"
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0
            assert result.n_points == 8
            # Non-vacuous: at least one perp carries a finite value, spot is NaN.
            live = env.engine.compute_asof([spec], ids, as_of=ts_samples[0])
            assert live[spec.name].xs(XRP, level="instrument_id").isna().all()
            perp_rows = live[spec.name].drop(XRP, level="instrument_id")
            assert perp_rows.notna().any()
