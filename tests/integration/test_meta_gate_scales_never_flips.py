"""The meta-gate scales, never flips — D1 / CRITIQUE_leakage #1 (``12_FINAL.md`` test 2).

This is the integration counterpart to the unit ``test_gating.py`` D1 cases: it
drives a REAL :class:`~alphaforge.signals.service.SignalService.compute_research`
frame off a synthetic ``tmp_path`` lake — a genuine mixed-sign ``alpha_blend``
cross-section with the engine's own ``mu_ann`` — through the EXACT per-leg gating
call the walk-forward runner makes (:func:`~alphaforge.signals.gating.gate_signal_frame`,
``analytics/walkforward.py::_run_leg_set``). A stub :class:`MetaModel` returns
MIXED, NON-CONSTANT ``|size|`` keyed off a planted feature column, so the gate is
exercised on a real signal surface (not a hand-planted Series) with a genuinely
varying magnitude — the case that hid behind the all-ones identity until the
re-z-score body in the original ``12_integration.md`` was killed.

Assertions (``12_FINAL.md`` test 2):

(i)   ``sign(mu_ann_gated) == sign(mu_ann)`` for EVERY finite row — the gate scales
      magnitude only and NEVER flips a name's direction (the sign-flip the old
      re-z-score after gating produced; ``alpha_blend`` stays the UNGATED Ã, so the
      gate's whole effect lives in ``mu_ann``, sign-tracking ``mu_ann`` ⇒ ``Ã``).
(ii)  ``|size| ≡ 1`` reproduces the ungated ``mu_ann`` EXACTLY (the OFF-equivalent
      gate is a byte-for-byte multiply by 1.0, D7).
(iii) the gated ``mu_ann`` still clears :func:`check_mu_ann_contract` /
      ``|mu_ann| < 3.0`` (the μ-contract, rule 5: ``|size| ∈ [0,1]`` and
      ``G ∈ (0,1]`` only SHRINK, so a contract-clean blend stays clean).
(iv)  :func:`assemble_meta_features` returns the PROCESSED, direction-signed ``zs``
      column for a directional-alpha name and the RAW engine ``frame`` column for a
      ``direction == 0`` context name (the train/serve parity surface, D4 / leakage
      #15) — a directional name's served column equals its ``zs`` value, NOT
      ``frame[name]``.

Offline, ``tmp_path`` lake only, deterministic (seeded rng); a few instruments and
a short window so the whole module runs well under the 90s budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
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
from alphaforge.portfolio.optimizer import MU_ANN_ABS_MAX, check_mu_ann_contract
from alphaforge.signals.blending import ALPHA_BLEND_COLUMN
from alphaforge.signals.features_serve import assemble_meta_features
from alphaforge.signals.gating import IdentityRegime, gate_signal_frame
from alphaforge.signals.service import SignalService
from alphaforge.signals.sizing import MU_ANN_COLUMN

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from alphaforge.features.context import FeatureContext

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z, a clean UTC-day boundary
N_BARS = 900
H = 72  # == SignalsCfg().horizon_bars
MEMBERS = tuple(f"BINANCE:PERP:{b}USDT" for b in ("BTC", "ETH", "SOL", "ADA", "DOGE", "LTC"))
START = T0 + 240 * HOUR
END = T0 + N_BARS * HOUR
_CONTEXT_COL = "btc_corr_ctx"  # a synthetic direction==0 context column (assertion iv)


def _xret_fn(ctx: FeatureContext, spec: FeatureSpec) -> pd.Series:
    """w-bar log return on the complete grid (a tiny finite-window CS alpha)."""
    close = ctx.panel("close")
    window = int(spec.params["window"])
    out: pd.DataFrame = np.log(close / close.shift(window))  # type: ignore[assignment]
    return long_series(out, name=spec.name)


def _registry() -> FeatureRegistry:
    """Two directional CS momentum alphas → a genuinely mixed-sign blend."""
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
            direction=-1,
            cross_sectional=True,
            lookback_bars=window + 1,
            params={"window": window},
            fn=_xret_fn,
        )

    reg.register(alpha_fast)
    reg.register(alpha_slow)
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
        opens.extend(float(v) for v in close[:-1])
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
        listed_ts=T0 - 365 * DAY,
        delisted_ts=None,
    )


class _StubMeta:
    """A stub :class:`~alphaforge.ml.model.MetaModel` with mixed, NON-constant ``|size|``.

    ``bet_size`` returns ``side · magnitude`` where ``magnitude`` is read from a column
    of the assembled features and clipped to ``[0, 1]``: sign is ALWAYS ``side`` (never
    flips), magnitude genuinely varies across the cross-section. ``feature_names`` is the
    pinned column order the gate assembles X over; when set to ``()`` the gate is a no-op
    identity (``|size| ≡ 1``).
    """

    def __init__(self, magnitude: pd.Series, feature_names: tuple[str, ...]) -> None:
        self._magnitude = magnitude
        self._feature_names = feature_names

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def model_id(self) -> str:
        return "stub_meta_integration"

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:  # pragma: no cover - unused
        return np.full(len(X.index), 0.7, dtype=np.float64)

    def bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series:
        mag = self._magnitude.reindex(x.index).to_numpy(dtype=float)
        mag = np.clip(mag, 0.0, 1.0)
        s = np.sign(side.reindex(x.index).to_numpy(dtype=float))
        out = s * mag
        out[~np.isfinite(out)] = 0.0
        return pd.Series(out, index=x.index, name="bet_size", dtype=float)

    def save(self, path: Path) -> None:  # pragma: no cover - seam completeness only
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path) -> _StubMeta:  # pragma: no cover - seam completeness only
        raise NotImplementedError


class _Env:
    __slots__ = ("frame", "mask", "research", "service", "zs")

    def __init__(
        self,
        research: pd.DataFrame,
        service: SignalService,
        frame: pd.DataFrame,
        mask: pd.Series,
        zs: dict[str, pd.Series],
    ) -> None:
        self.research = research
        self.service = service
        self.frame = frame
        self.mask = mask
        self.zs = zs


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Env]:
    tmp = tmp_path_factory.mktemp("meta_gate_never_flips")
    paths = LakePaths(tmp / "lake")
    closes = {iid: _closes(11 + k, N_BARS, 50.0 * (k + 1)) for k, iid in enumerate(MEMBERS)}
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

    store = InstrumentStore(tmp / "ops.sqlite")
    for iid in MEMBERS:
        store.upsert(_instrument(iid), as_of=T0 - 365 * DAY)

    reader = PITDataReader(paths)
    service = SignalService(
        FeatureEngine(reader, store, universe), universe, _registry(), SignalsCfg()
    )
    research = service.compute_research(START, END)
    # The engine's processed decision-time surface for assertion (iv): _panel returns
    # the RAW engine frame, the PIT mask, and the PROCESSED, direction-signed zs panel —
    # exactly what assemble_meta_features routes train and serve through (D4).
    frame, mask, zs = service._panel(START, END)
    yield _Env(research, service, frame, mask, dict(zs))
    store.close()


def _gate(research: pd.DataFrame, magnitude: pd.Series, names: tuple[str, ...]) -> pd.DataFrame:
    """Drive the REAL signal frame through the runner's exact per-leg gating call.

    Builds the meta-feature surface over ``names`` from the signal frame (the runner's
    serve-time ``_assemble_leg_features`` — the v1 gate features are processed engine
    columns already present in the frame), then applies BOTH gates via
    ``gate_signal_frame`` with an IdentityRegime (all-1.0 ``G`` — the meta gate is the one
    under test here; the regime gate is exercised in its own dedicated test).
    """
    feature_frame = assemble_meta_features(research, {}, names) if names else None
    meta = _StubMeta(magnitude, names)
    days = pd.Index(
        sorted({(int(t) // DAY) * DAY for t in research.index.get_level_values("ts_open")}),
        dtype="int64",
        name="ts_open",
    )
    g_series = IdentityRegime().gross_multiplier_series(pd.DataFrame(index=days), lag_days=1)
    sigma = pd.Series(0.5, index=research.index)
    return gate_signal_frame(research, feature_frame, meta, g_series, sigma)


def _finite_blend_rows(research: pd.DataFrame) -> npt.NDArray[np.bool_]:
    """Boolean mask of rows whose ungated blend Ã is finite (the tradable cross-section)."""
    finite: npt.NDArray[np.bool_] = np.isfinite(research[ALPHA_BLEND_COLUMN].to_numpy(dtype=float))
    return finite


def test_synthetic_frame_has_a_mixed_sign_tradable_cross_section(env: _Env) -> None:
    """Guard against a vacuous proof: the real frame must carry BOTH signs of Ã.

    If every ``alpha_blend`` were one sign (or all NaN) the never-flip assertion would
    pass trivially — this pins that the synthetic world produces a genuine mixed-sign
    blend and finite ``mu_ann`` to gate.
    """
    finite = _finite_blend_rows(env.research)
    assert int(finite.sum()) >= 20, "too few finite blend rows to exercise the gate"
    a = env.research[ALPHA_BLEND_COLUMN].to_numpy(dtype=float)[finite]
    assert (a > 0).any() and (a < 0).any(), "blend is single-signed — the proof is vacuous"
    mu = env.research[MU_ANN_COLUMN].to_numpy(dtype=float)
    assert np.isfinite(mu).any(), "no finite mu_ann to gate"


def test_meta_gate_scales_mu_ann_never_flips_its_sign(env: _Env) -> None:
    """(i) ``sign(mu_ann_gated) == sign(mu_ann)`` for every finite row (D1 / #1).

    A genuinely mixed, non-constant ``|size|`` — read off the row's own ``alpha_fast`` z,
    rescaled into ``[0, 1]`` — over the real mixed-sign cross-section. The gate scales
    magnitude only; ``alpha_blend`` stays the UNGATED Ã, so ``mu_ann_gated`` is
    ``mu_blend · |size| · 1`` and its sign can only equal ``sign(mu_blend)`` or be 0.
    """
    # A varying magnitude in [0, 1] planted off a real, mixed-sign processed z column.
    z = env.zs["alpha_fast"].reindex(env.research.index).to_numpy(dtype=float)
    mag = np.clip(np.abs(np.tanh(z)), 0.0, 1.0)
    mag[~np.isfinite(mag)] = 0.0
    magnitude = pd.Series(mag, index=env.research.index, dtype=float)

    gated = _gate(env.research, magnitude, (ALPHA_BLEND_COLUMN,))

    mu = env.research[MU_ANN_COLUMN].to_numpy(dtype=float)
    mug = gated[MU_ANN_COLUMN].to_numpy(dtype=float)
    finite = np.isfinite(mu) & np.isfinite(mug)
    assert int(finite.sum()) > 0
    flipped = finite & (np.sign(mug) == -np.sign(mu)) & (mug != 0.0)
    assert not flipped.any(), (
        f"meta-gate flipped mu_ann's sign at {int(flipped.sum())} of {int(finite.sum())} rows"
    )
    # alpha_blend column is the UNGATED Ã (the audit/IC quantity) — gate effect lives in mu.
    pd.testing.assert_series_equal(gated[ALPHA_BLEND_COLUMN], env.research[ALPHA_BLEND_COLUMN])
    # The gated mu is exactly mu_blend · |size| where both finite (magnitude-only).
    expected = mu * magnitude.to_numpy(dtype=float)
    np.testing.assert_allclose(mug[finite], expected[finite], rtol=0, atol=1e-12)


def test_unit_size_reproduces_ungated_mu_ann_exactly(env: _Env) -> None:
    """(ii) ``|size| ≡ 1`` reproduces the ungated ``mu_ann`` byte-for-byte (D1 part ii / D7)."""
    magnitude = pd.Series(1.0, index=env.research.index, dtype=float)
    gated = _gate(env.research, magnitude, (ALPHA_BLEND_COLUMN,))
    # Every |size| == 1 and an all-1.0 G ⇒ the gated frame equals the ungated frame.
    pd.testing.assert_frame_equal(gated, env.research)


def test_gated_mu_ann_clears_the_mu_contract(env: _Env) -> None:
    """(iii) The gated ``mu_ann`` still clears ``check_mu_ann_contract`` / ``|mu| < 3`` (D1 iii)."""
    # A worst-case magnitude (uniform in [0, 1]) — gating can only SHRINK |mu_ann|, so a
    # contract-clean blend (the engine's own mu, pinned by test_mu_contract) stays clean.
    rng = np.random.default_rng(7)
    magnitude = pd.Series(
        rng.uniform(0.0, 1.0, size=len(env.research.index)), index=env.research.index, dtype=float
    )
    gated = _gate(env.research, magnitude, (ALPHA_BLEND_COLUMN,))

    mu = env.research[MU_ANN_COLUMN].to_numpy(dtype=float)
    mug = gated[MU_ANN_COLUMN].to_numpy(dtype=float)
    finite_g = mug[np.isfinite(mug)]
    assert finite_g.size > 0
    # The optimizer's own guard accepts the gated vector unchanged.
    check_mu_ann_contract(finite_g)
    assert float(np.abs(finite_g).max()) < MU_ANN_ABS_MAX
    # Row-wise shrinkage: |gated| <= |blend| everywhere (|size| in [0,1], G == 1).
    finite = np.isfinite(mu) & np.isfinite(mug)
    assert (np.abs(mug)[finite] <= np.abs(mu)[finite] + 1e-12).all()


def test_assemble_meta_features_directional_uses_zs_context_uses_raw_frame(env: _Env) -> None:
    """(iv) directional name → processed ``zs``; context name → raw ``frame`` (D4 / #15).

    The runner's per-leg X is assembled by the ONE shared train/serve surface
    :func:`assemble_meta_features`. A directional-alpha name present in the service's
    ``zs`` panel resolves to the PROCESSED, direction-signed z column — NOT the raw
    engine ``frame[name]`` (the train/serve skew the original spec's
    ``x = frame[feature_names]`` would have introduced); a ``direction == 0`` context
    name (absent from ``zs``) resolves to the RAW frame column.
    """
    # Plant a synthetic direction==0 context column on the engine frame (a name absent
    # from the zs panel) so the helper's raw-frame branch is exercised alongside the
    # directional zs branch.
    frame = env.frame.copy()
    rng = np.random.default_rng(3)
    frame[_CONTEXT_COL] = rng.normal(0.0, 1.0, size=len(frame.index))

    feature_names = ("alpha_fast", _CONTEXT_COL)
    x = assemble_meta_features(frame, env.zs, feature_names)

    # Column order is EXACTLY feature_names.
    assert list(x.columns) == list(feature_names)
    # Directional name -> the PROCESSED, direction-signed zs value (aligned to the index).
    expected_dir = env.zs["alpha_fast"].reindex(frame.index).to_numpy(dtype=float)
    got_dir = x["alpha_fast"].to_numpy(dtype=float)
    np.testing.assert_array_equal(np.isnan(got_dir), np.isnan(expected_dir))
    finite = np.isfinite(expected_dir)
    np.testing.assert_allclose(got_dir[finite], expected_dir[finite], rtol=0, atol=0)
    # And it is NOT the raw engine value for that alpha (proves processed, not raw).
    raw_dir = frame["alpha_fast"].reindex(frame.index).to_numpy(dtype=float)
    both = np.isfinite(got_dir) & np.isfinite(raw_dir)
    assert both.any()
    assert not np.allclose(got_dir[both], raw_dir[both]), (
        "directional feature resolved to the RAW frame value — train/serve skew (leakage #15)"
    )
    # Context name -> the RAW frame value, byte-for-byte.
    np.testing.assert_array_equal(
        x[_CONTEXT_COL].to_numpy(dtype=float), frame[_CONTEXT_COL].to_numpy(dtype=float)
    )
