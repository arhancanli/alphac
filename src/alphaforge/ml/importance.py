"""Cluster-permutation MDA feature importance (alphaDesign.md §6.3; 09_ml.md §1.2).

Mean-Decrease-Accuracy permutation importance, on the OOS test fold of THE one
purged walk-forward splitter (:class:`alphaforge.validation.splits.PurgedWalkForward`,
finding 16 — no forked fold loop), with two corrections the naive per-feature
permutation lacks:

1. **Substitution effect (clustering).** Two correlated features each look
   unimportant under per-feature permutation because the model leans on the
   other; permuting only one barely moves the loss. :func:`cluster_features`
   collapses ``|rho_Spearman| >= corr_threshold`` columns into one cluster and
   :func:`mda_importance` permutes the whole cluster JOINTLY (the same row
   permutation across every column), so a cluster's importance is the loss
   increase when its entire correlated block is destroyed.
2. **Out-of-sample only.** Importance is the increase in binary log-loss on the
   HELD test fold after permuting a cluster — never on the train fold, where a
   flexible learner can memorize and per-feature MDA is meaningless. A fresh
   model is fit per fold on the purged train block.

A cluster whose ``mean - std <= 0`` across folds is a removal candidate (its
importance is not distinguishable from zero given the fold-to-fold spread). The
permutation RNG is seeded per ``(fold, cluster, repeat)`` so the report is bitwise
reproducible.

CRITIQUE_leakage finding 11: the correlation structure of slow features
(multi-week momentum, year-scale vol percentiles) drifts, so a clustering fit on
the WHOLE matrix (test rows included) is a mild contamination and is not the
clustering that held in any single fold. We therefore re-cluster on the TRAIN
slice of each fold by default (``recluster_per_fold=True``); members are
aggregated by their stable member-set across folds. A caller that has a
pre-registered grouping derived from a held-out design window may pass it via
``clusters=`` and set ``recluster_per_fold=False`` (the provenance is then the
caller's responsibility, documented on the returned frame's attrs).

Pure of global state: deterministic given the inputs, the splitter, and the seeds.
Offline — no lake, no clock, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import log_loss

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from alphaforge.ml.model import HistGBMMetaModel
    from alphaforge.validation.splits import PurgedWalkForward

__all__ = [
    "cluster_features",
    "mda_importance",
]

_CLUSTER_ID_FMT: Final[str] = "cluster_{:02d}"
"""Deterministic cluster-id format (09_ml.md §1.2): ``cluster_00``, ``cluster_01``, …"""

_RANK_IC_LOSS_LABELS: Final[tuple[float, float]] = (0.0, 1.0)
"""Fixed label set for :func:`sklearn.metrics.log_loss` so a single-class fold
slice never silently relabels the binary outcome."""


def cluster_features(
    X: pd.DataFrame, *, corr_threshold: float = 0.7
) -> dict[str, list[str]]:
    """Hierarchical clustering on ``d = 1 - |rho_Spearman|`` (average linkage).

    Columns are grouped so that ``|rho| >= corr_threshold`` forces co-membership
    (the distance cut is ``1 - corr_threshold``); independent columns become
    singleton clusters. This is the substitution-effect fix of §6.3: correlated
    factors share one cluster so joint permutation, not per-feature permutation,
    measures their importance.

    Cluster ids are deterministic — ``cluster_00``, ``cluster_01``, … assigned by
    ASCENDING minimum member column-index — so the same matrix always yields the
    same ids regardless of scipy's internal label numbering. Members within a
    cluster are returned in column order.

    A matrix with a single column (or all-constant columns whose Spearman rho is
    undefined) degenerates gracefully to one singleton cluster per column.

    Raises ``ValueError`` for ``corr_threshold`` outside ``(0, 1]`` or an empty X.
    """
    if not 0.0 < corr_threshold <= 1.0:
        raise ValueError(f"corr_threshold must be in (0, 1]; got {corr_threshold}")
    columns = [str(c) for c in X.columns]
    n = len(columns)
    if n == 0:
        raise ValueError("X has no columns to cluster")
    if n == 1:
        return {_CLUSTER_ID_FMT.format(0): [columns[0]]}

    # Spearman correlation = Pearson of average-tie ranks; a constant column has
    # undefined rho (NaN) -> treated as maximally distant (d = 1), i.e. its own cluster.
    ranks = X.rank(method="average")
    corr = ranks.corr(method="pearson").to_numpy(dtype=np.float64)
    abs_corr = np.abs(corr)
    abs_corr[~np.isfinite(abs_corr)] = 0.0
    np.fill_diagonal(abs_corr, 1.0)
    dist = 1.0 - abs_corr
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)  # enforce exact symmetry for squareform

    condensed = squareform(dist, checks=False)
    linkage_matrix = linkage(condensed, method="average")
    cut = 1.0 - corr_threshold
    raw_labels = fcluster(linkage_matrix, t=cut, criterion="distance")

    # Group columns by scipy's (arbitrary) label, then re-id by ascending min index.
    by_label: dict[int, list[int]] = {}
    for col_idx, label in enumerate(raw_labels):
        by_label.setdefault(int(label), []).append(col_idx)
    ordered = sorted(by_label.values(), key=min)
    clusters: dict[str, list[str]] = {}
    for cluster_idx, member_positions in enumerate(ordered):
        cid = _CLUSTER_ID_FMT.format(cluster_idx)
        clusters[cid] = [columns[p] for p in sorted(member_positions)]
    return clusters


def _weighted_logloss(
    proba: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    w: npt.NDArray[np.float64],
) -> float:
    """Sample-weighted binary log-loss with fixed ``{0, 1}`` labels."""
    return float(log_loss(y, proba, sample_weight=w, labels=list(_RANK_IC_LOSS_LABELS)))


def mda_importance(
    model_factory: Callable[[], HistGBMMetaModel],
    X: pd.DataFrame,
    y: pd.Series,
    w: pd.Series,
    t1: pd.Series,
    splitter: PurgedWalkForward,
    clusters: Mapping[str, list[str]] | None = None,
    *,
    n_repeats: int = 5,
    seed: int = 42,
    corr_threshold: float = 0.7,
    recluster_per_fold: bool = True,
) -> pd.DataFrame:
    """Cluster-permutation MDA over purged walk-forward folds (§6.3).

    For each ``(train_ts, test_ts)`` yielded by ``splitter.split(grid)`` (``grid``
    = the sorted unique ``ts_open`` of ``X``)::

        fit a fresh model_factory() on the TRAIN fold (carving its own
            train/ES/isotonic windows from the train span)
        base = weighted_logloss(model, test_X, test_y, test_w)
        for each cluster G:
            for r in range(n_repeats):
                permute ALL columns of G JOINTLY (one row permutation, applied to
                    every column of G) within the TEST fold only
                imp_fold[G] += weighted_logloss(model, X_permuted, y, w) - base

    A positive mean is an informative cluster (destroying it RAISES the loss); a
    cluster whose ``mean - std <= 0`` across folds is a removal candidate.

    ``clusters`` may be supplied as a pre-registered grouping; if ``None`` the
    clustering is derived per-fold from the train slice (``recluster_per_fold``)
    or once from the full matrix (``recluster_per_fold=False``). Per-fold cluster
    ids are matched across folds by their stable member-set (finding 11): a
    cluster present in only some folds contributes only those folds' increments.

    The permutation RNG is seeded ``seed + fold·1_000_003 + cluster_ord·1_009 + r``
    so the report is bitwise reproducible. Returns a DataFrame indexed by cluster
    id with columns ``[mean, std, members, n_folds]`` (``std`` is the population
    std across folds; ``members`` is a comma-joined column list), sorted by
    descending mean. ``attrs["clustering_provenance"]`` records how clusters were
    derived.

    Raises ``ValueError`` for ``n_repeats < 1`` or an X without a
    ``(ts_open, instrument_id)`` MultiIndex.
    """
    if n_repeats < 1:
        raise ValueError(f"n_repeats must be >= 1; got {n_repeats}")
    if not isinstance(X.index, pd.MultiIndex) or X.index.nlevels != 2:
        raise ValueError("X must be indexed by a 2-level (ts_open, instrument_id) MultiIndex")

    decision_ts = X.index.get_level_values(0).to_numpy(dtype=np.int64)
    grid = np.unique(decision_ts)

    if clusters is not None:
        provenance = "supplied"
    elif recluster_per_fold:
        provenance = "per-fold-train"
    else:
        clusters = cluster_features(X, corr_threshold=corr_threshold)
        provenance = "global"

    # Accumulate per-cluster (keyed by member-set) increments across folds.
    per_member_set: dict[tuple[str, ...], list[float]] = {}

    for fold_idx, (train_ts, test_ts) in enumerate(splitter.split(grid)):
        train_mask = np.isin(decision_ts, train_ts)
        test_mask = np.isin(decision_ts, test_ts)
        if not train_mask.any() or not test_mask.any():
            continue

        X_train = X.loc[train_mask]
        model = _fit_on_train_span(
            model_factory(), X_train, y.loc[train_mask], w.loc[train_mask], t1.loc[train_mask]
        )
        if model is None:  # too short to carve disjoint ES/isotonic blocks
            continue

        X_test = X.loc[test_mask]
        y_test = y.reindex(X_test.index).to_numpy(dtype=np.float64)
        w_test = w.reindex(X_test.index).to_numpy(dtype=np.float64)
        base = _weighted_logloss(model.predict_proba(X_test), y_test, w_test)

        fold_clusters = (
            cluster_features(X_train, corr_threshold=corr_threshold)
            if (clusters is None)
            else dict(clusters)
        )
        for cluster_ord, (_cid, members) in enumerate(sorted(fold_clusters.items())):
            member_key = tuple(members)
            increments = per_member_set.setdefault(member_key, [])
            delta_sum = 0.0
            for r in range(n_repeats):
                rng = np.random.RandomState(
                    seed + fold_idx * 1_000_003 + cluster_ord * 1_009 + r
                )
                X_perm = X_test.copy()
                perm = rng.permutation(len(X_test.index))
                for col in members:
                    X_perm[col] = X_test[col].to_numpy()[perm]
                permuted_loss = _weighted_logloss(model.predict_proba(X_perm), y_test, w_test)
                delta_sum += permuted_loss - base
            increments.append(delta_sum / n_repeats)

    return _summarize_importance(per_member_set, provenance)


def _fit_on_train_span(
    model: HistGBMMetaModel,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    w_train: pd.Series,
    t1_train: pd.Series,
) -> HistGBMMetaModel | None:
    """Fit ``model`` on a fold's train span, carving its own disjoint ES/isotonic.

    Returns the fitted model, or ``None`` when the train span is too short to carve
    a strictly-increasing (train / 40d ES / 20d isotonic) split — such a fold is
    skipped rather than fit on a degenerate window. Imports the windowing helper
    lazily to keep this module free of an import cycle through ``retrain``.
    """
    from alphaforge.ml.retrain import _MS_PER_DAY, EARLY_STOP_DAYS, ISOTONIC_DAYS

    span_ts = X_train.index.get_level_values(0).to_numpy(dtype=np.int64)
    fit_end = int(span_ts.max())
    iso_start = fit_end - (ISOTONIC_DAYS - 1) * _MS_PER_DAY
    es_start = iso_start - EARLY_STOP_DAYS * _MS_PER_DAY
    train_start = int(span_ts.min())
    if not (train_start < es_start < iso_start <= fit_end):
        return None

    from alphaforge.ml.model import FitWindows

    windows = FitWindows(
        train_start=train_start, es_start=es_start, iso_start=iso_start, fit_end=fit_end
    )
    try:
        return model.fit(X_train, y_train, w_train, t1_train, windows)
    except ValueError:
        return None


def _summarize_importance(
    per_member_set: Mapping[tuple[str, ...], list[float]], provenance: str
) -> pd.DataFrame:
    """Aggregate per-fold increments (keyed by member-set) into the report frame."""
    cids: list[str] = []
    means: list[float] = []
    stds: list[float] = []
    members_str: list[str] = []
    n_folds: list[int] = []
    # Re-id clusters deterministically by ascending member tuple (stable across runs).
    for cluster_idx, member_key in enumerate(sorted(per_member_set)):
        increments = np.asarray(per_member_set[member_key], dtype=np.float64)
        cids.append(_CLUSTER_ID_FMT.format(cluster_idx))
        means.append(float(increments.mean()) if increments.size else float("nan"))
        stds.append(float(increments.std(ddof=0)) if increments.size else float("nan"))
        members_str.append(",".join(member_key))
        n_folds.append(int(increments.size))

    frame = pd.DataFrame(
        {"mean": means, "std": stds, "members": members_str, "n_folds": n_folds},
        index=pd.Index(cids, name="cluster_id"),
    )
    frame = frame.sort_values("mean", ascending=False, kind="stable")
    frame.attrs["clustering_provenance"] = provenance
    return frame
