"""Unit tests for alphaforge.ml.model — the meta-model seam + LdP bet size.

These pin the four correctness rules Phase 9's model layer inherits (09_ml.md §0,
CRITIQUE_leakage findings 6/7/16, CRITIQUE_overfit, finding 9/12):

* Shallow/regularized HistGBM params (the four pinned knobs).
* Disjoint early-stop / isotonic blocks, and a PURGED early-stop block: a train row
  whose label ``[t, t1]`` overlaps the ES block never enters the trees (finding 7/9).
* Calibrated ``p ∈ [0, 1]`` that is non-decreasing in the raw score (isotonic).
* Serve-time column realignment with a loud ``KeyError`` on a missing feature.
* save/load reproducing ``predict_proba`` bitwise.
* The feature set is disjoint from label columns (refuses ``fwd_ret``/``t1``/...).
* The bet-size map SHARES the side's sign or is exactly 0 — NEVER flips (finding 12);
  ``p < p_min → 0``; ``p → 1 ⇒ |size| → 1`` (finding 16); NaN ``p`` → 0.
* A behavioural sanity test: a constructed edge yields a higher calibrated ``p`` in
  the winning regime than the losing one.

Offline, pure pandas/numpy/sklearn; no lake, no I/O beyond a tmp_path roundtrip. All
fixtures synthetic and seeded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from alphaforge.ml.model import (
    DEFAULT_PARAMS,
    EARLY_STOP_DAYS,
    ISOTONIC_DAYS,
    SIZE_STEP,
    FitWindows,
    HistGBMMetaModel,
    IdentityMeta,
    MetaModel,
    ModelProtocol,
    bet_size_from_prob,
)

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01 00:00 UTC


def _make_dataset(
    *,
    n_days: int = 200,
    n_iids: int = 6,
    seed: int = 0,
    edge_feature: str = "f0",
    horizon_bars: int = 72,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Synthetic (X, y, w, t1) with a known edge: ``meta_label`` depends on one
    feature plus noise. One decision bar per day per instrument (daily grid keeps
    the day-block carving simple). Returns a (ts_open, instrument_id) panel.
    """
    rng = np.random.RandomState(seed)
    days = [T0 + d * DAY for d in range(n_days)]
    iids = [f"I{k}" for k in range(n_iids)]
    index = pd.MultiIndex.from_product([days, iids], names=("ts_open", "instrument_id"))
    n = len(index)
    feats = {f"f{j}": rng.randn(n) for j in range(4)}
    X = pd.DataFrame(feats, index=index)
    # Edge: P(win) rises with the edge feature; the rest are pure noise.
    logit = 1.5 * X[edge_feature].to_numpy() + 0.3 * rng.randn(n)
    p_true = 1.0 / (1.0 + np.exp(-logit))
    y = pd.Series((rng.rand(n) < p_true).astype(float), index=index, name="meta_label")
    w = pd.Series(np.ones(n), index=index, name="w")
    # t1 = decision ts + horizon_bars hours (the realized event end).
    ts = index.get_level_values(0).to_numpy(dtype=np.int64)
    t1 = pd.Series(ts + horizon_bars * HOUR, index=index, name="t1")
    return X, y, w, t1


def _windows(*, n_days: int = 200) -> FitWindows:
    """Carve the last ES+ISO days off a daily grid of ``n_days`` days."""
    fit_end = T0 + (n_days - 1) * DAY
    iso_start = T0 + (n_days - ISOTONIC_DAYS) * DAY
    es_start = T0 + (n_days - ISOTONIC_DAYS - EARLY_STOP_DAYS) * DAY
    train_start = T0
    return FitWindows(
        train_start=train_start, es_start=es_start, iso_start=iso_start, fit_end=fit_end
    )


class TestDefaultParams:
    def test_default_params_shallow_regularized(self) -> None:
        """The four pinned knobs (09_ml.md §1.1)."""
        assert DEFAULT_PARAMS["max_depth"] == 4
        assert DEFAULT_PARAMS["learning_rate"] == 0.03
        assert DEFAULT_PARAMS["min_samples_leaf"] == 200
        assert DEFAULT_PARAMS["l2_regularization"] == 5.0
        # finding 7: sklearn's internal early stopping is OFF (we purge externally).
        assert DEFAULT_PARAMS["early_stopping"] is False

    def test_protocol_conformance(self) -> None:
        """The seam: HistGBMMetaModel and IdentityMeta satisfy ModelProtocol/MetaModel."""
        assert MetaModel is ModelProtocol
        X, y, w, t1 = _make_dataset()
        m = HistGBMMetaModel().fit(X, y, w, t1, _windows())
        assert isinstance(m, ModelProtocol)
        assert isinstance(IdentityMeta(), ModelProtocol)


class TestFitWindows:
    def test_rejects_non_increasing_bounds(self) -> None:
        with pytest.raises(ValueError, match="train_start < es_start"):
            FitWindows(train_start=T0, es_start=T0, iso_start=T0 + DAY, fit_end=T0 + 2 * DAY)


class TestFitBlocks:
    def test_fit_uses_disjoint_es_and_isotonic_blocks(self) -> None:
        """finding 9: the ES block and the isotonic block do not overlap, and no
        isotonic-block row is in the GBM's fit set."""
        w = _windows()
        assert w.es_start < w.iso_start <= w.fit_end  # disjoint, ES before ISO
        X, y, ww, t1 = _make_dataset()
        m = HistGBMMetaModel().fit(X, y, ww, t1, w)
        ts = X.index.get_level_values(0).to_numpy(dtype=np.int64)
        # Train rows fit on are those with ts < es_start AND t1 < es_start (purged).
        # No isotonic-block row (ts >= iso_start) can satisfy ts < es_start.
        n_train_candidates = int(((ts < w.es_start) & (t1.to_numpy() < w.es_start)).sum())
        assert m.n_train == n_train_candidates
        assert m.n_train > 0

    def test_no_lookahead_es_block_purged(self) -> None:
        """finding 7: a train row whose ``[t, t1]`` overlaps the ES block is absent
        from the trees' training set (the PurgedWalkForward overlap rule)."""
        w = _windows()
        X, y, ww, t1 = _make_dataset()
        ts = X.index.get_level_values(0).to_numpy(dtype=np.int64)
        # Rows decided before es_start but whose label spills into the ES block.
        overlap = (ts < w.es_start) & (t1.to_numpy() >= w.es_start)
        assert overlap.any()  # the fixture actually has spill-over rows
        m = HistGBMMetaModel().fit(X, y, ww, t1, w)
        kept = (ts < w.es_start) & (t1.to_numpy() < w.es_start)
        # n_train counts only the purged-kept rows, never the overlapping ones.
        assert m.n_train == int(kept.sum())
        assert m.n_train < int((ts < w.es_start).sum())  # purging actually dropped some

    def test_fit_raises_on_empty_train_after_purge(self) -> None:
        X, y, ww, t1 = _make_dataset(n_days=70)
        # Window with no realized train rows before the ES block.
        bad = FitWindows(
            train_start=T0,
            es_start=T0 + 1 * DAY,
            iso_start=T0 + 41 * DAY,
            fit_end=T0 + 61 * DAY,
        )
        with pytest.raises(ValueError, match="no train rows survive"):
            HistGBMMetaModel().fit(X, y, ww, t1, bad)


class TestLabelContract:
    def test_gross_only_label_refused_for_production(self) -> None:
        """finding 11: a gross-only label is refused unless allow_gross_label."""
        X, y, w, t1 = _make_dataset()
        with pytest.raises(ValueError, match="cost-honest net labels"):
            HistGBMMetaModel().fit(X, y, w, t1, _windows(), label_is_net=False)

    def test_gross_label_allowed_on_diagnostic_path(self) -> None:
        X, y, w, t1 = _make_dataset()
        m = HistGBMMetaModel().fit(
            X, y, w, t1, _windows(), label_is_net=False, allow_gross_label=True
        )
        assert m.n_train > 0

    def test_feature_set_disjoint_from_labels(self) -> None:
        """fit raises if X carries a post-decision / label quantity (§3)."""
        X, y, w, t1 = _make_dataset()
        for bad_col in ("fwd_ret_72", "t1", "side", "meta_label", "ret_net"):
            X_bad = X.copy()
            X_bad[bad_col] = 0.0
            with pytest.raises(ValueError, match="disjoint from label columns"):
                HistGBMMetaModel().fit(X_bad, y, w, t1, _windows())

    def test_nan_target_rejected(self) -> None:
        X, y, w, t1 = _make_dataset()
        y_bad = y.copy()
        y_bad.iloc[0] = np.nan
        with pytest.raises(ValueError, match="no NaN"):
            HistGBMMetaModel().fit(X, y_bad, w, t1, _windows())


class TestPredict:
    def test_calibrated_proba_in_unit_interval_and_monotone(self) -> None:
        """predict_proba ∈ [0,1] and isotonic output is non-decreasing in raw score."""
        X, y, w, t1 = _make_dataset()
        m = HistGBMMetaModel().fit(X, y, w, t1, _windows())
        p = m.predict_proba(X)
        assert p.shape == (len(X.index),)
        assert float(p.min()) >= 0.0
        assert float(p.max()) <= 1.0
        # Monotone in the raw score: sort by raw, assert p non-decreasing.
        raw = m._raw_score_at(m._check_fitted()[0], X.to_numpy(dtype=np.float64), m.best_n_iter)
        order = np.argsort(raw)
        assert bool(np.all(np.diff(p[order]) >= -1e-9))

    def test_predict_realigns_columns(self) -> None:
        """Shuffled / extra columns are realigned to feature_names; missing -> KeyError."""
        X, y, w, t1 = _make_dataset()
        m = HistGBMMetaModel().fit(X, y, w, t1, _windows())
        base = m.predict_proba(X)
        # Shuffle column order + add an extra column -> identical prediction.
        cols = list(X.columns)[::-1]
        X_shuffled = X[cols].copy()
        X_shuffled["extra"] = 99.0
        np.testing.assert_allclose(m.predict_proba(X_shuffled), base, rtol=0, atol=0)
        # Drop a required column -> KeyError.
        with pytest.raises(KeyError):
            m.predict_proba(X.drop(columns=[m.feature_names[0]]))

    def test_save_load_roundtrip_identical_proba(self, tmp_path: object) -> None:
        """load(save(m)) gives bitwise-equal predict_proba on a fixed X."""
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        X, y, w, t1 = _make_dataset()
        m = HistGBMMetaModel(model_id="histgbm_meta_test").fit(X, y, w, t1, _windows())
        path = tmp_path / "model.joblib"
        m.save(path)
        loaded = HistGBMMetaModel.load(path)
        np.testing.assert_array_equal(loaded.predict_proba(X), m.predict_proba(X))
        assert loaded.feature_names == m.feature_names
        assert loaded.model_id == "histgbm_meta_test"
        assert loaded.best_n_iter == m.best_n_iter

    def test_deterministic_fit(self) -> None:
        """Two fits with the same seed produce identical predictions."""
        X, y, w, t1 = _make_dataset()
        a = HistGBMMetaModel().fit(X, y, w, t1, _windows())
        b = HistGBMMetaModel().fit(X, y, w, t1, _windows())
        np.testing.assert_array_equal(a.predict_proba(X), b.predict_proba(X))
        assert a.best_n_iter == b.best_n_iter


class TestBehavioural:
    def test_higher_proba_in_winning_regime(self) -> None:
        """A constructed edge: rows with a large positive edge feature get a higher
        calibrated p than rows with a large negative edge feature (behavioural
        sanity, not a tolerance test)."""
        X, y, w, t1 = _make_dataset(n_days=240, seed=7)
        m = HistGBMMetaModel().fit(X, y, w, t1, _windows(n_days=240))
        p = pd.Series(m.predict_proba(X), index=X.index)
        win = p[X["f0"] > 1.0].mean()
        lose = p[X["f0"] < -1.0].mean()
        assert win > lose


class TestBetSize:
    def _side(self, index: pd.Index, values: np.ndarray) -> pd.Series:
        return pd.Series(values, index=index, name="side", dtype=float)

    def test_size_shares_side_sign(self) -> None:
        """finding 12: sign(bet_size) == side wherever non-zero; F = size·|Ã| never
        flips sign(Ã)."""
        rng = np.random.RandomState(1)
        n = 500
        idx = pd.RangeIndex(n)
        p = pd.Series(rng.uniform(0.0, 1.0, n), index=idx)
        side = self._side(idx, rng.choice([-1.0, 1.0], n))
        size = bet_size_from_prob(p, side)
        nz = size.to_numpy() != 0.0
        assert np.all(np.sign(size.to_numpy()[nz]) == side.to_numpy()[nz])
        # F = size·|alpha_tilde| preserves sign(alpha_tilde) or is 0.
        a = pd.Series(rng.randn(n), index=idx)
        f = size * a.abs()
        same_or_zero = (np.sign(f.to_numpy()) == np.sign(side.to_numpy())) | (f.to_numpy() == 0.0)
        # f's sign is size's sign (== side); never the opposite.
        assert np.all(same_or_zero | (f.to_numpy() == 0.0))
        flip = (np.sign(f.to_numpy()) == -np.sign(side.to_numpy())) & (f.to_numpy() != 0.0)
        assert not flip.any()

    def test_size_zero_below_pmin(self) -> None:
        """p < 0.5 -> size == 0 (never trade against the classifier)."""
        idx = pd.RangeIndex(5)
        p = pd.Series([0.0, 0.1, 0.3, 0.49, 0.5 - 1e-12], index=idx)
        side = self._side(idx, np.ones(5))
        size = bet_size_from_prob(p, side)
        assert np.all(size.to_numpy() == 0.0)

    def test_size_discretized_and_bounded(self) -> None:
        """Output is a multiple of step and in [-1, 1]; p=0.5 -> 0; p->1 -> |size|->1."""
        idx = pd.RangeIndex(3)
        p = pd.Series([0.5, 0.75, 1.0 - 1e-12], index=idx)
        side = self._side(idx, np.ones(3))
        size = bet_size_from_prob(p, side)
        vals = size.to_numpy()
        # Multiple of step.
        np.testing.assert_allclose(vals / SIZE_STEP, np.round(vals / SIZE_STEP), atol=1e-9)
        assert float(vals.min()) >= -1.0
        assert float(vals.max()) <= 1.0
        assert vals[0] == 0.0  # p == 0.5 -> z=0 -> magnitude 0
        # finding 16: full confidence is full size.
        assert vals[2] == pytest.approx(1.0)

    def test_degenerate_p_handling(self) -> None:
        """finding 16: p=1 -> |size|=1 (NOT 0); NaN p -> 0; p=0 -> 0 (below p_min)."""
        idx = pd.RangeIndex(4)
        p = pd.Series([1.0, 0.0, np.nan, 0.5], index=idx)
        side = self._side(idx, np.array([1.0, 1.0, 1.0, -1.0]))
        size = bet_size_from_prob(p, side)
        assert size.iloc[0] == pytest.approx(1.0)  # p=1 -> full long size
        assert size.iloc[1] == 0.0  # p=0 < p_min -> 0
        assert size.iloc[2] == 0.0  # NaN -> 0
        assert size.iloc[3] == 0.0  # p=0.5 -> 0

    def test_nan_side_zeroed(self) -> None:
        idx = pd.RangeIndex(2)
        p = pd.Series([0.9, 0.9], index=idx)
        side = self._side(idx, np.array([np.nan, 1.0]))
        size = bet_size_from_prob(p, side)
        assert size.iloc[0] == 0.0
        assert size.iloc[1] != 0.0

    def test_matches_closed_form(self) -> None:
        """Pin the formula: size = side·(2Φ(z)-1) discretized, for a clean p."""
        idx = pd.RangeIndex(1)
        p_val = 0.8
        p = pd.Series([p_val], index=idx)
        side = self._side(idx, np.array([-1.0]))
        z = (p_val - 0.5) / np.sqrt(p_val * (1.0 - p_val))
        mag = 2.0 * float(norm.cdf(z)) - 1.0
        expected = -1.0 * (round(mag / SIZE_STEP) * SIZE_STEP)
        assert bet_size_from_prob(p, side).iloc[0] == pytest.approx(expected)


class TestIdentityMeta:
    def test_identity_size_is_unit_signed(self) -> None:
        """IdentityMeta: |size| ≡ 1, sign == side (the OFF / byte-identical path)."""
        idx = pd.MultiIndex.from_product(
            [[T0], ["A", "B", "C"]], names=("ts_open", "instrument_id")
        )
        x = pd.DataFrame({"f0": [0.1, 0.2, 0.3]}, index=idx)
        side = pd.Series([1.0, -1.0, np.nan], index=idx)
        m = IdentityMeta()
        size = m.bet_size(x, side)
        assert size.iloc[0] == pytest.approx(1.0)
        assert size.iloc[1] == pytest.approx(-1.0)
        assert size.iloc[2] == 0.0  # NaN side -> 0
        # F = size·|alpha| == |alpha| for the long, -|alpha| for the short (no flip).
        assert np.all(m.predict_proba(x) == 1.0)

    def test_identity_save_load(self, tmp_path: object) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        m = IdentityMeta(("f0", "f1"), model_id="identity_x")
        path = tmp_path / "id.joblib"
        m.save(path)
        loaded = IdentityMeta.load(path)
        assert loaded.feature_names == ("f0", "f1")
        assert loaded.model_id == "identity_x"
