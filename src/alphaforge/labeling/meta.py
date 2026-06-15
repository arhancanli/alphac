"""Meta-label dataset assembly (alphaDesign.md §5.3, §4.3; build doc 09_labeling.md §3).

This module composes the three labeling primitives into the single training panel the
meta-model consumes:

* :func:`alphaforge.labeling.triple_barrier.apply_triple_barrier` (B1) — the
  cost-honest, gap-aware §1.3 label frame (``ret``, ``meta_label``, ``t1``, ``side``,
  ``entry_ts`` …);
* :func:`alphaforge.labeling.weights.sample_weights` (B2) — the AFML uniqueness ·
  decay · cross-sectional de-correlation ``sample_weight``;
* :func:`alphaforge.labeling.forward_returns.forward_returns` — the execution-aware
  fixed-horizon forward log returns (§5.1) kept as auxiliary regression targets /
  promotion-IC inputs.

The deliverable is the ``(features-aligned X, target y, sample_weight w, t1, side)``
panel keyed on the sorted ``(ts_open, instrument_id)`` MultiIndex (``ts_open`` == the
decision bar τ) — the exact shape :class:`alphaforge.ml.datasets.MLDataset` and
``HistGBMMetaModel.fit`` read (build doc 09_ml.md §1.4: ``dataset.matrices(start, end)
-> (X, y, w, t1, side)``).

**The label is the target, never a feature (correctness rule, leakageCritique
finding 12).** A label looks into the future by construction — ``ret``, ``t1``,
``meta_label``, ``side`` and the ``fwd_ret_*`` columns are emitted ONLY in the
``y`` / ``t1`` / ``side`` outputs and the diagnostic frame; the assembler asserts the
feature matrix ``X`` shares no column with the label space (09_ml.md §3: "the feature
set ∩ {label columns} = ∅"), so a caller cannot accidentally feed a forward-looking
column to the GBM.

**meta_label is computed on the SIDE-SIGNED NET return (leakageCritique findings 2,
11).** The triple-barrier ``ret`` / ``ret_gross`` are ALREADY the trader-PnL of side
``s`` (``ret_gross = s·ln(exit/p0)``), so ``meta_label = 1{ ret > 0 }`` already equals
``1{ s·(raw move) > 0 }`` — the side is applied exactly once, in the labeler. We do
NOT re-apply ``s`` here (doing so would invert every short's label). :func:`make_meta_labels`
is a pass-through accessor so this column has ONE definition, computed on the cost-honest
``ret`` (the classifier learns ``P(net win)``, not ``P(gross win)``).

**Bet sizing is re-exported, never re-defined (leakageCritique findings 1, 6, 16).**
The López-de-Prado bet-size map :func:`bet_size_from_prob` is the seam Phase 12
multiplies by the alpha magnitude ``|Ã|`` and the HMM gate ``G`` to form
``F = size·|Ã|·G``. It SCALES/GATES the blend and NEVER flips its sign. There is a
single canonical implementation (in :mod:`alphaforge.ml.model`, with the
``p → 1 ⇒ |size| → 1`` clipping fix of finding 16); this module re-exports it so the
``alphaforge.labeling.meta`` surface the design promises resolves to that one
definition rather than a divergent copy.

**Cost-honesty bounds, but does not eliminate, overfit risk (overfit-critique item 8).**
The labels net fees + half-spread + expected funding but deliberately omit market
impact (size unknown at label time) and use a flat last-known funding rate over the
hold. Label-space win-rate is a development diagnostic; the binding economic check is
the gated walk-forward net of costs through the truth engine, never a barrier-label
hit rate. This assembler produces the *development* dataset — its quality gate lives
downstream.

This module never mutates its inputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from alphaforge.labeling.forward_returns import forward_returns
from alphaforge.labeling.triple_barrier import TripleBarrierConfig, apply_triple_barrier
from alphaforge.labeling.weights import sample_weights
from alphaforge.ml.model import bet_size_from_prob

if TYPE_CHECKING:
    from alphaforge.core.instruments import Instrument
    from alphaforge.costs.model import TransactionCostModel

__all__ = [
    "DEFAULT_FORWARD_HORIZONS",
    "MetaLabelDataset",
    "bet_size_from_prob",
    "make_meta_label_dataset",
    "make_meta_labels",
]

#: Index level names shared with the §1.3 label frame and the feature panel.
_INDEX_NAMES: Final[tuple[str, str]] = ("ts_open", "instrument_id")

#: Fixed-horizon forward-return targets (§5.1) attached as auxiliary regression /
#: promotion-IC columns; bars in the model's X are the §3 processed feature surface.
DEFAULT_FORWARD_HORIZONS: Final[tuple[int, ...]] = (24, 72, 168)

#: Columns that look into the future — emitted as targets / interval bounds ONLY and
#: forbidden from the feature matrix ``X`` (09_ml.md §3 disjointness invariant).
_LABEL_SPACE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "entry_ts",
        "entry_price",
        "t1",
        "exit_price",
        "ret_gross",
        "ret",
        "label_tb",
        "touch",
        "side",
        "meta_label",
        "vol_at_entry",
        "n_funding",
    }
)


def make_meta_labels(labels: pd.DataFrame) -> pd.Series:
    """The binary meta-label ``y_meta = 1{ net ret > 0 }`` (alphaDesign.md §5.3).

    A pass-through accessor onto the §1.3 triple-barrier frame so the ``meta_label``
    column has exactly ONE definition. The triple-barrier ``ret`` is ALREADY the
    SIDE-SIGNED cost-honest trader return (``ret = s·ln(exit/p0) - costs - funding``),
    so the label is ``1{ ret > 0 }`` with the side applied once (in the labeler) — we
    do NOT multiply by ``side`` again (leakageCritique finding 2: double-applying ``s``
    would invert every short). It is computed on the cost-honest ``ret``, never
    ``ret_gross`` (finding 11: the classifier learns ``P(net win)``).

    Unresolved events carry a NaN ``ret`` (missing entry / vol / path bar — the
    triple-barrier gap sentinel); those rows are masked to a NaN label here rather than
    silently coerced to 0, so the consumer drops them alongside the NaN-price rows.

    Parameters
    ----------
    labels:
        The §1.3 label frame from :func:`apply_triple_barrier`, indexed by the
        ``(ts_open, instrument_id)`` MultiIndex; needs the cost-honest ``ret`` column.

    Returns
    -------
    pd.Series
        ``meta_label`` on ``labels``' index — ``Int8`` (nullable) with ``1`` / ``0``
        for resolved events and ``pd.NA`` where ``ret`` is NaN.
    """
    if "ret" not in labels.columns:
        raise ValueError("labels is missing the cost-honest 'ret' column")
    ret = labels["ret"].to_numpy(dtype=float)
    resolved = np.isfinite(ret)
    win = (ret > 0.0).astype("int8")
    out = pd.array(win, dtype="Int8")
    out[~resolved] = pd.NA  # NaN ret -> masked label (dropped by the consumer)
    return pd.Series(out, index=labels.index, name="meta_label")


@dataclass(frozen=True, slots=True)
class MetaLabelDataset:
    """The assembled meta-label training panel (build doc 09_labeling.md §3, §4.3).

    All members are aligned 1:1 on the sorted ``(ts_open, instrument_id)`` MultiIndex of
    the *resolved, weighted* events (un-tradable NaN-price sentinels and unweighted rows
    are dropped). This is the panel :class:`alphaforge.ml.datasets.MLDataset` slices via
    ``matrices(start, end) -> (X, y, w, t1, side)`` and ``HistGBMMetaModel.fit`` trains
    on.

    Attributes:
        features: ``X`` — the decision-time feature matrix (the §3 processed engine
            surface the caller hands in), realigned to the resolved events. Disjoint
            from the label space by construction (asserted at build time).
        target: ``y`` — the binary :func:`make_meta_labels` (``int8``; only resolved
            rows survive, so it carries no NA).
        sample_weight: ``w`` — the AFML :func:`sample_weights` (uniqueness · decay ·
            cross-sectional de-correlation), float64 ≥ 0.
        t1: event-end ``ts_open`` (int64 epoch-ms) — REQUIRED by CV purging / embargo
            (the only forward-looking column the splitter is allowed to read).
        side: the primary-signal side ``s`` (int8 ∈ {-1, +1}) passed through from the
            events; the bet-size map re-signs by it, never flipping it.
        labels: the full §1.3 label frame restricted to the dataset rows — the
            diagnostic surface (``ret_gross``, ``touch``, ``vol_at_entry``,
            ``fwd_ret_*`` …). Targets ONLY; never feed any of these to a model.
        feature_names: the exact ``X`` column order pinned onto the
            :class:`~alphaforge.ml.model.HistGBMMetaModel` ``ModelCard`` for the fit.
    """

    features: pd.DataFrame
    target: pd.Series
    sample_weight: pd.Series
    t1: pd.Series
    side: pd.Series
    labels: pd.DataFrame
    feature_names: tuple[str, ...]

    def matrices(self) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
        """The ``(X, y, w, t1, side)`` tuple the meta-model fit consumes (09_ml.md §1.4)."""
        return self.features, self.target, self.sample_weight, self.t1, self.side


def make_meta_label_dataset(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    features: pd.DataFrame,
    cfg: TripleBarrierConfig,
    *,
    cost_model: TransactionCostModel,
    instruments: Mapping[str, Instrument],
    funding: pd.DataFrame | None = None,
    vol: pd.Series | None = None,
    feature_names: Sequence[str] | None = None,
    forward_horizons: Sequence[int] = DEFAULT_FORWARD_HORIZONS,
    time_decay: float = 0.75,
) -> MetaLabelDataset:
    """Assemble the full ``(features-aligned, target, sample_weight)`` meta-label panel.

    The composition (build doc 09_labeling.md §3, alphaDesign.md §5.2-§5.4):

    1. **Label** the events with the cost-honest, gap-aware triple barrier
       (:func:`apply_triple_barrier`) → the §1.3 frame with ``ret`` (net), ``t1``,
       ``side``, ``meta_label`` …
    2. **Weight** the resolved events (:func:`sample_weights`) → AFML uniqueness · decay
       · cross-sectional ``1/√(n_t)`` de-correlation.
    3. **Forward returns** (:func:`forward_returns`) at the fixed §5.1 horizons, joined
       as auxiliary regression / promotion-IC targets (and the vol-scaled 72-bar one).
    4. **Align** the supplied decision-time feature matrix ``features`` to the resolved,
       weighted rows and pin the column order.

    Only events that (a) resolved to a tradable label (non-NaN ``ret`` / ``entry_price``
    / ``t1``) AND (b) earned a finite ``sample_weight`` AND (c) have a feature row at
    their decision τ survive — an inner alignment, never a positional or bridged join.

    The feature matrix is asserted disjoint from the label space (09_ml.md §3): no
    ``ret``, ``t1``, ``side``, ``meta_label`` or any §1.3 column may enter ``X``, so a
    forward-looking column cannot leak into the model's inputs.

    Parameters
    ----------
    bars:
        Long OHLC panel (``instrument_id``, ``ts_open`` int64 epoch-ms, ``open``,
        ``high``, ``low``, ``close``) — the labeler's price source and the open→open
        return source for the weights. Never mutated.
    events:
        One row per decision: ``ts`` (decision τ's ``ts_open``), ``instrument_id``,
        ``side`` (int8 ∈ {-1, +1}). Dead-zone filtering of weak signals is the signal
        layer's job upstream; this labels exactly the events handed in.
    features:
        The decision-time feature matrix on the ``(ts_open, instrument_id)`` MultiIndex
        — the §3 processed engine surface (post-CSPipeline directional alphas  and  raw
        ``direction==0`` risk/regime context). Realigned to the resolved events; never
        mutated.
    cfg:
        Triple-barrier geometry and cost knobs.
    cost_model, instruments, funding, vol:
        Passed verbatim to :func:`apply_triple_barrier` (the single shared cost model,
        instrument metadata, funding-events frame, optional externally-supplied sigma_hat).
    feature_names:
        Optional explicit ``X`` column order to pin (a subset of ``features``); defaults
        to ``features``' own column order. A name absent from ``features`` raises
        ``KeyError`` (no silent positional drift). Must be disjoint from the label space.
    forward_horizons:
        Fixed forward-return horizons (§5.1) attached as ``fwd_ret_{h}`` diagnostics; a
        ``fwd_ret_72_volscaled`` regression target is added when 72 is among them.
    time_decay:
        AFML time-decay floor passed to :func:`sample_weights` (newest 1.0, oldest
        ``time_decay``; 1.0 disables).

    Returns
    -------
    MetaLabelDataset
        The aligned ``(X, y, w, t1, side)`` panel plus the diagnostic label frame and
        the pinned feature-name order.
    """
    if not isinstance(features.index, pd.MultiIndex):
        raise ValueError("features must be indexed by a (ts_open, instrument_id) MultiIndex")
    if list(features.index.names) != list(_INDEX_NAMES):
        raise ValueError(
            f"features must be indexed by {list(_INDEX_NAMES)}; got {list(features.index.names)}"
        )

    names = tuple(features.columns) if feature_names is None else tuple(feature_names)
    missing = [c for c in names if c not in features.columns]
    if missing:
        raise KeyError(f"feature_names not in features: {sorted(missing)}")
    leaking = sorted(set(names) & _LABEL_SPACE_COLUMNS)
    if leaking:
        raise ValueError(
            f"feature matrix overlaps the label space (forward-looking leak): {leaking}"
        )

    # 1. Cost-honest triple-barrier labels (the §1.3 frame).
    labels = apply_triple_barrier(
        bars,
        events,
        cfg,
        cost_model=cost_model,
        instruments=instruments,
        funding=funding,
        vol=vol,
    )

    # 2. AFML sample weights on the resolved events (the composer drops NaN-t1 rows).
    weights = sample_weights(labels, bars, time_decay=time_decay, timeframe=cfg.timeframe)

    # 3. Fixed-horizon forward returns (§5.1) — auxiliary diagnostics / promotion-IC.
    fwd_frames: list[pd.Series] = []
    for h in forward_horizons:
        fwd_frames.append(forward_returns(bars, h, timeframe=cfg.timeframe))
    if 72 in tuple(forward_horizons):
        fwd_frames.append(
            forward_returns(bars, 72, vol_scaled=True, timeframe=cfg.timeframe)
        )

    # The dataset rows are the events that resolved AND earned a finite weight: an inner
    # alignment of the labels' decision index with the weight index (never bridged).
    resolved_idx = labels.index[labels["ret"].notna() & labels["entry_price"].notna()]
    weight_idx = weights.index[np.isfinite(weights.to_numpy(dtype=float))]
    keep = resolved_idx.intersection(weight_idx)
    # Feature rows must exist at the decision τ — inner-join against the feature panel.
    keep = keep.intersection(features.index).sort_values()

    labels_kept = labels.loc[keep]
    target = make_meta_labels(labels_kept)
    # Resolved rows have a finite ret, so the mask carries no NA; pin to int8.
    target = pd.Series(
        target.to_numpy(dtype="int8", na_value=np.int8(0)),
        index=keep,
        name="meta_label",
        dtype="int8",
    )
    weight = weights.reindex(keep).astype("float64")
    weight.name = "sample_weight"
    t1 = labels_kept["t1"].astype("int64").rename("t1")
    side = labels_kept["side"].astype("int8").rename("side")

    x = features.loc[keep, list(names)].copy()

    # Attach the forward-return diagnostics to the label frame (targets, never features).
    # forward_returns already names each Series (``fwd_ret_{h}`` / ``..._volscaled``).
    diag = labels_kept.copy()
    for fwd in fwd_frames:
        diag = diag.join(fwd.reindex(keep))

    return MetaLabelDataset(
        features=x,
        target=target,
        sample_weight=weight,
        t1=t1,
        side=side,
        labels=diag,
        feature_names=names,
    )
