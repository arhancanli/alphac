"""Labeling: execution-aware targets for model training and factor evaluation.

Curated public surface — downstream modules import from :mod:`alphaforge.labeling`,
not its submodules. Labels look into the future by construction; they are
training/evaluation targets ONLY and must never re-enter the feature path.

Three primitives compose the meta-label panel:

* :mod:`alphaforge.labeling.triple_barrier` — cost-honest, gap-aware first-touch
  labels (:class:`TripleBarrierConfig`, :func:`apply_triple_barrier`); ``ret`` is
  NET of fees + half-spread + expected funding, ``ret_gross`` is a diagnostic only
  (leakageCritique finding 11).
* :mod:`alphaforge.labeling.weights` — the AFML uniqueness · decay ·
  cross-sectional de-correlation :func:`sample_weights` (and its
  :func:`concurrency` / :func:`average_uniqueness` / :func:`attribution_weights`
  building blocks) that corrects overlapping-label redundancy (finding 23).
* :mod:`alphaforge.labeling.forward_returns` — execution-aware fixed-horizon
  forward log returns (:func:`forward_returns`), the §5.1 auxiliary targets.

:func:`make_meta_label_dataset` assembles the three into the single
``(X, y, w, t1, side)`` training panel (:class:`MetaLabelDataset`) consumed by the
meta-model layer.
"""

from alphaforge.labeling.forward_returns import forward_returns
from alphaforge.labeling.meta import (
    DEFAULT_FORWARD_HORIZONS,
    MetaLabelDataset,
    make_meta_label_dataset,
    make_meta_labels,
)
from alphaforge.labeling.triple_barrier import TripleBarrierConfig, apply_triple_barrier
from alphaforge.labeling.weights import (
    attribution_weights,
    average_uniqueness,
    concurrency,
    sample_weights,
)

__all__ = [
    "DEFAULT_FORWARD_HORIZONS",
    "MetaLabelDataset",
    "TripleBarrierConfig",
    "apply_triple_barrier",
    "attribution_weights",
    "average_uniqueness",
    "concurrency",
    "forward_returns",
    "make_meta_label_dataset",
    "make_meta_labels",
    "sample_weights",
]
