"""Gate adapters — wire the Phase-9 meta-model + Phase-11 regime gate into the
blend (Phase 12; ``docs/design/build/12_FINAL.md`` D1/D2/D4/D7).

This is the ONLY new module in :mod:`alphaforge.signals`. It depends on Phase 9
(:mod:`alphaforge.ml`) and Phase 11 (:mod:`alphaforge.regime`) ONLY through their
frozen Protocols (:class:`~alphaforge.ml.model.MetaModel`,
:class:`~alphaforge.regime.hmm.RegimeGate`) and never edits them. Three pure,
deterministic, sign-safe functions plus the shared train/serve feature assembly:

* :func:`assemble_meta_features` — THE single train/serve feature surface (D4 /
  CRITIQUE_leakage #15): directional-alpha names resolve to the PROCESSED,
  direction-signed ``zs`` panel; ``direction==0`` risk/regime context names
  resolve to the RAW engine ``frame`` column. Training (the Phase-9 dataset
  builder) and serve (:meth:`SignalService.compute_research_gated`) BOTH call
  this, so the X at decision bar ``t`` is byte-identical on both paths.
* :func:`apply_meta_gate` — ``F̃ = Ã·|size|``, magnitude-only (D1 /
  CRITIQUE_leakage #1). ``side = sign(Ã)``; ``|size|`` from
  ``meta.bet_size(x, side)`` ∈ [0, 1]. There is NO ``cs_zscore`` after gating —
  re-z-scoring would subtract a non-zero cross-sectional mean of ``F`` and could
  flip a small-``|size|`` positive name below the mean to negative, the exact
  sign-flip the critique killed. Because ``|size| ≥ 0``, ``sign(F̃) == sign(Ã)``
  or ``0`` BY CONSTRUCTION — the gate scales, never flips.
* :func:`apply_regime_gate` — broadcast the daily ``G`` (already lagged once by
  the producer) to the hourly ``mu_ann`` rows via ONE backward
  :func:`pandas.merge_asof` on ``ts_open`` (D2 / CRITIQUE_leakage #4), keyed on
  the day-``D`` ``ts_open`` the gate APPLIES TO — NOT on ``available_at``, and
  with NO second shift. Cold-start rows (before the first available gate day) get
  ``G = 1.0`` (never NaN — a missing regime read must not zero the book).

OFF == identity, byte-for-byte (D7): under :class:`~alphaforge.ml.model.IdentityMeta`
(``|size| ≡ 1``) and an all-ones ``g_series`` (:class:`~alphaforge.regime.hmm.IdentityRegime`),
the output of every function is the input unchanged — the gates multiply by 1.0,
no numeric perturbation. The pinned regression test asserts frame equality.

Pure and deterministic; inputs are never mutated. All timestamps are epoch-ms
:data:`alphaforge.core.time.Ms` (int64); never a ``DatetimeIndex`` /
``pd.Timestamp`` (CRITIQUE_leakage #5).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Re-export the identity gates so callers (the runner, the live hook) construct the
# OFF path through ONE import surface — the gates are the seam, not ml/regime directly.
from alphaforge.ml.model import IdentityMeta, MetaModel
from alphaforge.regime.hmm import IdentityRegime, RegimeGate
from alphaforge.signals.blending import ALPHA_BLEND_COLUMN

# THE single train/serve feature surface lives in ``features_serve`` (D4 / leakage
# #15). Re-export it here (no second definition) so "THE single surface" is literally
# ONE function — both production paths (the Phase-9 dataset builder and the runner's
# serve gate) and ``test_gating`` reference the same object, and a future edit cannot
# silently diverge two copies while tests stay green.
from alphaforge.signals.features_serve import assemble_meta_features

__all__ = [
    "REGIME_GATE_COLUMN",
    "IdentityMeta",
    "IdentityRegime",
    "MetaModel",
    "RegimeGate",
    "apply_meta_gate",
    "apply_regime_gate",
    "assemble_meta_features",
]

REGIME_GATE_COLUMN: str = "regime_gate"
"""Internal column name for the broadcast daily gross multiplier ``G`` (the name
:meth:`RegimeHMM.gross_multiplier_series` already stamps on its Series)."""

_TS_OPEN_LEVEL: str = "ts_open"
"""The first level of the ``(ts_open, instrument_id)`` panel MultiIndex."""


def apply_meta_gate(
    a_tilde: pd.Series,
    x: pd.DataFrame | None,
    meta: MetaModel,
    mask: pd.Series,
) -> pd.Series:
    """``F̃ = Ã·|size|`` — magnitude-only gating that NEVER flips (D1 / #1).

    ``side = sign(Ã)``; ``|size| = abs(meta.bet_size(x, side))`` ∈ [0, 1] (the
    bet-size map floors below ``P_MIN`` to 0 and carries ``sign == side``). The
    gated signal is the per-name product ``Ã·|size|`` — there is NO ``cs_zscore``
    and NO re-standardization (re-z-scoring subtracts a non-zero cross-sectional
    mean of ``F`` and can flip a small-``|size|`` positive name negative; that is
    the bug CRITIQUE_leakage #1 killed). Because ``|size| ≥ 0``,
    ``sign(F̃) == sign(Ã)`` or ``0`` by construction.

    Args:
        a_tilde: The ungated blend ``Ã`` (the sign source), on the
            ``(ts_open, instrument_id)`` MultiIndex. Carries the strict NaN
            discipline of :func:`~alphaforge.signals.blending.blend` (non-members
            and partially-informed rows are already NaN).
        x: The assembled features (from :func:`assemble_meta_features`), aligned
            to ``a_tilde.index``. ``None`` (the model has no ``feature_names``)
            short-circuits to ``|size| ≡ 1`` ⇒ ``F̃ == Ã`` (the OFF path).
        meta: The frozen meta-model seam. With
            :class:`~alphaforge.ml.model.IdentityMeta`, ``|size| ≡ 1`` so
            ``F̃ == Ã`` exactly (D7).
        mask: PIT membership per row; NaN ``Ã`` rows (non-members) stay NaN
            because ``NaN·anything = NaN`` — the gate cannot resurrect a name the
            blend dropped.

    Returns:
        The gated float Series ``F̃`` aligned to ``a_tilde.index`` (NaN-preserving).
    """
    if x is None:
        # No model features ⇒ identity gate; return Ã unchanged (no perturbation).
        return a_tilde.copy()
    side = pd.Series(np.sign(a_tilde.to_numpy(dtype=float)), index=a_tilde.index, name="side")
    size = meta.bet_size(x, side).reindex(a_tilde.index)
    magnitude = size.abs().to_numpy(dtype=float)
    # `mask` is documented as the PIT membership the caller passes; NaN Ã already
    # encodes non-membership (blend NaN'd them), so the product is NaN-preserving.
    # The reference here keeps the signature honest for callers that gate a panel
    # whose Ã has been re-materialized; it never widens membership.
    del mask
    values = a_tilde.to_numpy(dtype=float) * magnitude
    return pd.Series(values, index=a_tilde.index, name=a_tilde.name, dtype=float)


def apply_regime_gate(
    mu_ann: pd.Series,
    g_series: pd.Series,
) -> pd.Series:
    """Broadcast the daily ``G`` to hourly ``mu_ann`` rows (D2 / #4).

    The daily ``g_series`` from
    :meth:`~alphaforge.regime.hmm.RegimeHMM.gross_multiplier_series` is ALREADY
    lagged once and keyed by the day-``D`` ``ts_open`` it applies to. Broadcast it
    to the hourly ``(ts_open, instrument_id)`` rows with ONE backward
    :func:`pandas.merge_asof` on ``ts_open`` (``allow_exact_matches=True``): the
    most-recent day-``D`` ``ts_open ≤ hour_ts`` is exactly the gate for the day
    containing the hour. Key on the day-``D`` ``ts_open`` (the gate's own index),
    NOT on ``available_at``, and do NOT ``shift`` again (the producer lagged once).

    Rows before the first available gate day (cold start) get ``G = 1.0``
    (``fillna``) — never NaN; a missing regime read must not zero the book. With an
    all-1.0 ``g_series`` (:class:`~alphaforge.regime.hmm.IdentityRegime`) the result
    equals ``mu_ann`` exactly (D7).

    Because ``G ∈ (0, 1]`` only shrinks, ``|mu_ann_gated| ≤ |mu_ann|`` everywhere
    and the optimizer's ``|mu_ann| < 3.0`` tripwire can only get safer (μ-contract,
    rule 5).

    Args:
        mu_ann: The (post-meta) ``mu_ann`` on the hourly
            ``(ts_open, instrument_id)`` MultiIndex.
        g_series: The daily gross multiplier ``G`` keyed by day-``D`` ``ts_open``
            (int64 epoch-ms), already lagged once by the producer.

    Returns:
        ``mu_ann · G`` as a float Series aligned to ``mu_ann.index`` (NaN ``mu_ann``
        rows stay NaN; ``G`` is never NaN after the cold-start fill).
    """
    # The unique, sorted hourly ts_open keys: merge_asof needs a sorted left frame
    # and the gate is daily (one G per ts_open), so we resolve G per DISTINCT hour
    # ts_open once, then map it back to every (ts_open, instrument_id) row. This
    # avoids the per-instrument `by=` blow-up — every instrument in a day shares G_d.
    hour_ts = mu_ann.index.get_level_values(_TS_OPEN_LEVEL).to_numpy(dtype=np.int64)
    unique_ts = np.unique(hour_ts)  # sorted ascending

    right = pd.DataFrame(
        {
            _TS_OPEN_LEVEL: g_series.index.to_numpy(dtype=np.int64),
            REGIME_GATE_COLUMN: g_series.to_numpy(dtype=float),
        }
    ).sort_values(_TS_OPEN_LEVEL, kind="stable")

    left = pd.DataFrame({_TS_OPEN_LEVEL: unique_ts})
    merged = pd.merge_asof(
        left,
        right,
        on=_TS_OPEN_LEVEL,
        direction="backward",
        allow_exact_matches=True,
    )
    # Cold start (no day-D gate at or before this hour) -> permissive 1.0, never NaN.
    g_per_ts = merged[REGIME_GATE_COLUMN].fillna(1.0).to_numpy(dtype=float)

    # Broadcast the per-unique-ts G back onto every panel row by ts_open position.
    pos = np.searchsorted(unique_ts, hour_ts)
    g_row = g_per_ts[pos]
    out = mu_ann.to_numpy(dtype=float) * g_row
    return pd.Series(out, index=mu_ann.index, name=mu_ann.name, dtype=float)


def gate_signal_frame(
    signal_frame: pd.DataFrame,
    feature_frame: pd.DataFrame | None,
    meta: MetaModel,
    g_series: pd.Series,
    sigma: pd.Series,
    *,
    mu_ann_from_blend: bool = True,
) -> pd.DataFrame:
    """Apply BOTH gates to a ``[alpha_blend, mu_ann]`` frame (D1 then D2).

    The combined gate convenience the spec names: meta-gate the blend ``Ã``
    (magnitude-only, D1), recompute ``mu_ann`` from the gated ``F̃`` by LINEARITY
    (``mu_ann`` is linear in ``F̃`` — :class:`~alphaforge.signals.sizing.GrinoldSizer`),
    then regime-gate ``mu_ann`` (D2). The reported ``alpha_blend`` column keeps the
    UNGATED ``Ã`` (the audit/IC quantity); the gate's entire effect lives in
    ``mu_ann`` (12_FINAL.md D1).

    By linearity, ``mu_ann_gated = mu_ann_blend · |size| · G`` exactly equals
    ``GrinoldSizer.mu_ann(Ã·|size|, sigma) · G``; we use the multiply form (one
    vector op per gate) when ``mu_ann_from_blend`` is True to avoid a second
    ``mu_ann`` call and to GUARANTEE byte-for-byte identity on the OFF path (the
    blend ``mu_ann`` already in ``signal_frame`` is multiplied by 1.0 under
    IdentityMeta + IdentityRegime, with no recompute that could perturb the last
    ULP). With both identity gates the returned frame equals ``signal_frame``.

    Args:
        signal_frame: ``[alpha_blend, mu_ann]`` on the
            ``(ts_open, instrument_id)`` MultiIndex (the blend output).
        feature_frame: Assembled meta features (from
            :func:`assemble_meta_features`); ``None`` ⇒ identity meta gate.
        meta: The frozen meta-model seam.
        g_series: The daily lagged gross multiplier (see :func:`apply_regime_gate`).
        sigma: The per-bar EWMA sigma_hat aligned to the panel (UNUSED when
            ``mu_ann_from_blend`` is True; kept for the linearity-equivalence
            contract and a future recompute path).
        mu_ann_from_blend: When True (default), multiply the existing blend
            ``mu_ann`` by ``|size|`` (the linearity equivalence). The arg exists so
            the equivalence is explicit and testable; the recompute branch is not
            needed by the runner.

    Returns:
        A new ``[alpha_blend (ungated Ã), mu_ann (gated)]`` frame on
        ``signal_frame.index``.
    """
    from alphaforge.signals.sizing import MU_ANN_COLUMN  # local: avoid import cycle

    a_tilde = signal_frame[ALPHA_BLEND_COLUMN]
    mu_ann = signal_frame[MU_ANN_COLUMN]

    if feature_frame is None:
        magnitude = pd.Series(1.0, index=a_tilde.index)
    else:
        side = pd.Series(np.sign(a_tilde.to_numpy(dtype=float)), index=a_tilde.index, name="side")
        magnitude = meta.bet_size(feature_frame, side).reindex(a_tilde.index).abs()

    del sigma  # documented signature; the multiply (linearity) form needs no recompute
    if not mu_ann_from_blend:  # pragma: no cover - the recompute path is unused
        raise NotImplementedError(
            "recompute path is the linearity reference only; use mu_ann_from_blend=True"
        )
    mu_gated = apply_regime_gate(mu_ann * magnitude, g_series)
    return pd.DataFrame(
        {ALPHA_BLEND_COLUMN: a_tilde, MU_ANN_COLUMN: mu_gated}, index=signal_frame.index
    )
