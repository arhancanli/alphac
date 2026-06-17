"""Train/serve parity for the ONE shared meta-feature surface (Phase 12, D4).

``alphaforge.signals.features_serve.assemble_meta_features`` is the single helper
the Phase-9 dataset builder (training) and ``SignalService`` (serve) both route X
through, so the model's feature matrix at decision bar ``t`` is byte-identical on
both paths (12_FINAL.md §D4, leakage #15). This test pins that on the real feature
engine over a synthetic lake (the ``test_signal_service.py`` idiom):

* **directional alphas resolve to the PROCESSED, direction-signed ``zs`` column,
  NEVER the raw ``frame[name]``** — the exact skew the original
  ``x = frame[feature_names]`` body would have introduced;
* **``direction == 0`` context resolves to the RAW ``frame[name]``**;
* **a train window and an overlapping serve window produce IDENTICAL columns on
  their overlap** (the parity invariant — same engine surface in, same X out);
* output columns are exactly ``feature_names`` in order; a name in neither ``zs``
  nor ``frame`` is a loud ``KeyError``.

Offline; tmp_path lake only; deterministic (seeded rng).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from alphaforge.config.settings import SignalsCfg
from alphaforge.core.instruments import Instrument, InstrumentStore
from alphaforge.core.types import AssetClass, MarketType
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.store.writer import LakeWriter
from alphaforge.data.universe.store import UniverseStore
from alphaforge.features.context import long_series
from alphaforge.features.engine import FeatureEngine
from alphaforge.features.registry import FeatureRegistry
from alphaforge.features.spec import Family, FeatureSpec
from alphaforge.signals.features_serve import assemble_meta_features
from alphaforge.signals.service import (
    _OPEN_SPEC,
    _SIGMA_SPEC,
    SIGMA_COLUMN,
    SignalService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from alphaforge.features.context import FeatureContext

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z
N_BARS = 840

MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
ALL_IDS = list(MEMBERS)

# The full span the lake covers; the two windows below overlap inside it.
SPAN_START = T0 + 240 * HOUR  # alphas + sigma + the direction==0 context are warm here
SPAN_END = T0 + N_BARS * HOUR

# A "train" window and a later, OVERLAPPING "serve" window. The overlap is where the
# two assembled surfaces MUST be byte-identical (slice-invariance of the engine
# surface + the single helper).
TRAIN_START = SPAN_START
TRAIN_END = T0 + 720 * HOUR
SERVE_START = T0 + 480 * HOUR
SERVE_END = SPAN_END
OVERLAP_START = SERVE_START
OVERLAP_END = TRAIN_END

# direction != 0 (blended, processed) and direction == 0 (raw context) feature names.
DIRECTIONAL = ("alpha_fast", "alpha_slow")
CONTEXT = "ctx_vol"  # a direction==0 risk/regime context column, fed RAW
FEATURE_NAMES = (*DIRECTIONAL, CONTEXT)


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """w-bar log return on the complete grid (test alpha; gaps stay NaN)."""
    close = ctx.panel("close")
    window = int(spec.params["window"])
    out: pd.DataFrame = np.log(close / close.shift(window))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _abs_ret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """A direction==0 risk-context column: |1-bar log return| (raw, never z-scored)."""
    close = ctx.panel("close")
    out: pd.DataFrame = np.abs(np.log(close / close.shift(1)))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _registry() -> FeatureRegistry:
    reg = FeatureRegistry()

    def alpha_fast() -> FeatureSpec:
        window = 24
        return FeatureSpec(
            name="alpha_fast",
            family=Family.MOMENTUM,
            direction=1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    def alpha_slow() -> FeatureSpec:
        window = 96
        return FeatureSpec(
            name="alpha_slow",
            family=Family.REVERSAL,
            direction=-1,  # exercises the direction multiply through the seam
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    def ctx_vol() -> FeatureSpec:
        return FeatureSpec(
            name=CONTEXT,
            family=Family.VOLATILITY,
            direction=0,  # risk/regime context — fed RAW, never blended
            cross_sectional=False,
            lookback_bars=2,
            params={},
            fn=_abs_ret_fn,
        )

    reg.register(alpha_fast)
    reg.register(alpha_slow)
    reg.register(ctx_vol)
    return reg


def _closes(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(level * np.exp(np.cumsum(rng.normal(0.0, 0.005, n))))


def _ohlcv_table(per_inst: dict[str, np.ndarray]) -> pa.Table:
    iids: list[str] = []
    ts: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for iid, close in per_inst.items():
        n = len(close)
        iids.extend([iid] * n)
        ts.extend(T0 + k * HOUR for k in range(n))
        opens.append(float(close[0]))
        opens.extend(float(v) for v in close[:-1])  # open = previous close
        closes.extend(float(v) for v in close)
    n_rows = len(iids)
    return pa.table(
        {
            "instrument_id": pa.array(iids, type=pa.string()),
            "ts_open": pa.array(ts, type=pa.timestamp("ms", tz="UTC")),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array([v * 1.001 for v in closes], type=pa.float64()),
            "low": pa.array([v * 0.999 for v in closes], type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array([10.0] * n_rows, type=pa.float64()),
            "quote_volume": pa.array([1.0e6] * n_rows, type=pa.float64()),
            "n_trades": pa.array([42] * n_rows, type=pa.int64()),
            "quality_flags": pa.array([0] * n_rows, type=pa.int32()),
            "ingested_at": pa.array(
                [t + HOUR + 1000 for t in ts], type=pa.timestamp("ms", tz="UTC")
            ),
        }
    )


def _instrument(instrument_id: str) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.CRYPTO_PERP,
        market_type=MarketType.PERP,
        base=instrument_id.split(":")[2].removesuffix("USDT"),
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
    service: SignalService
    ctx_spec: FeatureSpec  # the direction==0 context spec the model also consumes


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("feature_serve_parity")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(100 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(ALL_IDS)}
    LakeWriter(paths).write(Dataset.OHLCV, _ohlcv_table(closes))

    universe = UniverseStore(paths)
    universe.write_intervals(
        pa.table(
            {
                "instrument_id": pa.array(list(MEMBERS), type=pa.string()),
                "effective_from": pa.array([T0] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "effective_to": pa.array([None] * len(MEMBERS), type=pa.timestamp("ms", tz="UTC")),
                "rank": pa.array([1] * len(MEMBERS), type=pa.int32()),
                "reason": pa.array(["enter_top40"] * len(MEMBERS), type=pa.string()),
            }
        )
    )

    instruments = InstrumentStore(tmp / "instruments.db")
    for iid in ALL_IDS:
        instruments.upsert(_instrument(iid), as_of=T0 - 1000)

    cfg = SignalsCfg()
    registry = _registry()
    engine = FeatureEngine(PITDataReader(paths), instruments, universe)
    # The blend uses only the directional alphas; the direction==0 ctx column rides
    # along through the engine spec set (the service rejects direction==0 names as
    # *alphas*, so it is NOT in alpha_names — exactly the 12_FINAL §2 case where the
    # per-leg builder threads a context spec into the engine compute).
    service = SignalService(engine, universe, registry, cfg, alpha_names=DIRECTIONAL)
    yield Env(service=service, ctx_spec=registry.get(CONTEXT))
    instruments.close()


def _panel(
    env: Env, start: int, end: int
) -> tuple[pd.DataFrame, pd.Series, Mapping[str, pd.Series]]:
    """The engine's processed surface BOTH train and serve assemble X from.

    Replicates ``SignalService._panel`` (the seam both ``compute_research`` and the
    Phase-9 dataset builder consume) but threads the ``direction == 0`` context spec
    into the engine compute — the 12_FINAL.md §2 case where a model lists a context
    column the alpha set does not already produce, so the per-leg builder constructs
    the service over the extended spec set. ``zs`` carries only the directional
    (processed, signed) subset, exactly as the service produces it.
    """
    service = env.service
    ids = service._window_ids(start, end)
    specs = [*service._alpha_specs, _SIGMA_SPEC, _OPEN_SPEC, env.ctx_spec]
    frame = service._engine.compute_history(specs, ids, start=start, end=end)
    assert isinstance(frame.index, pd.MultiIndex)
    mask = service._membership_mask(frame.index)
    zs = service._directional_zs(frame, mask)
    return frame, mask, zs


class TestResolution:
    def test_directional_names_resolve_to_processed_zs_not_raw_frame(self, env: Env) -> None:
        """The load-bearing skew assertion (D4 / leakage #15): a directional name's
        served column is its PROCESSED, direction-signed ``zs`` value — NOT the raw
        ``frame[name]`` the buggy original body would have handed the model."""
        frame, _mask, zs = _panel(env, SPAN_START, SPAN_END)
        x = assemble_meta_features(frame, zs, FEATURE_NAMES)
        for name in DIRECTIONAL:
            pd.testing.assert_series_equal(
                x[name], zs[name].reindex(frame.index).astype("float64"), check_names=False
            )
            # And it is genuinely the PROCESSED surface, not the raw frame: the
            # z-scored, direction-signed column differs from frame[name] on the
            # finite cross-section (the bug this whole helper exists to kill).
            raw = frame[name].to_numpy(dtype=float)
            got = x[name].to_numpy(dtype=float)
            both = np.isfinite(raw) & np.isfinite(got)
            assert both.sum() > 100
            assert not np.allclose(got[both], raw[both])

    def test_context_name_resolves_to_raw_frame_column(self, env: Env) -> None:
        """A ``direction == 0`` context name is fed RAW from the engine frame."""
        frame, _mask, zs = _panel(env, SPAN_START, SPAN_END)
        assert CONTEXT not in zs  # not a directional alpha => not in the z panel
        x = assemble_meta_features(frame, zs, FEATURE_NAMES)
        pd.testing.assert_series_equal(
            x[CONTEXT], frame[CONTEXT].astype("float64"), check_names=False
        )

    def test_columns_are_exactly_feature_names_in_order(self, env: Env) -> None:
        frame, _mask, zs = _panel(env, SPAN_START, SPAN_END)
        # Reversed order to prove the output follows feature_names, not zs/frame order.
        names = tuple(reversed(FEATURE_NAMES))
        x = assemble_meta_features(frame, zs, names)
        assert tuple(x.columns) == names

    def test_unknown_name_is_keyerror(self, env: Env) -> None:
        frame, _mask, zs = _panel(env, SPAN_START, SPAN_END)
        with pytest.raises(KeyError, match="neither the processed z panel nor"):
            assemble_meta_features(frame, zs, (*FEATURE_NAMES, "not_a_feature"))

    def test_sigma_context_column_also_routes_raw(self, env: Env) -> None:
        """The service's own ``sigma`` helper column (direction==0, in the frame but
        not in zs) routes RAW too — a model may list it as risk context."""
        frame, _mask, zs = _panel(env, SPAN_START, SPAN_END)
        assert SIGMA_COLUMN in frame.columns and SIGMA_COLUMN not in zs
        x = assemble_meta_features(frame, zs, (DIRECTIONAL[0], SIGMA_COLUMN))
        pd.testing.assert_series_equal(
            x[SIGMA_COLUMN], frame[SIGMA_COLUMN].astype("float64"), check_names=False
        )


class TestTrainServeParity:
    def test_overlap_surface_is_identical(self, env: Env) -> None:
        """THE parity invariant: the X assembled over a TRAIN window and over an
        overlapping SERVE window are byte-identical on the overlap — because both
        route the same engine surface through the same helper."""
        train_frame, _tm, train_zs = _panel(env, TRAIN_START, TRAIN_END)
        serve_frame, _sm, serve_zs = _panel(env, SERVE_START, SERVE_END)
        x_train = assemble_meta_features(train_frame, train_zs, FEATURE_NAMES)
        x_serve = assemble_meta_features(serve_frame, serve_zs, FEATURE_NAMES)

        ts = x_train.index.get_level_values("ts_open")
        in_overlap_train = (ts >= OVERLAP_START) & (ts < OVERLAP_END)
        ts_s = x_serve.index.get_level_values("ts_open")
        in_overlap_serve = (ts_s >= OVERLAP_START) & (ts_s < OVERLAP_END)

        ov_train = x_train.loc[in_overlap_train].sort_index()
        ov_serve = x_serve.loc[in_overlap_serve].sort_index()
        assert len(ov_train) > 1000  # a real panel, not a sliver
        assert ov_train.index.equals(ov_serve.index)
        # Finite-window alphas + raw context: identical to the bit on the overlap.
        pd.testing.assert_frame_equal(ov_train, ov_serve, check_exact=True)

    def test_one_helper_both_paths_same_dtype_and_index(self, env: Env) -> None:
        """Train and serve hand the model the same dtype/index contract (float64 on
        the (ts_open, instrument_id) MultiIndex) so realignment is positional-safe."""
        frame, _mask, zs = _panel(env, SPAN_START, SPAN_END)
        x = assemble_meta_features(frame, zs, FEATURE_NAMES)
        assert list(x.index.names) == ["ts_open", "instrument_id"]
        assert (x.dtypes == np.float64).all()
        assert x.index.equals(frame.index)
