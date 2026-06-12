"""Unit tests for alphaforge.features.library.regime_features (alphaDesign.md §2.7).

Covers: market breadth on a hand-planted 4-member point-in-time universe (exact
fractions 1/3 and 2/4 before/after a member's entry; strict-greater SMA indicator
on an exactly-flat instrument; non-members excluded from numerator AND
denominator), broadcast semantics (one market value repeated across the requested
cross-section), per-symbol BTC correlation against ``numpy.corrcoef`` on the
planted return windows (anchor column exactly 1.0, zero-variance symbol NaN),
the BTC-anchor fail-loud contract (anchor must be requested), the realized-vol
percentile against a brute-force count over the trailing-year window of
Yang-Zhang vols, exact warmup boundaries, and truncation invariance via
``verify_truncation`` for EVERY registered regime spec (finite windows:
``max_abs_diff == 0.0``).

All lake-backed tests run against deterministic synthetic tmp lakes (offline).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.regime_features import BTC_ANCHOR
from alphaforge.features.library.vol import yang_zhang
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = BTC_ANCHOR  # "BINANCE:PERP:BTCUSDT" — the documented market proxy
UP = "BINANCE:PERP:SOLUSDT"  # uptrend, universe member from T0
UP2 = "BINANCE:PERP:AVAXUSDT"  # uptrend, ENTERS the universe at T0 + 800h
FLAT = "BINANCE:PERP:DOGEUSDT"  # exactly constant close, member from T0
DOWN = "BINANCE:PERP:ADAUSDT"  # downtrend, member from T0
CORRA = "BINANCE:PERP:ETHUSDT"  # returns = 0.5 * r_btc + noise; NEVER a member

ALL_IDS = (BTC, UP, UP2, FLAT, DOWN, CORRA)

HOUR = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h-aligned)
N_BARS = 900
N_BIG = 9_600  # > reg_rvp_720 lookback (9480)
UP2_ENTRY = T0 + 800 * HOUR

ALT = "BINANCE:PERP:SOLUSDT"  # second instrument in the rvp lake


# --------------------------------------------------------------------------- builders


def _closes(n: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(51)
    r_btc = rng.normal(0.0, 0.005, n)
    r_corr = 0.5 * r_btc + rng.normal(0.0, 0.002, n)
    k = np.arange(n, dtype="float64")
    return {
        BTC: 100.0 * np.exp(np.cumsum(r_btc)),
        UP: 100.0 * np.exp(0.0005 * k),
        UP2: 50.0 * np.exp(0.0005 * k),
        FLAT: np.full(n, 100.0),
        DOWN: 100.0 * np.exp(-0.0005 * k),
        CORRA: 100.0 * np.exp(np.cumsum(r_corr)),
    }


def _make_ohlc(seed: int, n: int, level: float) -> dict[str, np.ndarray]:
    """Random walk with valid OHLC geometry (the rvp lake needs real ranges)."""
    rng = np.random.default_rng(seed)
    close = level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n)))
    open_ = np.empty(n)
    open_[0] = level
    open_[1:] = close[:-1] * np.exp(rng.normal(0.0, 0.001, n - 1))
    wick = np.abs(rng.normal(0.0, 0.002, n))
    high = np.maximum(open_, close) * np.exp(wick)
    low = np.minimum(open_, close) * np.exp(-wick)
    return {"open": open_, "high": high, "low": low, "close": close}


def _ohlcv_table(per_inst: dict[str, dict[str, np.ndarray]]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    cols: dict[str, list[float]] = {"open": [], "high": [], "low": [], "close": []}
    for iid, ohlc in per_inst.items():
        n = len(ohlc["close"])
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        for name in cols:
            cols[name].extend(float(v) for v in ohlc[name])
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(cols["open"], type=pa.float64()),
            "high": pa.array(cols["high"], type=pa.float64()),
            "low": pa.array(cols["low"], type=pa.float64()),
            "close": pa.array(cols["close"], type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1000.0] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
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


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    close: dict[str, np.ndarray]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_regime")
    paths = LakePaths(tmp / "lake")
    close = _closes(N_BARS)
    per_inst = {
        iid: {"open": c, "high": c * 1.001, "low": c * 0.999, "close": c}
        for iid, c in close.items()
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(per_inst))
    universe = UniverseStore(paths)
    universe.write_intervals(
        _universe_table(
            [(UP, T0, None), (FLAT, T0, None), (DOWN, T0, None), (UP2, UP2_ENTRY, None)]
        )
    )
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    yield Env(engine=engine, close=close)
    instruments.close()


@dataclass(frozen=True)
class BigEnv:
    engine: FeatureEngine
    ohlc: dict[str, dict[str, np.ndarray]]


@pytest.fixture(scope="module")
def env_big(tmp_path_factory: pytest.TempPathFactory) -> Iterator[BigEnv]:
    tmp = tmp_path_factory.mktemp("factors_regime_big")
    paths = LakePaths(tmp / "lake")
    ohlc = {BTC: _make_ohlc(61, N_BIG, 100.0), ALT: _make_ohlc(62, N_BIG, 50.0)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, UniverseStore(paths))
    yield BigEnv(engine=engine, ohlc=ohlc)
    instruments.close()


def _spec(name: str) -> FeatureSpec:
    return default_registry().get(name)


def _row(env: Env, name: str, ts: int, ids: list[str]) -> pd.Series:
    out = env.engine.compute_history([_spec(name)], ids, start=ts, end=ts + HOUR)
    return out[name].xs(ts, level="ts_open")


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpecs:
    def test_metadata(self) -> None:
        expected_lookbacks = {
            "reg_rvp_720": 8760 + 720,  # oldest percentile slot's YZ needs 721 bars
            "reg_corr_btc_720": 721,  # 720 returns need 721 closes
            "reg_breadth_sma720": 720,
            "reg_breadth_mom168": 169,  # the return needs C_{t-168}
        }
        for name, lookback in expected_lookbacks.items():
            spec = _spec(name)
            assert spec.family is Family.REGIME
            assert spec.direction == 0  # context features, not alphas
            assert spec.cross_sectional is False  # excluded from CS z-scoring
            assert spec.lookback_bars == lookback
            assert not spec.is_ewma_family

    def test_anchor_param_documents_perp_proxy(self) -> None:
        for name in ("reg_rvp_720", "reg_corr_btc_720"):
            assert _spec(name).params["anchor"] == "BINANCE:PERP:BTCUSDT"

    def test_anchor_must_be_requested_fail_loud(self, env: Env) -> None:
        ts = T0 + 850 * HOUR
        for name in ("reg_rvp_720", "reg_corr_btc_720"):
            with pytest.raises(ValueError, match="anchor"):
                env.engine.compute_history([_spec(name)], [UP, DOWN], start=ts, end=ts + HOUR)


# --------------------------------------------------------------------------- breadth


class TestBreadth:
    def test_exact_fractions_on_planted_universe(self, env: Env) -> None:
        ids = list(ALL_IDS)
        # Before UP2's entry: members {UP, FLAT, DOWN}. UP is above its SMA720 and
        # has a positive 168-bar return; FLAT sits EXACTLY on its SMA (strict ">"
        # excludes it) with a 0 return (strict ">" excludes it); DOWN is below/negative.
        ts = T0 + 780 * HOUR
        assert _row(env, "reg_breadth_sma720", ts, ids).iloc[0] == 1.0 / 3.0
        assert _row(env, "reg_breadth_mom168", ts, ids).iloc[0] == 1.0 / 3.0
        # After UP2 enters (4-member universe): two of four are up => exactly 1/2.
        ts2 = T0 + 850 * HOUR
        assert _row(env, "reg_breadth_sma720", ts2, ids).iloc[0] == 0.5
        assert _row(env, "reg_breadth_mom168", ts2, ids).iloc[0] == 0.5

    def test_membership_is_point_in_time(self, env: Env) -> None:
        # UP2's interval starts at exactly T0 + 800h: the bar AT the entry instant
        # already counts it (half-open membership), the bar before does not.
        ids = list(ALL_IDS)
        before = _row(env, "reg_breadth_sma720", UP2_ENTRY - HOUR, ids).iloc[0]
        at_entry = _row(env, "reg_breadth_sma720", UP2_ENTRY, ids).iloc[0]
        assert before == 1.0 / 3.0
        assert at_entry == 0.5

    def test_broadcast_same_value_for_every_requested_instrument(self, env: Env) -> None:
        ids = list(ALL_IDS)
        for name in ("reg_breadth_sma720", "reg_breadth_mom168"):
            row = _row(env, name, T0 + 850 * HOUR, ids)
            assert len(row) == len(ids)
            assert row.nunique() == 1  # one market-level value, repeated

    def test_non_members_excluded_from_both_sides(self, env: Env) -> None:
        # BTC and CORRA are never members: requesting them must not change the
        # fraction (they are excluded from numerator AND denominator).
        ts = T0 + 780 * HOUR
        with_extras = _row(env, "reg_breadth_mom168", ts, list(ALL_IDS)).iloc[0]
        without = _row(env, "reg_breadth_mom168", ts, [UP, FLAT, DOWN]).iloc[0]
        assert with_extras == without == 1.0 / 3.0


# ------------------------------------------------------------------- BTC correlation


class TestCorrBtc:
    def test_matches_numpy_corrcoef_on_planted_window(self, env: Env) -> None:
        k = 850
        row = _row(env, "reg_corr_btc_720", T0 + k * HOUR, list(ALL_IDS))
        c_btc, c_a = env.close[BTC], env.close[CORRA]
        r_btc = np.diff(np.log(c_btc))
        r_a = np.diff(np.log(c_a))
        # Bar k's window holds the returns of bars k-719 .. k (diff index i-1).
        expected = float(np.corrcoef(r_a[k - 720 : k], r_btc[k - 720 : k])[0, 1])
        assert row[CORRA] == pytest.approx(expected, rel=1e-9)
        assert 0.5 < row[CORRA] < 1.0  # planted positive dependence, not degenerate

    def test_anchor_column_is_exactly_one(self, env: Env) -> None:
        row = _row(env, "reg_corr_btc_720", T0 + 850 * HOUR, list(ALL_IDS))
        assert row[BTC] == 1.0

    def test_zero_variance_symbol_is_nan(self, env: Env) -> None:
        row = _row(env, "reg_corr_btc_720", T0 + 850 * HOUR, list(ALL_IDS))
        assert np.isnan(row[FLAT])  # constant close: correlation undefined, never 0

    def test_warmup_boundary(self, env: Env) -> None:
        out = env.engine.compute_history(
            [_spec("reg_corr_btc_720")], [BTC, CORRA], start=T0 + 719 * HOUR, end=T0 + 721 * HOUR
        )
        col = out["reg_corr_btc_720"].xs(CORRA, level="instrument_id")
        assert np.isnan(col.iloc[0])  # bar 719: only 719 returns exist
        assert np.isfinite(col.iloc[1])  # bar 720: first full 720-return window


# ------------------------------------------------------------- realized-vol percentile


class TestRvp:
    def test_matches_brute_force_count(self, env_big: BigEnv) -> None:
        k = 9_500
        out = env_big.engine.compute_history(
            [_spec("reg_rvp_720")], [BTC, ALT], start=T0 + k * HOUR, end=T0 + (k + 1) * HOUR
        )
        index = pd.Index([T0 + j * HOUR for j in range(N_BIG)], name="ts_open")
        panels = {
            f: pd.DataFrame({iid: env_big.ohlc[iid][f] for iid in (BTC, ALT)}, index=index)
            for f in ("open", "high", "low", "close")
        }
        sigma = yang_zhang(
            panels["open"],
            panels["high"],
            panels["low"],
            panels["close"],
            window=720,
            annualize=True,
        )[BTC].to_numpy()
        window = sigma[k - 8_759 : k + 1]
        expected = float(np.sum(window <= sigma[k])) / 8_760.0
        got = out.loc[(T0 + k * HOUR, BTC), "reg_rvp_720"]
        assert got == expected
        assert 0.0 < got <= 1.0  # the k=0 term always counts itself
        # Broadcast: ALT carries the same market-level value.
        assert out.loc[(T0 + k * HOUR, ALT), "reg_rvp_720"] == got

    def test_warmup_boundary(self, env_big: BigEnv) -> None:
        # sigma_YZ(720) first exists at bar 720; the percentile needs 8760 of them:
        # first finite RVP at bar 720 + 8760 - 1 = 9479 == lookback_bars - 1.
        out = env_big.engine.compute_history(
            [_spec("reg_rvp_720")], [BTC], start=T0 + 9_478 * HOUR, end=T0 + 9_480 * HOUR
        )
        col = out["reg_rvp_720"].xs(BTC, level="instrument_id")
        assert np.isnan(col.iloc[0])
        assert np.isfinite(col.iloc[1])


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    def test_corr_and_breadth_exact_under_truncation(self, env: Env) -> None:
        ts_samples = [T0 + 850 * HOUR + 19 * 60_000, T0 + 880 * HOUR]
        for name in ("reg_corr_btc_720", "reg_breadth_sma720", "reg_breadth_mom168"):
            spec = _spec(name)
            report = verify_truncation(
                env.engine, spec, list(ALL_IDS), ts_samples, history_start=T0
            )
            result = report.result(name)
            assert result.passed, f"{name}: {result}"
            assert result.rtol == 0.0
            assert result.max_abs_diff == 0.0
            assert result.n_points == 12
            live = env.engine.compute_asof([spec], list(ALL_IDS), as_of=ts_samples[0])
            assert live[name].xs(CORRA, level="instrument_id").notna().all()  # non-vacuous

    def test_rvp_exact_under_truncation(self, env_big: BigEnv) -> None:
        spec = _spec("reg_rvp_720")
        ts_samples = [T0 + 9_550 * HOUR + 19 * 60_000]
        report = verify_truncation(env_big.engine, spec, [BTC, ALT], ts_samples, history_start=T0)
        result = report.result(spec.name)
        assert result.passed, result
        assert result.rtol == 0.0
        assert result.max_abs_diff == 0.0
        assert result.n_points == 2
        live = env_big.engine.compute_asof([spec], [BTC, ALT], as_of=ts_samples[0])
        assert live["reg_rvp_720"].notna().all()  # non-vacuous


def test_anchor_constant_matches_design() -> None:
    assert BTC_ANCHOR == "BINANCE:PERP:BTCUSDT"
