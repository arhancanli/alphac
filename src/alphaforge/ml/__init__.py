"""ML meta-labeling layer (alphaDesign.md §6) — calibrated P(win) that SCALES the blend.

Curated public surface — downstream modules import from :mod:`alphaforge.ml`, not
its submodules. By correctness rule 3 the model output GATES the blend
(``F = size·|Ã|``) and NEVER flips the sign of the signal.

* :mod:`alphaforge.ml.model` — the seam (:class:`ModelProtocol` / :class:`MetaModel`)
  and its v1 :class:`HistGBMMetaModel` (sklearn ``HistGradientBoostingClassifier``
  behind the Protocol so lightgbm can swap in later), the OFF :class:`IdentityMeta`,
  the LdP :func:`bet_size_from_prob` map, and the purged window constants.
* :mod:`alphaforge.ml.importance` — cluster-permutation MDA OOS feature importance
  (:func:`cluster_features`, :func:`mda_importance`).
* :mod:`alphaforge.ml.retrain` — the purged weekly retrain + champion/challenger
  promotion gate (:func:`weekly_retrain`, :func:`judge_promotion`,
  :func:`build_fit_windows`, :class:`PromotionVerdict`).
* :mod:`alphaforge.ml.registry` — the versioned :class:`ModelRegistry` /
  :class:`ModelCard` SQLite ledger enforcing the single-champion invariant.
"""

from alphaforge.ml.importance import cluster_features, mda_importance
from alphaforge.ml.model import (
    DEFAULT_PARAMS,
    EARLY_STOP_DAYS,
    ISOTONIC_DAYS,
    P_MIN,
    SIZE_STEP,
    FitWindows,
    HistGBMMetaModel,
    IdentityMeta,
    MetaModel,
    ModelProtocol,
    bet_size_from_prob,
)
from alphaforge.ml.registry import ModelCard, ModelRegistry, ModelStatus
from alphaforge.ml.retrain import (
    MLDataset,
    PromotionVerdict,
    build_fit_windows,
    dataset_content_sha,
    judge_promotion,
    weekly_retrain,
)

__all__ = [
    "DEFAULT_PARAMS",
    "EARLY_STOP_DAYS",
    "ISOTONIC_DAYS",
    "P_MIN",
    "SIZE_STEP",
    "FitWindows",
    "HistGBMMetaModel",
    "IdentityMeta",
    "MLDataset",
    "MetaModel",
    "ModelCard",
    "ModelProtocol",
    "ModelRegistry",
    "ModelStatus",
    "PromotionVerdict",
    "bet_size_from_prob",
    "build_fit_windows",
    "cluster_features",
    "dataset_content_sha",
    "judge_promotion",
    "mda_importance",
    "weekly_retrain",
]
