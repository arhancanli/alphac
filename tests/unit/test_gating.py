"""Unit tests for :mod:`alphaforge.signals.gating` (Phase 12; ``12_FINAL.md``).

The gate adapters are pure, deterministic, sign-safe functions. These tests pin
the load-bearing decisions D1/D2/D4/D7 on synthetic, hand-planted panels (no lake,
no I/O):

* **D7 — OFF == identity, byte-for-byte.** Under :class:`IdentityMeta`
  (``|size| ≡ 1``) and an all-ones ``g_series`` (:class:`IdentityRegime`), every
  function returns its input unchanged: ``apply_meta_gate`` reproduces ``Ã``,
  ``apply_regime_gate`` reproduces ``mu_ann``, and the combined
  ``gate_signal_frame`` returns a frame EQUAL to its input (both ``alpha_blend``
  and ``mu_ann``). This is the guarantee the shipped blend-only run is not
  perturbed by a single ULP.
* **D1 — magnitude-only meta-gate, NEVER flips (CRITIQUE_leakage #1).** Feeding a
  stub :class:`MetaModel` that returns mixed, NON-constant ``|size|`` over a
  cross-section with mixed ``Ã`` signs: every finite row of the gated ``F̃`` has
  ``sign(F̃) == sign(Ã)`` or ``0`` — the exact sign-flip the old re-z-score body
  produced. ``|size| ≡ 1`` reproduces ``Ã`` exactly; the gated ``mu_ann`` still
  clears the optimizer's :func:`check_mu_ann_contract` / ``|mu_ann| < 3.0`` rule.
* **D4 — train/serve feature parity (CRITIQUE_leakage #15).**
  ``assemble_meta_features`` returns the PROCESSED, direction-signed ``zs`` column
  for a directional-alpha name and the RAW engine ``frame`` column for a
  ``direction==0`` context name, in EXACTLY ``feature_names`` order; a name absent
  from both is a loud ``KeyError`` (no silent positional drift); NaN-preserving.
* **D2 — single backward merge_asof, no double lag (CRITIQUE_leakage #4).** The
  daily ``G`` (already lagged once by the producer) broadcasts to hourly rows via
  ONE backward :func:`pandas.merge_asof` keyed on the day-``D`` ``ts_open``: every
  hour of day ``D`` receives day ``D``'s gate (``allow_exact_matches=True`` at the
  day boundary), cold-start rows get ``G = 1.0`` (never NaN), and
  ``0 < G ≤ 1 ⇒ |mu_ann_gated| ≤ |mu_ann|`` everywhere.

Offline, pure pandas/numpy; no lake, no network.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alphaforge.portfolio.optimizer import MU_ANN_ABS_MAX, check_mu_ann_contract
from alphaforge.signals.blending import ALPHA_BLEND_COLUMN
from alphaforge.signals.gating import (
    REGIME_GATE_COLUMN,
    IdentityMeta,
    IdentityRegime,
    apply_meta_gate,
    apply_regime_gate,
    assemble_meta_features,
    gate_signal_frame,
)
from alphaforge.signals.sizing import MU_ANN_COLUMN

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z, a clean UTC-day boundary

# ----------------------------------------------------------------- panel fixtures


def _panel_index(ts: list[int], instruments: list[str]) -> pd.MultiIndex:
    """A ``(ts_open, instrument_id)`` MultiIndex — the engine panel shape."""
    return pd.MultiIndex.from_product([ts, instruments], names=["ts_open", "instrument_id"])


def _hourly_index(n_hours: int, instruments: list[str], *, start: int = T0) -> pd.MultiIndex:
    ts = [start + h * HOUR for h in range(n_hours)]
    return _panel_index(ts, instruments)


class _StubMeta:
    """A stub :class:`MetaModel` whose ``|size|`` is a fixed, NON-constant map.

    ``bet_size`` returns ``side · magnitude`` with ``magnitude`` read from a column
    of the assembled features (so we can plant per-row magnitudes), clipped to
    ``[0, 1]`` and never flipping ``side``. This exercises the D1 sign-safety on a
    mixed-sign cross-section with a genuinely varying ``|size|`` — the case that
    hid behind the all-ones identity.
    """

    def __init__(self, magnitude_col: str, feature_names: tuple[str, ...]) -> None:
        self._col = magnitude_col
        self._feature_names = feature_names

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def model_id(self) -> str:
        return "stub_meta"

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:  # pragma: no cover - unused
        return np.full(len(X.index), 0.7, dtype=np.float64)

    def bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series:
        magnitude = x[self._col].reindex(x.index).to_numpy(dtype=float)
        magnitude = np.clip(magnitude, 0.0, 1.0)
        s = np.sign(side.reindex(x.index).to_numpy(dtype=float))
        out = s * magnitude
        out[~np.isfinite(out)] = 0.0
        return pd.Series(out, index=x.index, name="bet_size", dtype=float)

    def save(self, path: Path) -> None:  # pragma: no cover - seam completeness only
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path) -> _StubMeta:  # pragma: no cover - seam completeness only
        raise NotImplementedError


# ============================================================ D7 — OFF == identity


def test_apply_meta_gate_identity_reproduces_a_tilde() -> None:
    """IdentityMeta with no features (``x=None``) returns ``Ã`` byte-for-byte (D7)."""
    idx = _hourly_index(4, ["BTC", "ETH"])
    a_tilde = pd.Series(
        [1.5, -0.5, np.nan, 0.3, -2.0, 0.0, 0.9, -1.1],
        index=idx,
        name=ALPHA_BLEND_COLUMN,
        dtype=float,
    )
    mask = pd.Series(True, index=idx)
    out = apply_meta_gate(a_tilde, None, IdentityMeta(), mask)
    pd.testing.assert_series_equal(out, a_tilde)


def test_apply_meta_gate_identity_with_features_reproduces_a_tilde() -> None:
    """IdentityMeta WITH an assembled X (``|size| ≡ 1``) still reproduces ``Ã`` (D7)."""
    idx = _hourly_index(3, ["BTC", "ETH"])
    a_tilde = pd.Series(
        [1.0, -2.0, 0.4, -0.7, np.nan, 0.6], index=idx, name=ALPHA_BLEND_COLUMN, dtype=float
    )
    x = pd.DataFrame({"mom": np.linspace(-1.0, 1.0, len(idx))}, index=idx)
    mask = pd.Series(True, index=idx)
    out = apply_meta_gate(a_tilde, x, IdentityMeta(feature_names=("mom",)), mask)
    # |size| ≡ 1 for every finite-side row → F̃ == Ã (NaN rows preserved as NaN).
    np.testing.assert_array_equal(out.to_numpy(dtype=float), a_tilde.to_numpy(dtype=float))


def test_apply_regime_gate_identity_reproduces_mu_ann() -> None:
    """An all-ones daily ``g_series`` (IdentityRegime) returns ``mu_ann`` exactly (D7)."""
    idx = _hourly_index(48, ["BTC", "ETH"])  # two UTC days of hourly bars
    rng = np.random.default_rng(42)
    mu_ann = pd.Series(
        rng.normal(0.0, 0.2, size=len(idx)), index=idx, name=MU_ANN_COLUMN, dtype=float
    )
    days = pd.Index([T0, T0 + DAY], name="ts_open")
    g_series = IdentityRegime().gross_multiplier_series(pd.DataFrame(index=days), lag_days=1)
    out = apply_regime_gate(mu_ann, g_series)
    pd.testing.assert_series_equal(out, mu_ann)


def test_gate_signal_frame_double_identity_is_byte_for_byte() -> None:
    """The headline D7 guarantee: IdentityMeta + IdentityRegime ⇒ frame UNCHANGED."""
    idx = _hourly_index(48, ["BTC", "ETH", "SOL"])
    rng = np.random.default_rng(7)
    signal_frame = pd.DataFrame(
        {
            ALPHA_BLEND_COLUMN: rng.normal(0.0, 1.0, size=len(idx)),
            MU_ANN_COLUMN: rng.normal(0.0, 0.2, size=len(idx)),
        },
        index=idx,
    )
    # Plant some NaN to prove the gate is NaN-preserving on both columns.
    signal_frame.iloc[3, 0] = np.nan
    signal_frame.iloc[3, 1] = np.nan
    sigma = pd.Series(0.5, index=idx)
    days = pd.Index([T0, T0 + DAY], name="ts_open")
    g_series = IdentityRegime().gross_multiplier_series(pd.DataFrame(index=days), lag_days=1)
    out = gate_signal_frame(
        signal_frame,
        feature_frame=None,  # identity meta
        meta=IdentityMeta(),
        g_series=g_series,
        sigma=sigma,
    )
    pd.testing.assert_frame_equal(out, signal_frame)


# ====================================================== D1 — scales, never flips


def test_meta_gate_preserves_sign_never_flips() -> None:
    """Mixed-sign ``Ã`` with non-constant ``|size|`` ⇒ sign preserved or 0 (D1 / #1).

    The bug that hid behind the identity case: a re-z-score after gating subtracts
    a non-zero cross-sectional mean and can flip a small-``|size|`` positive name
    below the mean to negative. The magnitude-only gate cannot.
    """
    idx = _hourly_index(2, ["A", "B", "C", "D"])  # 8 rows, mixed signs per cross-section
    a_tilde = pd.Series(
        [2.0, -1.5, 0.3, -0.8, 1.1, -2.2, 0.05, -0.05],
        index=idx,
        name=ALPHA_BLEND_COLUMN,
        dtype=float,
    )
    # Non-constant magnitudes in [0, 1], including a 0 (floor) and a small value.
    magnitude = pd.Series([0.9, 0.1, 0.0, 0.5, 0.05, 0.8, 0.3, 0.6], index=idx, dtype=float)
    x = pd.DataFrame({"mag": magnitude}, index=idx)
    meta = _StubMeta("mag", ("mag",))
    mask = pd.Series(True, index=idx)

    f_tilde = apply_meta_gate(a_tilde, x, meta, mask)

    a_arr = a_tilde.to_numpy(dtype=float)
    f_arr = f_tilde.to_numpy(dtype=float)
    finite = np.isfinite(a_arr) & np.isfinite(f_arr)
    # sign(F̃) == sign(Ã) OR F̃ == 0 — NEVER the opposite sign.
    flipped = finite & (np.sign(f_arr) == -np.sign(a_arr)) & (f_arr != 0.0)
    assert not flipped.any(), f"meta-gate flipped a sign at rows {np.flatnonzero(flipped)}"
    # The product is exactly Ã·|size| (magnitude-only).
    np.testing.assert_allclose(f_arr[finite], (a_arr * magnitude.to_numpy())[finite])
    # The floored (|size|==0) name is exactly 0, not a tiny negative.
    assert f_tilde.iloc[2] == 0.0


def test_meta_gate_unit_size_reproduces_mu_ann() -> None:
    """``|size| ≡ 1`` reproduces the ungated ``mu_ann`` exactly (D1 part ii)."""
    idx = _hourly_index(3, ["BTC", "ETH"])
    a_tilde = pd.Series(
        [1.2, -0.6, 0.4, -1.0, 0.7, -0.2], index=idx, name=ALPHA_BLEND_COLUMN, dtype=float
    )
    magnitude = pd.Series(1.0, index=idx)  # every |size| == 1
    x = pd.DataFrame({"mag": magnitude}, index=idx)
    meta = _StubMeta("mag", ("mag",))
    mask = pd.Series(True, index=idx)
    f_tilde = apply_meta_gate(a_tilde, x, meta, mask)
    np.testing.assert_allclose(f_tilde.to_numpy(dtype=float), a_tilde.to_numpy(dtype=float))


def test_gated_mu_ann_clears_contract() -> None:
    """The gated ``mu_ann`` still clears ``check_mu_ann_contract`` / rule 5 (D1 iii).

    ``|size| ∈ [0, 1]`` and ``G ∈ (0, 1]`` only SHRINK, so a contract-clean
    baseline stays clean — the gate can only make the ``|mu_ann| < 3.0`` tripwire
    safer.
    """
    idx = _hourly_index(4, ["A", "B", "C"])
    rng = np.random.default_rng(11)
    # A contract-clean baseline (median |mu_ann| well under MU_ANN_ABS_MAX).
    mu_blend = pd.Series(
        rng.normal(0.0, 0.2, size=len(idx)), index=idx, name=MU_ANN_COLUMN, dtype=float
    )
    check_mu_ann_contract(mu_blend.to_numpy(dtype=float))  # baseline is clean

    magnitude = pd.Series(rng.uniform(0.0, 1.0, size=len(idx)), index=idx, dtype=float)
    mu_gated = mu_blend * magnitude
    check_mu_ann_contract(mu_gated.to_numpy(dtype=float))  # must not raise
    # And shrinkage holds row-wise.
    finite = np.isfinite(mu_blend.to_numpy())
    blend_abs = np.abs(mu_blend.to_numpy())[finite]
    gated_abs = np.abs(mu_gated.to_numpy())[finite]
    assert (gated_abs <= blend_abs + 1e-12).all()
    assert float(np.nanmax(np.abs(mu_gated.to_numpy()))) < MU_ANN_ABS_MAX


# =================================================== D4 — train/serve feature parity


def test_assemble_meta_features_directional_uses_zs_context_uses_frame() -> None:
    """Directional names resolve to processed ``zs``; context names to raw ``frame`` (D4)."""
    idx = _hourly_index(2, ["BTC", "ETH"])
    # Raw engine frame: a directional alpha's RAW value AND a context column.
    frame = pd.DataFrame(
        {
            "mom_10d": [10.0, 20.0, 30.0, 40.0],  # raw directional value (must NOT be used)
            "btc_corr": [0.1, 0.2, 0.3, 0.4],  # direction==0 context (raw, MUST be used)
        },
        index=idx,
    )
    # The PROCESSED, direction-signed z column for the directional alpha.
    zs = {"mom_10d": pd.Series([-1.0, 0.5, 1.5, -0.5], index=idx, dtype=float)}
    feature_names = ("mom_10d", "btc_corr")

    x = assemble_meta_features(frame, zs, feature_names)

    # Column order is EXACTLY feature_names.
    assert list(x.columns) == list(feature_names)
    # Directional name -> the PROCESSED zs value, NOT frame["mom_10d"].
    np.testing.assert_array_equal(x["mom_10d"].to_numpy(), zs["mom_10d"].to_numpy())
    assert not np.array_equal(x["mom_10d"].to_numpy(), frame["mom_10d"].to_numpy())
    # Context name -> the RAW frame value.
    np.testing.assert_array_equal(x["btc_corr"].to_numpy(), frame["btc_corr"].to_numpy())
    # Same index as the engine frame.
    pd.testing.assert_index_equal(x.index, frame.index)


def test_assemble_meta_features_unknown_name_raises_keyerror() -> None:
    """A name absent from BOTH ``zs`` and ``frame`` fails loud (no positional drift)."""
    idx = _hourly_index(1, ["BTC", "ETH"])
    frame = pd.DataFrame({"btc_corr": [0.1, 0.2]}, index=idx)
    zs = {"mom_10d": pd.Series([0.5, -0.5], index=idx, dtype=float)}
    with pytest.raises(KeyError, match="typo_feature"):
        assemble_meta_features(frame, zs, ("mom_10d", "typo_feature"))


def test_assemble_meta_features_empty_is_index_only() -> None:
    """An empty ``feature_names`` yields an index-only frame (the OFF short-circuit)."""
    idx = _hourly_index(2, ["BTC"])
    frame = pd.DataFrame({"btc_corr": [0.1, 0.2]}, index=idx)
    x = assemble_meta_features(frame, {}, ())
    assert list(x.columns) == []
    pd.testing.assert_index_equal(x.index, frame.index)


def test_assemble_meta_features_is_nan_preserving() -> None:
    """A NaN in the processed ``zs`` (a blend-dropped name) survives into X (D4)."""
    idx = _hourly_index(2, ["BTC", "ETH"])
    frame = pd.DataFrame({"ctx": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    zs = {"mom": pd.Series([0.5, np.nan, -0.5, 1.0], index=idx, dtype=float)}
    x = assemble_meta_features(frame, zs, ("mom", "ctx"))
    assert bool(np.isnan(x["mom"].to_numpy()[1]))


def test_serve_surface_matches_training_surface_parity() -> None:
    """One helper, two callers (train + serve) ⇒ byte-identical X (the parity pin)."""
    idx = _hourly_index(3, ["BTC", "ETH"])
    frame = pd.DataFrame({"mom": [9.0, 8.0, 7.0, 6.0, 5.0, 4.0], "ctx": np.arange(6.0)}, index=idx)
    zs = {"mom": pd.Series(np.linspace(-1.0, 1.0, 6), index=idx, dtype=float)}
    names = ("mom", "ctx")
    x_train = assemble_meta_features(frame, zs, names)
    x_serve = assemble_meta_features(frame, zs, names)
    pd.testing.assert_frame_equal(x_train, x_serve)


# ========================================================= D2 — regime broadcast


class _FlipRegime:
    """A stub :class:`RegimeGate` whose daily ``G`` flips across two days.

    Day-``D`` ``ts_open`` keys carry the ALREADY-lagged value (the producer's
    contract). We plant distinct day values so a same-day vs day-``D-1`` mistake
    would be visible.
    """

    def __init__(self, day_to_g: dict[int, float]) -> None:
        self._day_to_g = day_to_g

    def gross_multiplier_series(self, obs: pd.DataFrame, *, lag_days: int = 1) -> pd.Series:
        del obs, lag_days  # the planted map IS the already-lagged series
        days = sorted(self._day_to_g)
        return pd.Series(
            [self._day_to_g[d] for d in days],
            index=pd.Index(days, name="ts_open"),
            name=REGIME_GATE_COLUMN,
            dtype=float,
        )


def test_regime_gate_broadcasts_day_value_to_every_hour() -> None:
    """Every hour of day ``D`` gets day ``D``'s gate; boundary hour matches (D2)."""
    idx = _hourly_index(48, ["BTC", "ETH"])  # 2 days, 24h each, 2 instruments
    mu_ann = pd.Series(1.0, index=idx, name=MU_ANN_COLUMN, dtype=float)
    g_series = _FlipRegime({T0: 0.4, T0 + DAY: 0.9}).gross_multiplier_series(
        pd.DataFrame(index=pd.Index([T0, T0 + DAY]))
    )
    out = apply_regime_gate(mu_ann, g_series)

    ts = out.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    day0 = ts < T0 + DAY
    day1 = ts >= T0 + DAY
    # Day 0 hours (incl. the exact day-open boundary) all get G=0.4.
    np.testing.assert_allclose(out.to_numpy()[day0], 0.4)
    # Day 1 hours all get G=0.9 (the next day's already-lagged value).
    np.testing.assert_allclose(out.to_numpy()[day1], 0.9)
    # The exact day-1 open boundary matches (allow_exact_matches=True).
    boundary = out[(slice(None), "BTC")].loc[T0 + DAY]
    assert boundary == pytest.approx(0.9)


def test_regime_gate_cold_start_is_one_never_nan() -> None:
    """Hours BEFORE the first available gate day get ``G = 1.0`` (never NaN) (D2)."""
    idx = _hourly_index(48, ["BTC"])
    mu_ann = pd.Series(0.5, index=idx, name=MU_ANN_COLUMN, dtype=float)
    # The gate only starts on day 1 — day 0 hours have no day-D ≤ hour gate.
    g_series = _FlipRegime({T0 + DAY: 0.6}).gross_multiplier_series(
        pd.DataFrame(index=pd.Index([T0 + DAY]))
    )
    out = apply_regime_gate(mu_ann, g_series)
    assert not bool(out.isna().any())
    ts = out.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    cold = ts < T0 + DAY
    # Cold start: mu_ann untouched (multiplied by 1.0).
    np.testing.assert_allclose(out.to_numpy()[cold], 0.5)
    np.testing.assert_allclose(out.to_numpy()[~cold], 0.5 * 0.6)


def test_regime_gate_single_merge_asof_no_double_lag() -> None:
    """The broadcast is a SINGLE backward asof — no extra shift (D2 / #4).

    If a second lag were applied, day ``D``'s hours would receive day ``D-1``'s
    value. We assert the planted day-``D`` value reaches day ``D``'s hours exactly,
    which a double-lag would break.
    """
    idx = _hourly_index(72, ["BTC"])  # 3 days
    mu_ann = pd.Series(2.0, index=idx, name=MU_ANN_COLUMN, dtype=float)
    g_series = _FlipRegime({T0: 0.3, T0 + DAY: 0.5, T0 + 2 * DAY: 0.7}).gross_multiplier_series(
        pd.DataFrame(index=pd.Index([T0, T0 + DAY, T0 + 2 * DAY]))
    )
    out = apply_regime_gate(mu_ann, g_series)
    ts = out.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    np.testing.assert_allclose(out.to_numpy()[ts < T0 + DAY], 2.0 * 0.3)
    np.testing.assert_allclose(out.to_numpy()[(ts >= T0 + DAY) & (ts < T0 + 2 * DAY)], 2.0 * 0.5)
    np.testing.assert_allclose(out.to_numpy()[ts >= T0 + 2 * DAY], 2.0 * 0.7)


def test_regime_gate_shrinks_magnitude_and_preserves_nan() -> None:
    """``0 < G ≤ 1 ⇒ |mu_ann_gated| ≤ |mu_ann|`` everywhere; NaN mu_ann stays NaN."""
    idx = _hourly_index(24, ["BTC", "ETH"])
    rng = np.random.default_rng(3)
    mu_ann = pd.Series(
        rng.normal(0.0, 0.3, size=len(idx)), index=idx, name=MU_ANN_COLUMN, dtype=float
    )
    mu_ann.iloc[5] = np.nan  # a NaN must survive the gate
    g_series = _FlipRegime({T0: 0.5}).gross_multiplier_series(pd.DataFrame(index=pd.Index([T0])))
    out = apply_regime_gate(mu_ann, g_series)
    assert bool(np.isnan(out.to_numpy()[5]))
    finite = np.isfinite(mu_ann.to_numpy())
    assert (np.abs(out.to_numpy())[finite] <= np.abs(mu_ann.to_numpy())[finite] + 1e-12).all()


# ===================================================== combined gate (D1 then D2)


def test_gate_signal_frame_applies_both_gates_keeps_ungated_alpha_blend() -> None:
    """``gate_signal_frame``: ``alpha_blend`` stays UNGATED Ã; effect lives in mu_ann."""
    idx = _hourly_index(48, ["BTC", "ETH"])
    a_tilde = pd.Series(
        np.linspace(-1.5, 1.5, len(idx)), index=idx, name=ALPHA_BLEND_COLUMN, dtype=float
    )
    mu_blend = pd.Series(0.2, index=idx, name=MU_ANN_COLUMN, dtype=float)
    signal_frame = pd.DataFrame({ALPHA_BLEND_COLUMN: a_tilde, MU_ANN_COLUMN: mu_blend}, index=idx)
    magnitude = pd.Series(
        np.clip(np.linspace(0.0, 1.0, len(idx)), 0.0, 1.0), index=idx, dtype=float
    )
    feature_frame = pd.DataFrame({"mag": magnitude}, index=idx)
    meta = _StubMeta("mag", ("mag",))
    g_series = _FlipRegime({T0: 0.5, T0 + DAY: 0.8}).gross_multiplier_series(
        pd.DataFrame(index=pd.Index([T0, T0 + DAY]))
    )
    sigma = pd.Series(0.5, index=idx)

    out = gate_signal_frame(signal_frame, feature_frame, meta, g_series, sigma)

    # alpha_blend column is the UNGATED Ã (the audit/IC quantity).
    pd.testing.assert_series_equal(out[ALPHA_BLEND_COLUMN], a_tilde)
    # mu_ann = mu_blend · |size| · G_d (by linearity).
    ts = out.index.get_level_values("ts_open").to_numpy(dtype=np.int64)
    g_row = np.where(ts < T0 + DAY, 0.5, 0.8)
    expected = mu_blend.to_numpy() * magnitude.to_numpy() * g_row
    np.testing.assert_allclose(out[MU_ANN_COLUMN].to_numpy(), expected)
    # Sign of mu_ann is the sign of |size|·G·mu_blend; both factors >= 0 so it
    # tracks mu_blend's sign (here mu_blend > 0) — never flipped.
    assert (out[MU_ANN_COLUMN].to_numpy() >= -1e-12).all()


def test_gate_signal_frame_recompute_path_is_guarded() -> None:
    """The ``mu_ann_from_blend=False`` recompute path is the linearity reference only."""
    idx = _hourly_index(2, ["BTC"])
    signal_frame = pd.DataFrame(
        {ALPHA_BLEND_COLUMN: [0.5, -0.5], MU_ANN_COLUMN: [0.1, -0.1]}, index=idx
    )
    g_series = IdentityRegime().gross_multiplier_series(pd.DataFrame(index=pd.Index([T0])))
    with pytest.raises(NotImplementedError):
        gate_signal_frame(
            signal_frame,
            None,
            IdentityMeta(),
            g_series,
            pd.Series(0.5, index=idx),
            mu_ann_from_blend=False,
        )
