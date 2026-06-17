"""Meta-model layer — calibrated P(win) that SCALES the blend (alphaDesign.md §6, §5.3).

This is Phase 9's load-bearing module: the seam (:class:`ModelProtocol` /
:class:`MetaModel`) and its v1 implementation
(:class:`HistGBMMetaModel`), plus the LdP bet-size map
(:func:`bet_size_from_prob`). Nothing here touches the live signal path — Phase 12
wires the model output into :class:`alphaforge.signals.sizing.GrinoldSizer` via
``F = size·|Ã|``.

The four correctness rules this layer inherits (build doc 09_ml.md §0, the two
adversarial critiques), each load-bearing and tested:

1. **No lookahead.** X arrives from the ONE feature engine; the model never
   recomputes a feature. The early-stop block is a *purged held tail*, never a
   random ``validation_fraction`` (CRITIQUE_leakage finding 7): sklearn's
   ``HistGradientBoostingClassifier`` has no hook to feed an explicit purged
   block, so we DISABLE its internal early stopping (``early_stopping=False``)
   and choose the iteration count EXTERNALLY by binary log-loss on the carved
   40d ES block, after purging every train row whose label interval ``[t, t1]``
   overlaps that block (the :class:`alphaforge.validation.splits.PurgedWalkForward`
   overlap rule, reused — :func:`_purge_overlapping`, not a forked fold loop).
2. **Cost-honest label (finding 11).** ``fit`` refuses a gross-only label frame
   for a production fit (``label_is_net`` must be True unless
   ``allow_gross_label``); gross labels are a diagnostic path only.
3. **Gate, never flip (finding 12 / §5.3).** :func:`bet_size_from_prob` returns
   ``side·(2Φ(z)-1)`` floored at ``p_min`` and discretized; its sign is the
   sign of ``side`` (the blend side ``s = sign(Ã)``) by construction, so
   ``F = size·|Ã|`` shares ``sign(Ã)`` or is zero — never the opposite sign.
4. **Calibration split disjoint from early-stopping (finding 9).** The trailing
   tail is split 40d early-stop / 20d isotonic; the GBM's iteration count is
   chosen on the 40d block and the :class:`sklearn.isotonic.IsotonicRegression`
   map is fit on the disjoint 20d block. Neither is reused for promotion.

The bet-size edge convention (CRITIQUE_leakage finding 16): full confidence is
full size, i.e. ``p → 1 ⇒ |size| → 1``. ``p`` is clipped to ``[eps, 1-eps]``
*before* the ``z = (p-0.5)/√(p(1-p))`` step so the limit is approached, never an
``inf`` divide; only a NaN ``p`` (or ``side``) collapses to size 0.

Pure and deterministic given the inputs and ``random_state``:
``HistGradientBoostingClassifier`` is reproducible for a fixed seed and the
single-threaded sklearn build on arm64.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, Self, runtime_checkable

import joblib
import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss

if TYPE_CHECKING:
    from collections.abc import Mapping

    from alphaforge.core.time import Ms

__all__ = [
    "DEFAULT_PARAMS",
    "EARLY_STOP_DAYS",
    "ISOTONIC_DAYS",
    "P_MIN",
    "SIZE_STEP",
    "FitWindows",
    "HistGBMMetaModel",
    "IdentityMeta",
    "MetaModel",
    "ModelProtocol",
    "bet_size_from_prob",
]

DEFAULT_PARAMS: Final[Mapping[str, object]] = {
    "max_depth": 4,  # shallow: up to 4-way interactions, all S/N supports
    "learning_rate": 0.03,  # slow; iteration count chosen by external early stopping
    "max_iter": 2000,  # ceiling; external early stopping picks the real number
    "min_samples_leaf": 200,  # every leaf is a >=200-sample statistical statement
    "l2_regularization": 5.0,  # heavy L2 shrink of leaf values toward 0
    "max_bins": 127,  # coarse bins resist micro-noise splits
    # CRITIQUE_leakage finding 7: sklearn early_stopping is a RANDOM/tail split that
    # leaks across the t1 gap. We disable it and select n_iter externally on the
    # explicit purged ES block, so validation_fraction is never used.
    "early_stopping": False,
    "random_state": 42,
}
"""Shallow, heavily-regularized HistGBM params (09_ml.md §1.1). The four pinned
knobs (max_depth, learning_rate, min_samples_leaf, l2_regularization) are asserted
by ``test_default_params_shallow_regularized``."""

EARLY_STOP_DAYS: Final[int] = 40
"""finding 9: the early-stop block length in days (chooses n_iter, never the map)."""

ISOTONIC_DAYS: Final[int] = 20
"""finding 9: the isotonic-calibration block length in days (disjoint from ES)."""

P_MIN: Final[float] = 0.50
"""§5.3: never trade against the classifier — ``p < p_min`` floors size to 0."""

SIZE_STEP: Final[float] = 0.05
"""Discretize bet size to suppress churn (09_ml.md §1.1)."""

_N_ITER_NO_CHANGE: Final[int] = 50
"""External early-stop patience: stop scanning iterations once ES log-loss has not
improved for this many consecutive trees (mirrors the spec's ``n_iter_no_change``)."""

_PROBA_EPS: Final[float] = 1e-9
"""``p`` is clipped to ``[eps, 1-eps]`` before the z-statistic so ``p→1`` approaches
``|size|=1`` (finding 16) rather than dividing by zero."""

_LABEL_FORBIDDEN_SUBSTRINGS: Final[tuple[str, ...]] = (
    "fwd_ret",
    "ret_net",
    "ret_gross",
    "meta_label",
    "label_tb",
    "t1",
    "side",
)
"""A feature column whose name contains any of these is a post-decision / label
quantity that must never enter X (09_ml.md §3: feature set ∩ label columns = ∅)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FitWindows:
    """The three disjoint time spans of one fit (finding 9), in epoch-ms UTC.

    ::

        train:      [train_start, es_start)   # GBM trees fit here (then purged by t1)
        early_stop: [es_start,    iso_start)  # 40d; chooses n_iter, purged from train
        isotonic:   [iso_start,   fit_end]    # 20d; fits the isotonic map, disjoint

    ``fit_end`` is the last decision-bar ``t`` whose label ``t1`` is fully realized
    (``t1 <= asof``); :func:`alphaforge.ml.retrain.build_fit_windows` carves it.
    Bounds are validated to be strictly increasing on construction.
    """

    train_start: Ms
    es_start: Ms
    iso_start: Ms
    fit_end: Ms

    def __post_init__(self) -> None:
        if not (self.train_start < self.es_start < self.iso_start <= self.fit_end):
            raise ValueError(
                "FitWindows bounds must satisfy "
                "train_start < es_start < iso_start <= fit_end; got "
                f"{self.train_start} / {self.es_start} / {self.iso_start} / {self.fit_end}"
            )


@runtime_checkable
class ModelProtocol(Protocol):
    """The seam: a weighted binary classifier emitting calibrated ``P(win)``.

    Implementations are pure of global state, deterministic given ``random_state``,
    and NEVER read features they were not handed (no lookahead by construction —
    X arrives from the ONE feature engine). ``feature_names`` pins column order so
    serve-time X is realigned, not positionally assumed. ``model_id`` is stamped on
    every prediction row at serve time (Phase 12) for live-vs-backtest reconciliation.
    """

    @property
    def feature_names(self) -> tuple[str, ...]: ...

    @property
    def model_id(self) -> str: ...

    def predict_proba(self, X: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Calibrated ``p ∈ [0, 1]``, shape ``(n,)``, aligned to ``X.index``."""
        ...

    def bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series:
        """The SINGLE composition (CRITIQUE_leakage finding 6): the floor/sign logic
        lives here, never re-glued per call site —
        ``bet_size_from_prob(predict_proba(x), side)``."""
        ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path) -> Self: ...


# `MetaModel` is the name Phase 12 imports for the seam (CRITIQUE_leakage finding 6);
# it is the same Protocol as `ModelProtocol` (one seam, two names for one contract).
MetaModel = ModelProtocol


def _require_panel_frame(X: pd.DataFrame) -> None:
    """Fail loud if X is not a (ts_open, instrument_id) MultiIndex frame."""
    if not isinstance(X.index, pd.MultiIndex) or X.index.nlevels != 2:
        raise ValueError(
            "X must be indexed by a 2-level (ts_open, instrument_id) MultiIndex; "
            f"got {type(X.index).__name__}"
        )


def _assert_features_disjoint_from_labels(columns: tuple[str, ...]) -> None:
    """Refuse any X column that is a post-decision / label quantity (09_ml.md §3)."""
    leaked = [c for c in columns if any(bad in c for bad in _LABEL_FORBIDDEN_SUBSTRINGS)]
    if leaked:
        raise ValueError(
            "feature set must be disjoint from label columns (09_ml.md §3); "
            f"these X columns are post-decision/label quantities: {leaked}"
        )


def _purge_overlapping(
    decision_ts: npt.NDArray[np.int64],
    t1: npt.NDArray[np.int64],
    held_start: Ms,
) -> npt.NDArray[np.bool_]:
    """Boolean mask of train rows to KEEP: label interval ``[t, t1]`` does NOT
    overlap the held block ``[held_start, ...)``.

    This is the :class:`alphaforge.validation.splits.PurgedWalkForward` overlap rule
    (``candidates + purge_bars·Δ >= test_start`` there), generalized from a fixed
    bar-count horizon to the explicit, variable triple-barrier ``t1`` carried per
    row: a train decision at ``t < held_start`` is purged exactly when its label is
    not fully realized before the held block opens, i.e. ``t1 >= held_start``. We
    reuse the *predicate*, not a forked fold loop (finding 16). ``decision_ts`` is
    only used to assert all train rows precede the block.
    """
    if decision_ts.size and int(decision_ts.max()) >= held_start:
        raise ValueError(
            "train rows must all precede the held block; "
            f"max train ts {int(decision_ts.max())} >= held_start {held_start}"
        )
    return t1 < held_start


class HistGBMMetaModel:
    """sklearn ``HistGradientBoostingClassifier`` + isotonic calibration (the seam).

    ``fit`` pipeline (alphaDesign §6.2, findings 9/11; module docstring):

    1. Align X to its column order; assert no NaN target/weight; assert the label
       frame is cost-honest (``label_is_net``) unless ``allow_gross_label``; assert
       the feature set is disjoint from label columns (§3).
    2. Carve train / 40d ES / 20d isotonic by ``windows`` and PURGE train rows whose
       label ``[t, t1]`` overlaps the ES block (:func:`_purge_overlapping`).
    3. Fit ``HistGradientBoostingClassifier(**DEFAULT_PARAMS)`` (internal early
       stopping OFF) with ``sample_weight``; choose the iteration count by binary
       log-loss on the purged 40d ES block via ``staged_decision_function``.
    4. Fit ``IsotonicRegression(out_of_bounds="clip")`` mapping the raw GBM score
       (truncated to ``best_n_iter``) → empirical ``P(win)`` on the DISJOINT 20d
       isotonic block.
    5. Freeze. ``predict_proba`` returns ``isotonic(raw_score@best_n_iter)``.

    The fit is pure given inputs + ``random_state``. ``model_id`` defaults to a
    content-stamped id; :class:`alphaforge.ml.registry.ModelCard` overrides it at
    registration time. Not constructed in production directly — go through
    :func:`alphaforge.ml.retrain.weekly_retrain`.
    """

    def __init__(
        self,
        *,
        params: Mapping[str, object] | None = None,
        random_state: int = 42,
        model_id: str = "histgbm_meta",
    ) -> None:
        merged: dict[str, object] = dict(DEFAULT_PARAMS)
        if params is not None:
            merged.update(params)
        merged["random_state"] = random_state
        merged["early_stopping"] = False  # finding 7: never sklearn's random tail
        self._params: dict[str, object] = merged
        self._random_state = random_state
        self._model_id = model_id
        self._estimator: HistGradientBoostingClassifier | None = None
        self._calibrator: IsotonicRegression | None = None
        self._feature_names: tuple[str, ...] = ()
        self._best_n_iter: int = 0
        self._windows: FitWindows | None = None
        self._n_train: int = 0

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def windows(self) -> FitWindows:
        if self._windows is None:
            raise RuntimeError("model is not fitted; no windows available")
        return self._windows

    @property
    def best_n_iter(self) -> int:
        """The externally-selected number of trees (finding 7)."""
        return self._best_n_iter

    def _check_fitted(self) -> tuple[HistGradientBoostingClassifier, IsotonicRegression]:
        if self._estimator is None or self._calibrator is None:
            raise RuntimeError("model is not fitted; call fit() first")
        return self._estimator, self._calibrator

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        w: pd.Series,
        t1: pd.Series,
        windows: FitWindows,
        *,
        label_is_net: bool = True,
        allow_gross_label: bool = False,
    ) -> Self:
        """Fit the GBM + isotonic calibrator (module / class docstring).

        ``X`` is the ``(ts_open, instrument_id)`` MultiIndex feature frame; ``y`` the
        meta-label ``∈ {0, 1}``; ``w`` the per-event sample weight; ``t1`` the label
        event-end (epoch-ms) per row. ``windows`` carves train/ES/isotonic. Raises
        ``ValueError`` on NaN target/weight, a gross-only label without
        ``allow_gross_label`` (finding 11), a feature/label overlap (§3), or an empty
        train/ES/isotonic block after purging.
        """
        _require_panel_frame(X)
        if not label_is_net and not allow_gross_label:
            raise ValueError(
                "label frame is gross-only (label_is_net=False); a production fit "
                "requires cost-honest net labels (finding 11). Pass "
                "allow_gross_label=True only on the diagnostic path."
            )
        feature_names = tuple(str(c) for c in X.columns)
        _assert_features_disjoint_from_labels(feature_names)

        y = y.reindex(X.index)
        w = w.reindex(X.index)
        t1 = t1.reindex(X.index)
        if bool(y.isna().any()) or bool(w.isna().any()):
            raise ValueError("y and w must be fully aligned to X with no NaN")
        if bool(t1.isna().any()):
            raise ValueError("t1 must be fully aligned to X with no NaN")
        if bool((w < 0).any()):
            raise ValueError("sample weights must be non-negative")

        decision_ts = X.index.get_level_values(0).to_numpy(dtype=np.int64)
        t1_arr = t1.to_numpy(dtype=np.int64)

        train_mask = decision_ts < windows.es_start
        es_mask = (decision_ts >= windows.es_start) & (decision_ts < windows.iso_start)
        iso_mask = (decision_ts >= windows.iso_start) & (decision_ts <= windows.fit_end)

        # Purge train rows whose label interval overlaps the ES block (finding 7/9).
        keep = _purge_overlapping(decision_ts[train_mask], t1_arr[train_mask], windows.es_start)
        train_idx = np.flatnonzero(train_mask)[keep]
        es_idx = np.flatnonzero(es_mask)
        iso_idx = np.flatnonzero(iso_mask)
        if train_idx.size == 0:
            raise ValueError("no train rows survive purging; widen the train window")
        if es_idx.size == 0:
            raise ValueError("early-stop block is empty; check FitWindows")
        if iso_idx.size == 0:
            raise ValueError("isotonic block is empty; check FitWindows")

        x_values = X.to_numpy(dtype=np.float64)
        y_values = y.to_numpy(dtype=np.float64)
        w_values = w.to_numpy(dtype=np.float64)

        estimator = HistGradientBoostingClassifier(**self._params)
        estimator.fit(
            x_values[train_idx],
            y_values[train_idx],
            sample_weight=w_values[train_idx],
        )

        best_n_iter = self._select_n_iter(
            estimator,
            x_values[es_idx],
            y_values[es_idx],
            w_values[es_idx],
        )

        raw_iso = self._raw_score_at(estimator, x_values[iso_idx], best_n_iter)
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(raw_iso, y_values[iso_idx])

        self._estimator = estimator
        self._calibrator = calibrator
        self._feature_names = feature_names
        self._best_n_iter = best_n_iter
        self._windows = windows
        self._n_train = int(train_idx.size)
        return self

    @property
    def n_train(self) -> int:
        """Number of (purged) training rows actually fit on."""
        return self._n_train

    def _select_n_iter(
        self,
        estimator: HistGradientBoostingClassifier,
        x_es: npt.NDArray[np.float64],
        y_es: npt.NDArray[np.float64],
        w_es: npt.NDArray[np.float64],
    ) -> int:
        """Choose the iteration count by binary log-loss on the purged ES block.

        Scans ``staged_decision_function`` (raw scores after ``k`` trees), maps each
        stage through the logistic link to a probability, and tracks the minimum
        weighted log-loss; stops scanning after ``_N_ITER_NO_CHANGE`` consecutive
        non-improvements (finding 7 — the held block is explicit and purged, never a
        random sklearn split). Returns a 1-based tree count ``>= 1``.
        """
        best_loss = np.inf
        best_iter = 1
        no_change = 0
        for k, raw in enumerate(estimator.staged_decision_function(x_es), start=1):
            proba = 1.0 / (1.0 + np.exp(-np.asarray(raw, dtype=np.float64).ravel()))
            loss = float(log_loss(y_es, proba, sample_weight=w_es, labels=[0.0, 1.0]))
            if loss < best_loss - 1e-12:
                best_loss = loss
                best_iter = k
                no_change = 0
            else:
                no_change += 1
                if no_change >= _N_ITER_NO_CHANGE:
                    break
        return best_iter

    @staticmethod
    def _raw_score_at(
        estimator: HistGradientBoostingClassifier,
        x_values: npt.NDArray[np.float64],
        n_iter: int,
    ) -> npt.NDArray[np.float64]:
        """Raw decision score after exactly ``n_iter`` trees (1-based), via
        ``staged_decision_function`` — the externally-selected truncation point."""
        last: npt.NDArray[np.float64] | None = None
        for k, raw in enumerate(estimator.staged_decision_function(x_values), start=1):
            last = np.asarray(raw, dtype=np.float64).ravel()
            if k >= n_iter:
                return last
        if last is None:  # pragma: no cover - estimator always has >=1 tree
            raise RuntimeError("estimator produced no staged scores")
        return last

    def predict_proba(self, X: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Calibrated ``p = isotonic(raw_score@best_n_iter)`` aligned to ``X.index``.

        X is realigned to ``feature_names`` (extra columns dropped, order fixed); a
        missing required column raises ``KeyError`` (never a silent positional
        mismatch — 09_ml.md §3).
        """
        estimator, calibrator = self._check_fitted()
        aligned = X[list(self._feature_names)]  # KeyError on a missing column
        raw = self._raw_score_at(estimator, aligned.to_numpy(dtype=np.float64), self._best_n_iter)
        proba: npt.NDArray[np.float64] = np.asarray(calibrator.predict(raw), dtype=np.float64)
        return np.clip(proba, 0.0, 1.0)

    def bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series:
        """The SINGLE composition (finding 6): predict_proba → calibrated p → size.

        ``side`` is the blend side ``s = sign(Ã)``, aligned to ``x.index``. The
        floor (``p_min``) and the sign-preservation invariant live ONLY here, so
        research and the model's own code call the same line.
        """
        p = pd.Series(self.predict_proba(x), index=x.index, name="p_win")
        return bet_size_from_prob(p, side.reindex(x.index))

    def save(self, path: Path) -> None:
        """Persist estimator + calibrator + feature_names + best_n_iter + a content
        sha (joblib). ``load`` reproduces ``predict_proba`` bitwise (09_ml.md §1.1)."""
        estimator, calibrator = self._check_fitted()
        payload = {
            "estimator": estimator,
            "calibrator": calibrator,
            "feature_names": self._feature_names,
            "best_n_iter": self._best_n_iter,
            "params": self._params,
            "random_state": self._random_state,
            "model_id": self._model_id,
            "windows": self._windows,
            "n_train": self._n_train,
            "content_sha": self._content_sha(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(payload, path)

    @classmethod
    def load(cls, path: Path) -> Self:
        """Reconstruct a frozen model from :meth:`save`'s artifact."""
        payload = joblib.load(path)
        model = cls(
            params=payload["params"],
            random_state=int(payload["random_state"]),
            model_id=str(payload["model_id"]),
        )
        model._estimator = payload["estimator"]
        model._calibrator = payload["calibrator"]
        model._feature_names = tuple(payload["feature_names"])
        model._best_n_iter = int(payload["best_n_iter"])
        model._windows = payload["windows"]
        model._n_train = int(payload["n_train"])
        return model

    def _content_sha(self) -> str:
        """A reproducibility stamp over feature_names + best_n_iter + params."""
        blob = json.dumps(
            {
                "feature_names": list(self._feature_names),
                "best_n_iter": self._best_n_iter,
                "params": {k: str(v) for k, v in sorted(self._params.items())},
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


class IdentityMeta:
    """The OFF gate (CRITIQUE_leakage finding 6): ``|size| ≡ 1``, ``sign == side``.

    Phase 12 plugs this in when the meta-gate is disabled so ``F = size·|Ã| = |Ã|``
    with ``sign(F) == sign(Ã)`` — i.e. byte-identical to the un-gated blend. It
    satisfies the same :class:`ModelProtocol`/:class:`MetaModel` seam, so the OFF
    path is mechanically the identity, never a special branch.
    """

    def __init__(self, feature_names: tuple[str, ...] = (), *, model_id: str = "identity") -> None:
        self._feature_names = feature_names
        self._model_id = model_id

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def model_id(self) -> str:
        return self._model_id

    def predict_proba(self, X: pd.DataFrame) -> npt.NDArray[np.float64]:
        """A degenerate ``p = 1`` everywhere → ``|size| = 1`` after the bet-size map."""
        return np.ones(len(X.index), dtype=np.float64)

    def bet_size(self, x: pd.DataFrame, side: pd.Series) -> pd.Series:
        """``|size| ≡ 1`` carrying ``sign == side`` (NaN side → 0)."""
        s = side.reindex(x.index)
        out = np.sign(s.to_numpy(dtype=np.float64))
        out[~np.isfinite(out)] = 0.0
        return pd.Series(out, index=x.index, name="bet_size", dtype=float)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"feature_names": self._feature_names, "model_id": self._model_id}, path)

    @classmethod
    def load(cls, path: Path) -> Self:
        payload = joblib.load(path)
        return cls(tuple(payload["feature_names"]), model_id=str(payload["model_id"]))


def bet_size_from_prob(
    p: pd.Series,
    side: pd.Series,
    *,
    p_min: float = P_MIN,
    step: float = SIZE_STEP,
) -> pd.Series:
    """LdP bet size (§5.3) — magnitude-only, NEVER sign-flipping (finding 12).

    ::

        z    = (p - 0.5) / √(p(1 - p))          (p clipped to [eps, 1-eps] first)
        size = side · (2·Φ(z) - 1)              floored to 0 when p < p_min
                                                discretized to `step`

    The size SHARES ``sign(side)`` by construction (``2Φ(z)-1 ∈ [0, 1)`` for
    ``z >= 0``, and ``z >= 0 ⇔ p >= 0.5``; below ``p_min >= 0.5`` it is floored to
    0), so ``F = size·|Ã|`` preserves ``sign(Ã)`` or is exactly 0 — never the
    opposite sign. The edge convention is "full confidence is full size":
    ``p → 1 ⇒ |size| → 1`` (finding 16), achieved by clipping ``p`` before the
    ``z`` step rather than special-casing ``p ∈ {0, 1}`` to 0. Only a NaN ``p`` or
    NaN ``side`` collapses to 0. Returns a float Series in ``[-1, 1]`` aligned to
    ``p.index``.
    """
    side = side.reindex(p.index)
    p_arr = p.to_numpy(dtype=np.float64)
    s_arr = side.to_numpy(dtype=np.float64)

    finite = np.isfinite(p_arr) & np.isfinite(s_arr)
    # Clip p so p→1 approaches |size|=1 (finding 16); below p_min it floors to 0.
    p_clipped = np.clip(p_arr, _PROBA_EPS, 1.0 - _PROBA_EPS)
    z = (p_clipped - 0.5) / np.sqrt(p_clipped * (1.0 - p_clipped))
    magnitude = 2.0 * np.asarray(norm.cdf(z), dtype=np.float64) - 1.0

    # Floor: never trade against the classifier (§5.3). p < p_min → 0.
    magnitude = np.where(p_arr < p_min, 0.0, magnitude)
    # Discretize the magnitude to `step`, clamp to [0, 1], then re-sign.
    magnitude = np.round(magnitude / step) * step
    magnitude = np.clip(magnitude, 0.0, 1.0)

    sign = np.sign(s_arr)
    out = sign * magnitude
    out = np.where(finite, out, 0.0)
    return pd.Series(out, index=p.index, name="bet_size", dtype=float)
