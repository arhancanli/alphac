"""The ONE shared train/serve feature-assembly surface (Phase 12, D4; leakage #15).

The Phase-9 meta-model's X matrix is the engine's **processed decision-time
surface**, NOT the raw engine frame. The original ``12_integration.md`` body
``x = frame[feature_names]`` is WRONG (12_FINAL.md §D4): it would hand the GBM the
*raw* factor values for the directional alphas at serve time, while training saw
the *processed* (winsorize → zscore, PIT-masked, ``direction``-signed) ``zs``
panel — a silent train/serve skew that the model would learn around and then mis-
apply live.

:func:`assemble_meta_features` is the single helper both paths call, so the X at
decision bar ``t`` is byte-identical on train and serve (the parity invariant
``tests/unit/test_feature_serve_parity.py`` pins). Per name, in
``feature_names`` order (09_ml.md §3):

* **directional alphas** (``direction != 0``) — present in ``zs`` — resolve to the
  PROCESSED, ``direction``-signed z column (``cross_sectional=True`` ones arrive
  POST-CSPipeline; the rest mask-only). These also drive the blend side ``s``.
* **risk / regime context** (``direction == 0``) — absent from ``zs`` — resolve to
  the RAW engine column ``frame[name]`` (the model learns *when the side works
  given the regime*, §6.1).

Membership of each set is decided by *presence in* ``zs`` (the service's
``_directional_zs`` produces exactly one ``zs`` entry per directional alpha), never
a hardcoded list — so adding/removing an alpha cannot drift the resolution. A
``feature_names`` entry absent from BOTH ``zs`` and ``frame`` is a loud
``KeyError`` (no silent positional drift; 09_ml.md §3).

Pure and deterministic; inputs are never mutated. ``ts_open`` keys stay int64
epoch-ms — this module never constructs a ``pd.Timestamp`` / ``DatetimeIndex``
(leakage #5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["assemble_meta_features"]


def assemble_meta_features(
    frame: pd.DataFrame,
    zs: Mapping[str, pd.Series],
    feature_names: tuple[str, ...],
) -> pd.DataFrame:
    """THE single train/serve feature surface (12_FINAL.md §D4 / leakage #15).

    For each name in ``feature_names``: if it is a directional-alpha name present
    in ``zs``, take the PROCESSED, ``direction``-signed z column from ``zs``;
    otherwise take the RAW engine column from ``frame[name]`` (the
    ``direction == 0`` risk/regime context). A name absent from BOTH is a
    ``KeyError`` — never a silent positional fill.

    Used IDENTICALLY by the Phase-9 dataset builder (training) and by
    ``SignalService`` serve (Phase 12), so the X at decision bar ``t`` is byte-
    identical on both paths.

    Parameters
    ----------
    frame:
        The engine output frame (RAW columns) on the ``(ts_open, instrument_id)``
        MultiIndex — the same frame ``SignalService._panel`` returns. Supplies the
        ``direction == 0`` context columns and the index/dtype reference. Never
        mutated.
    zs:
        The PROCESSED directional-z panel — exactly ``SignalService._directional_zs``'s
        output: one ``pd.Series`` per directional alpha, ``direction``-signed and
        PIT-masked (non-members NaN), aligned to ``frame.index``. Presence here is
        what marks a name as a directional alpha (vs raw context).
    feature_names:
        The model's pinned column order (``ModelProtocol.feature_names`` /
        ``ModelCard.feature_names``). The output columns are EXACTLY this, in this
        order, so serve-time X realigns to the trained column order rather than
        positionally assuming it.

    Returns
    -------
    pd.DataFrame
        A float frame on ``frame.index`` (the ``(ts_open, instrument_id)``
        MultiIndex) with columns exactly ``feature_names`` in order. Directional
        columns carry their ``zs`` (processed, signed) values; context columns carry
        their raw ``frame`` values. Both train and serve route through here, so the
        two surfaces are identical for an overlapping span (the parity invariant).
    """
    if not isinstance(frame.index, pd.MultiIndex) or list(frame.index.names) != [
        "ts_open",
        "instrument_id",
    ]:
        raise ValueError(
            "frame must be indexed by a 2-level (ts_open, instrument_id) MultiIndex; "
            f"got names {list(frame.index.names)}"
        )

    columns: dict[str, pd.Series] = {}
    for name in feature_names:
        if name in zs:
            # Directional alpha: the PROCESSED, direction-signed z (post-CSPipeline,
            # PIT-masked) — the surface training saw, NOT the raw frame[name].
            series = zs[name].reindex(frame.index)
        elif name in frame.columns:
            # direction==0 risk/regime context: fed RAW from the engine frame.
            series = frame[name]
        else:
            raise KeyError(
                f"meta feature {name!r} is in neither the processed z panel nor the "
                "engine frame — feature set must be a subset of the engine surface "
                "(09_ml.md §3; no silent positional drift)"
            )
        columns[name] = series.astype("float64")

    # Build in feature_names order with an explicit column list so the order is the
    # model's pinned order regardless of dict-insertion quirks across versions.
    out = pd.DataFrame(columns, index=frame.index, dtype="float64")
    return out[list(feature_names)]
