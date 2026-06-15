"""Unit tests for alphaforge.features.library.market_state (build slate Pod A).

Covers ``beta_lowbeta_720`` (betting-against-beta): the registered fn returns the
raw rolling market beta against the equal-weight PIT-universe return, with
``direction=-1`` carrying the low-beta sign. Tests assert:

* the fn output equals ``rolling_beta`` on the identical PIT-masked panel,
  bit-for-bit (finite window => parity atol = 0);
* PIT membership genuinely changes the market (a mid-history universe entry must
  move the beta vs a naive everyone-is-a-member market);
* registered-spec metadata (family REGIME, direction -1, CS, derived
  lookback_bars = BETA_WINDOW + 1 = 721, NOT EWMA-family);
* exact NaN-warmup boundary (first finite beta at index BETA_WINDOW + 1);
* the raw value is NOT pre-negated (the sign lives on the spec, not the fn);
* truncation invariance via ``verify_truncation`` (finite window: atol = 0).

All lake-backed tests run against a deterministic synthetic tmp lake (offline).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.core.instruments import InstrumentStore
from alphaforge.data.schemas import UNIVERSE_SCHEMA, Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.library.mean_reversion import (
    BETA_WINDOW,
    market_return,
    rolling_beta,
)
from alphaforge.features.library.vol import log_returns
from alphaforge.features.parity import verify_truncation
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

if TYPE_CHECKING:
    from collections.abc import Iterator

    from alphaforge.features.spec import FeatureSpec

BTC = "BINANCE:PERP:BTCUSDT"
ETH = "BINANCE:PERP:ETHUSDT"
SOL = "BINANCE:PERP:SOLUSDT"
IDS = (BTC, ETH, SOL)

HOUR = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z (1h-aligned)
N_BARS = 1100  # > beta lookback (722) + sample headroom
SOL_ENTRY_BAR = 850  # SOL joins the PIT universe mid-history
LOOKBACK = BETA_WINDOW + 2  # 722 == declared lookback_bars (counts the valued bar)
# Formula warmup: beta needs BETA_WINDOW returns through t-1; returns valid from
# grid index 1, so the window is first full at grid index BETA_WINDOW + 1 = 721
# (one less than lookback_bars: lookback counts the valued bar, this is its index).
FIRST_FINITE = BETA_WINDOW + 1  # 721

NAME = "beta_lowbeta_720"


# --------------------------------------------------------------------------- builders


def _make_ohlc(seed: int, n: int, level: float) -> dict[str, np.ndarray]:
    """Deterministic OHLC random walk with valid bar geometry (H >= max(O,C) >= L)."""
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


def _universe_table() -> pa.Table:
    """BTC/ETH members from T0; SOL enters at SOL_ENTRY_BAR (PIT mid-history entry)."""
    return pa.table(
        {
            "instrument_id": [BTC, ETH, SOL],
            "effective_from": pa.array(
                [T0, T0, T0 + SOL_ENTRY_BAR * HOUR], type=pa.timestamp("ms", tz="UTC")
            ),
            "effective_to": pa.array([None, None, None], type=pa.timestamp("ms", tz="UTC")),
            "rank": pa.array([1, 2, 3], type=pa.int32()),
            "reason": ["enter_top40", "enter_top40", "enter_top40"],
        },
        schema=UNIVERSE_SCHEMA,
    )


@dataclass(frozen=True)
class Env:
    engine: FeatureEngine
    ohlc: dict[str, dict[str, np.ndarray]]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("factors_market_state")
    paths = LakePaths(tmp / "lake")
    ohlc = {
        BTC: _make_ohlc(61, N_BARS, 100.0),
        ETH: _make_ohlc(62, N_BARS, 50.0),
        SOL: _make_ohlc(63, N_BARS, 20.0),
    }
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(ohlc))
    universe = UniverseStore(paths)
    universe.write_intervals(_universe_table())
    instruments = InstrumentStore(tmp / "instruments.db")
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    yield Env(engine=engine, ohlc=ohlc)
    instruments.close()


def _spec() -> FeatureSpec:
    return default_registry().get(NAME)


def _close_panel(env: Env) -> pd.DataFrame:
    index = pd.Index([T0 + k * HOUR for k in range(N_BARS)], name="ts_open")
    return pd.DataFrame({iid: env.ohlc[iid]["close"] for iid in IDS}, index=index)


def _pit_mask(index: pd.Index) -> pd.DataFrame:
    """The hand-built PIT membership mask matching ``_universe_table``."""
    mask = pd.DataFrame(True, index=index, columns=pd.Index(list(IDS)))
    mask.loc[mask.index < T0 + SOL_ENTRY_BAR * HOUR, SOL] = False
    return mask


# ------------------------------------------------------------------- registered specs


class TestRegisteredSpec:
    def test_metadata(self) -> None:
        spec = _spec()
        assert spec.family is Family.REGIME
        assert spec.direction == -1  # betting-against-beta: high beta priced down
        assert spec.cross_sectional is True
        assert not spec.is_ewma_family  # finite window: parity atol = 0
        assert spec.lookback_bars == LOOKBACK == 722
        assert spec.params["beta_window"] == BETA_WINDOW == 720

    def test_engine_output_equals_rolling_beta_with_pit_mask(self, env: Env) -> None:
        # start chosen so the engine warm-up headroom (lookback 721) lands exactly
        # on the lake start: the context panel and the hand-built panel are the
        # identical array, so equality must be bit-for-bit (finite window).
        out = env.engine.compute_history(
            [_spec()], list(IDS), start=T0 + LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        close = _close_panel(env)
        returns = log_returns(close)
        mkt = market_return(returns, _pit_mask(close.index))
        expected = rolling_beta(returns, mkt, window=BETA_WINDOW).iloc[LOOKBACK:]
        assert np.array_equal(out[NAME].to_numpy(), expected.to_numpy().ravel(), equal_nan=True)
        assert out[NAME].notna().all()  # non-vacuous

    def test_value_is_raw_beta_not_negated(self, env: Env) -> None:
        # direction=-1 owns the sign; the fn returns the raw beta. With a positive
        # mean cross-sectional market exposure (a long-biased synthetic), the raw
        # betas are predominantly positive -> the fn must NOT pre-negate them.
        out = env.engine.compute_history(
            [_spec()], list(IDS), start=T0 + LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        vals = out[NAME].to_numpy()
        finite = vals[np.isfinite(vals)]
        assert finite.size > 0
        assert np.median(finite) > 0.0  # raw betas, not flipped to negative

    def test_pit_membership_changes_the_market(self, env: Env) -> None:
        # SOL enters at bar 850 (inside the output range). A naive
        # everyone-is-always-a-member market MUST disagree with the PIT-masked
        # result (selection into m_t is time-varying), so the betas differ.
        out = env.engine.compute_history(
            [_spec()], list(IDS), start=T0 + LOOKBACK * HOUR, end=T0 + N_BARS * HOUR
        )
        close = _close_panel(env)
        returns = log_returns(close)
        naive_mask = pd.DataFrame(True, index=close.index, columns=close.columns)
        naive = rolling_beta(returns, market_return(returns, naive_mask), window=BETA_WINDOW).iloc[
            LOOKBACK:
        ]
        assert not np.array_equal(out[NAME].to_numpy(), naive.to_numpy().ravel(), equal_nan=True)

    def test_warmup_boundary(self, env: Env) -> None:
        # Lake history starts at T0. rolling_beta needs BETA_WINDOW returns through
        # t-1; returns are valid from index 1, so the window is first full at grid
        # index BETA_WINDOW + 1 = 721 (one less than the declared lookback_bars,
        # which counts the valued bar).
        out = env.engine.compute_history([_spec()], list(IDS), start=T0, end=T0 + N_BARS * HOUR)
        col = out[NAME].xs(BTC, level="instrument_id")
        first_finite = int(np.flatnonzero(col.notna().to_numpy())[0])
        assert first_finite == FIRST_FINITE == 721
        assert np.isnan(col.iloc[first_finite - 1])


# -------------------------------------------------------------- truncation invariance


class TestTruncationInvariance:
    TS_SAMPLES = (T0 + 1000 * HOUR + 13 * 60_000, T0 + 1080 * HOUR)

    def test_exact_under_truncation(self, env: Env) -> None:
        # Live minimal window (exactly lookback_bars = 721) vs full history must be
        # bit-for-bit identical: no EWMA recursion anywhere => finite-window atol 0.
        spec = _spec()
        report = verify_truncation(
            env.engine, spec, list(IDS), list(self.TS_SAMPLES), history_start=T0
        )
        result = report.result(NAME)
        assert result.passed, f"{NAME}: {result}"
        assert result.rtol == 0.0
        assert result.max_abs_diff == 0.0  # finite window: exact
        assert result.n_points == 6  # 2 samples x 3 instruments
        # Non-vacuous: the sampled values are real numbers, not NaN==NaN.
        live = env.engine.compute_asof([spec], list(IDS), as_of=self.TS_SAMPLES[0])
        assert live[NAME].notna().all()
