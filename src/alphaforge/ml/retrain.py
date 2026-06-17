"""Purged retrain job + champion/challenger promotion (09_ml.md §1.4, §2).

The weekly retrain fits a challenger :class:`alphaforge.ml.model.HistGBMMetaModel`
on a rolling window, registers it, and decides whether it should replace the
champion. The promotion decision is the load-bearing leakage control (finding 9):
it is judged ONLY on data strictly after BOTH the champion's and the challenger's
fit+calibration windows — never on a tail either model fit or calibrated on.

Window discipline (finding 9 / 09_ml.md §2)::

    train      : [asof - window_days, es_start)     # GBM trees
    early-stop : 40d block (chooses n_iter)          # challenger GBM only
    isotonic   : 20d block (fits calibrator)         # challenger isotonic only
    promotion  : OOS window AFTER max(champ.fit_end, chall.fit_end) + embargo
                                                     # neither model's fit touched it

``fit_end`` is the last decision-bar ``t`` whose label ``t1 = t + horizon_bars·Δ``
is fully realized (``<= asof``); :func:`build_fit_windows` carves it from THE single
shared horizon constant ``settings.signals.horizon_bars`` (never a local literal).

Promotion gate (finding 9 + CRITIQUE_leakage finding 10):

* Cold start (no champion): promote, ``reason='cold-start'``.
* Else the shared OOS window must hold ``>= min_oos`` events, otherwise
  ``reason='insufficient-oos'`` and the champion stays — NO fallback to a
  contaminated tail.
* The promotion IC is **direction-consistent** (finding 10): ``predict_proba`` is
  a sign-less confidence, so correlating raw ``p`` against a side-less forward
  return is meaningless. We gate on ``rank_ic(size, ret_signed)`` — the SIGNED bet
  size (``side·(2Φ(z)-1)``) against the SIDE-SIGNED realized net return — on the
  non-overlapping ``h``-bar grid (the :func:`alphaforge.validation.metrics.
  non_overlapping` machinery the live service uses), plus a weighted log-loss
  comparison. Promote iff ``logloss_new <= logloss_champ + tol`` AND
  ``rank_ic_new >= ic_keep_frac · rank_ic_champ``.

CRITIQUE_overfit findings 2/5: each promotion decision is a TRIAL. The
``trial_config`` hashed into the :class:`alphaforge.validation.experiments.
ExperimentLog` includes the model hyperparameters, the feature-set hash, the gate
constants, and the realized window bounds — so retuning ANY knob creates a new
trial and the DSR ``N`` cannot silently ratchet. The label-space gate here is
NECESSARY but not the binding economic check: per finding 5/12 the binding gate is
the Phase-12 gated walk-forward net-of-cost PnL vs the blend-only baseline. This
module's verdict therefore carries ``label_space_only=True`` so a caller never
mistakes a label-space pass for a deployment decision.

Pure of clock: ``asof`` is passed in (the :mod:`alphaforge.validation.experiments`
discipline). Deterministic given inputs + seeds.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import numpy as np
import pandas as pd

from alphaforge.core.time import Timeframe
from alphaforge.ml.model import (
    EARLY_STOP_DAYS,
    ISOTONIC_DAYS,
    FitWindows,
    HistGBMMetaModel,
    bet_size_from_prob,
)
from alphaforge.validation.experiments import ExperimentLog
from alphaforge.validation.metrics import non_overlapping, rank_ic

if TYPE_CHECKING:
    from alphaforge.config.settings import Settings
    from alphaforge.core.time import Ms
    from alphaforge.ml.registry import ModelCard, ModelRegistry

__all__ = [
    "EARLY_STOP_DAYS",
    "ISOTONIC_DAYS",
    "MLDataset",
    "PromotionVerdict",
    "build_fit_windows",
    "dataset_content_sha",
    "judge_promotion",
    "weekly_retrain",
]

_MS_PER_DAY: Final[int] = 86_400_000
"""Epoch-ms in one UTC day (24/7 market, no DST) — the window-carving unit."""

DEFAULT_WINDOW_DAYS: Final[int] = 365
"""Rolling training-window length in days (09_ml.md §1.4)."""

DEFAULT_EMBARGO_BARS: Final[int] = 720
"""Promotion-window embargo in bars after both fit ends (CRITIQUE_leakage finding
12: the embargo must be >= the dominant slow-feature lookback that enters the
model, ~720 bars, not the splitter's 168 default, so test-block feature serial
correlation cannot bleed into the judged window)."""

DEFAULT_LOGLOSS_TOL: Final[float] = 0.002
"""Promotion log-loss tolerance: ``logloss_new <= logloss_champ + tol`` (§1.4)."""

DEFAULT_IC_KEEP_FRAC: Final[float] = 0.8
"""Promotion rank-IC floor: ``rank_ic_new >= ic_keep_frac · rank_ic_champ`` (§1.4)."""

DEFAULT_MIN_OOS: Final[int] = 200
"""Minimum events in the shared OOS window; below this -> ``insufficient-oos``
(finding 9: never borrow a contaminated tail to manufacture a verdict)."""


class MLDataset(Protocol):
    """The X/y/w/t1/side aligner (09_ml.md §1.4; full spec is ``ml/datasets.py``).

    Phase 9 consumes it as a seam: :meth:`matrices` returns the decision-time
    feature matrix and the label contract over ``[start, end]``, all on the shared
    ``(ts_open, instrument_id)`` MultiIndex. ``side`` is the blend side
    ``s = sign(Ã)`` per row; ``ret_signed`` is the SIDE-SIGNED realized net return
    (the label layer's ``ret`` — net of fees + half-spread + funding) used by the
    direction-consistent promotion IC (finding 10). ``label_is_net`` carries the
    cost-honesty provenance (finding 11).
    """

    def matrices(
        self, start: Ms, end: Ms
    ) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
        """``(X, y, w, t1, side)`` over decision bars in ``[start, end]``."""
        ...

    def ret_signed(self, start: Ms, end: Ms) -> pd.Series:
        """Side-signed realized NET return per event over ``[start, end]`` (finding 10)."""
        ...

    @property
    def label_is_net(self) -> bool:
        """Cost-honesty provenance of the label frame (finding 11)."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionVerdict:
    """The judged challenger-vs-champion comparison (finding 9).

    Metrics are computed on the OOS window strictly after BOTH models'
    fit+calibration windows: ``oos_start = max(champion.fit_end, challenger.fit_end)
    + embargo_bars·Δ``. ``promote`` is the label-space verdict; ``label_space_only``
    is always ``True`` to flag (finding 5/12) that the BINDING deployment gate is
    the Phase-12 gated walk-forward net-of-cost PnL vs the blend baseline, not these
    label-space metrics. ``n_oos`` is the event count in the judged window.
    """

    promote: bool
    oos_start: Ms
    oos_end: Ms
    n_oos: int
    challenger_logloss: float
    champion_logloss: float | None
    challenger_rank_ic: float
    champion_rank_ic: float | None
    reason: str
    label_space_only: bool = True


def build_fit_windows(
    asof: Ms,
    *,
    horizon_bars: int,
    window_days: int = DEFAULT_WINDOW_DAYS,
    es_days: int = EARLY_STOP_DAYS,
    iso_days: int = ISOTONIC_DAYS,
    bar_ms: int = Timeframe.H1.ms,
) -> FitWindows:
    """Carve ``[asof - window_days, asof]`` into train / ``es_days`` ES / ``iso_days`` iso.

    ``fit_end`` is the last decision bar ``t`` whose label ``t1 = t + horizon_bars·Δ``
    is fully realized (``t1 <= asof``), i.e. ``fit_end = asof - horizon_bars·bar_ms``
    — so no unrealized label can enter the fit (09_ml.md test
    ``test_build_fit_windows_realized_only``). The isotonic block is the trailing
    ``iso_days`` ending at ``fit_end``; the ES block the ``es_days`` before it; train
    is everything from ``asof - window_days`` up to the ES block.

    ``horizon_bars`` is THE single shared constant (``settings.signals.horizon_bars``);
    ``bar_ms`` is the decision-bar width Δ (1h by default). Raises ``ValueError`` for
    non-positive day counts or a window too short to carve strictly-increasing bounds.
    """
    if window_days <= 0 or es_days <= 0 or iso_days <= 0:
        raise ValueError(f"window/es/iso days must be > 0; got {window_days}/{es_days}/{iso_days}")
    if horizon_bars <= 0:
        raise ValueError(f"horizon_bars must be > 0; got {horizon_bars}")

    fit_end: Ms = int(asof) - horizon_bars * bar_ms
    iso_start: Ms = fit_end - (iso_days - 1) * _MS_PER_DAY
    es_start: Ms = iso_start - es_days * _MS_PER_DAY
    train_start: Ms = int(asof) - window_days * _MS_PER_DAY
    if not (train_start < es_start < iso_start <= fit_end):
        raise ValueError(
            f"window_days={window_days} too short to carve train/{es_days}d ES/"
            f"{iso_days}d isotonic before fit_end; got bounds "
            f"{train_start} / {es_start} / {iso_start} / {fit_end}"
        )
    return FitWindows(
        train_start=train_start, es_start=es_start, iso_start=iso_start, fit_end=fit_end
    )


def dataset_content_sha(
    X: pd.DataFrame, y: pd.Series, w: pd.Series, t1: pd.Series, windows: FitWindows
) -> str:
    """Content SHA-256 of the MATERIALIZED training matrices (CRITIQUE_leakage finding 18).

    There is no training parquet in the walk-forward in-memory path, so the
    reproducibility stamp hashes the SORTED ``(X, y, w, t1)`` content + feature
    names + window bounds — computed identically in the live and WF paths, so a
    re-fit on the same data yields the same ``data_sha256``. Sorting by index makes
    the hash invariant to row order.
    """
    order = X.index
    sorted_X = X.sort_index()
    digest = hashlib.sha256()
    digest.update(json.dumps([str(c) for c in sorted_X.columns]).encode("ascii"))
    digest.update(
        json.dumps(
            [windows.train_start, windows.es_start, windows.iso_start, windows.fit_end]
        ).encode("ascii")
    )
    digest.update(np.ascontiguousarray(sorted_X.to_numpy(dtype=np.float64)).tobytes())
    digest.update(
        np.ascontiguousarray(y.reindex(order).sort_index().to_numpy(dtype=np.float64)).tobytes()
    )
    digest.update(
        np.ascontiguousarray(w.reindex(order).sort_index().to_numpy(dtype=np.float64)).tobytes()
    )
    digest.update(
        np.ascontiguousarray(t1.reindex(order).sort_index().to_numpy(dtype=np.int64)).tobytes()
    )
    return digest.hexdigest()


def _trial_config(
    challenger: HistGBMMetaModel,
    *,
    window_days: int,
    embargo_bars: int,
    logloss_tol: float,
    ic_keep_frac: float,
    horizon_bars: int,
    data_sha256: str,
) -> dict[str, object]:
    """The hashed trial identity (CRITIQUE_overfit findings 2/5).

    Includes the model hyperparameters, a feature-set hash, the gate constants, and
    the realized data/window bounds — so retuning ANY knob (a param, the feature
    set, a gate threshold) is a DISTINCT trial and the DSR ``N`` cannot silently
    ratchet across weekly retrains.
    """
    feature_hash = hashlib.sha256(
        json.dumps(list(challenger.feature_names)).encode("ascii")
    ).hexdigest()[:16]
    params = {k: str(v) for k, v in sorted(challenger._params.items())}
    return {
        "kind": "ml_meta_retrain_promotion",
        "params": params,
        "feature_set_sha": feature_hash,
        "n_features": len(challenger.feature_names),
        "best_n_iter": challenger.best_n_iter,
        "window_days": window_days,
        "embargo_bars": embargo_bars,
        "logloss_tol": logloss_tol,
        "ic_keep_frac": ic_keep_frac,
        "horizon_bars": horizon_bars,
        "fit_end": int(challenger.windows.fit_end),
        "data_sha256": data_sha256,
    }


def _oos_metrics(
    model: HistGBMMetaModel,
    dataset: MLDataset,
    oos_start: Ms,
    oos_end: Ms,
    *,
    horizon_bars: int,
    bar_ms: int,
) -> tuple[float, float, int]:
    """``(weighted_logloss, direction_consistent_rank_ic, n_events)`` on the OOS window.

    The IC is ``rank_ic(size, ret_signed)`` on the non-overlapping ``h``-bar grid
    (finding 10): the SIGNED bet size against the SIDE-SIGNED realized net return,
    so a real edge yields a positive IC and a sign-blind confidence does not. Both
    metrics use only ``ts_open >= oos_start`` rows.
    """
    from sklearn.metrics import log_loss

    X, y, w, _t1, side = dataset.matrices(oos_start, oos_end)
    if len(X.index) == 0:
        return float("nan"), float("nan"), 0
    proba = model.predict_proba(X)
    y_arr = y.reindex(X.index).to_numpy(dtype=np.float64)
    w_arr = w.reindex(X.index).to_numpy(dtype=np.float64)
    logloss = float(log_loss(y_arr, proba, sample_weight=w_arr, labels=[0.0, 1.0]))

    size = bet_size_from_prob(pd.Series(proba, index=X.index, name="p_win"), side.reindex(X.index))
    ret_signed = dataset.ret_signed(oos_start, oos_end).reindex(X.index)
    # Direction-consistent IC on the non-overlapping h-grid (finding 10): treat all
    # rows as universe members (the dataset already universe-masked at build time).
    universe = pd.Series(True, index=X.index, name="member")
    size_grid = non_overlapping(size, horizon_bars, delta_ms=bar_ms)
    ic = rank_ic(size_grid, ret_signed, universe.reindex(size_grid.index), min_members=2)
    finite_ic = ic.to_numpy(dtype=np.float64)
    finite_ic = finite_ic[np.isfinite(finite_ic)]
    mean_ic = float(finite_ic.mean()) if finite_ic.size else float("nan")
    return logloss, mean_ic, len(X.index)


def judge_promotion(
    challenger: HistGBMMetaModel,
    champion_card: ModelCard | None,
    dataset: MLDataset,
    settings: Settings,
    asof: Ms,
    *,
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
    logloss_tol: float = DEFAULT_LOGLOSS_TOL,
    ic_keep_frac: float = DEFAULT_IC_KEEP_FRAC,
    min_oos: int = DEFAULT_MIN_OOS,
    champion_model: HistGBMMetaModel | None = None,
    bar_ms: int = Timeframe.H1.ms,
) -> PromotionVerdict:
    """Promotion gate, judged ONLY on data after BOTH fit windows (finding 9).

    ``oos_start = max(champion.fit_end, challenger.fit_end) + embargo_bars·Δ`` so
    neither model's train/ES/isotonic span touches the judged window;
    ``oos_end = asof - horizon_bars·Δ`` (only fully-realized labels). Cold start
    (``champion_card is None``) auto-promotes (``reason='cold-start'``). Otherwise:

    * ``< min_oos`` events in the shared window -> ``promote=False``,
      ``reason='insufficient-oos'`` (NO fallback to a contaminated tail).
    * else promote iff ``logloss_new <= logloss_champ + logloss_tol`` AND
      ``rank_ic_new >= ic_keep_frac · rank_ic_champ`` (the direction-consistent IC,
      finding 10).

    ``champion_model`` is the loaded incumbent (needed to score the champion on the
    OOS window); when ``None`` and a champion card exists, the champion's metrics
    are read from its card as a conservative fallback and the reason records it.
    """
    horizon_bars = settings.signals.horizon_bars
    oos_end: Ms = int(asof) - horizon_bars * bar_ms
    chall_fit_end = int(challenger.windows.fit_end)

    if champion_card is None:
        oos_start: Ms = chall_fit_end + embargo_bars * bar_ms
        new_logloss, new_ic, n_oos = _oos_metrics(
            challenger, dataset, oos_start, oos_end, horizon_bars=horizon_bars, bar_ms=bar_ms
        )
        return PromotionVerdict(
            promote=True,
            oos_start=oos_start,
            oos_end=oos_end,
            n_oos=n_oos,
            challenger_logloss=new_logloss,
            champion_logloss=None,
            challenger_rank_ic=new_ic,
            champion_rank_ic=None,
            reason="cold-start",
        )

    oos_start = max(int(champion_card.fit_end), chall_fit_end) + embargo_bars * bar_ms
    new_logloss, new_ic, n_oos = _oos_metrics(
        challenger, dataset, oos_start, oos_end, horizon_bars=horizon_bars, bar_ms=bar_ms
    )

    if n_oos < min_oos or oos_start > oos_end:
        return PromotionVerdict(
            promote=False,
            oos_start=oos_start,
            oos_end=oos_end,
            n_oos=n_oos,
            challenger_logloss=new_logloss,
            champion_logloss=None,
            challenger_rank_ic=new_ic,
            champion_rank_ic=None,
            reason="insufficient-oos",
        )

    if champion_model is not None:
        champ_logloss, champ_ic, _ = _oos_metrics(
            champion_model,
            dataset,
            oos_start,
            oos_end,
            horizon_bars=horizon_bars,
            bar_ms=bar_ms,
        )
        fallback = ""
    else:
        champ_logloss = champion_card.val_logloss
        champ_ic = champion_card.val_rank_ic
        fallback = " (champion metrics from card; champion_model not supplied)"

    logloss_ok = new_logloss <= champ_logloss + logloss_tol
    ic_floor = ic_keep_frac * champ_ic if champ_ic > 0 else 0.0
    ic_ok = new_ic >= ic_floor
    promote = bool(logloss_ok and ic_ok)
    reason = (
        f"promoted: logloss {new_logloss:.4f}<= {champ_logloss + logloss_tol:.4f} and "
        f"rank_ic {new_ic:.4f}>= {ic_floor:.4f}{fallback}"
        if promote
        else (
            f"kept-champion: logloss_ok={logloss_ok} (new {new_logloss:.4f} vs "
            f"{champ_logloss + logloss_tol:.4f}), ic_ok={ic_ok} (new {new_ic:.4f} vs "
            f"{ic_floor:.4f}){fallback}"
        )
    )
    return PromotionVerdict(
        promote=promote,
        oos_start=oos_start,
        oos_end=oos_end,
        n_oos=n_oos,
        challenger_logloss=new_logloss,
        champion_logloss=champ_logloss,
        challenger_rank_ic=new_ic,
        champion_rank_ic=champ_ic,
        reason=reason,
    )


def _build_card(
    challenger: HistGBMMetaModel,
    *,
    trained_at: Ms,
    n_samples: int,
    val_logloss: float,
    val_rank_ic: float,
    code_git_sha: str,
    data_sha256: str,
    label_is_net: bool,
    model_id: str,
) -> ModelCard:
    """Assemble the challenger's :class:`ModelCard` (status ``candidate``)."""
    from alphaforge.ml.registry import ModelCard

    return ModelCard(
        model_id=model_id,
        trained_at=trained_at,
        train_start=challenger.windows.train_start,
        fit_end=challenger.windows.fit_end,
        n_samples=n_samples,
        feature_names=challenger.feature_names,
        params_json=json.dumps(
            {k: str(v) for k, v in sorted(challenger._params.items())}, sort_keys=True
        ),
        val_logloss=val_logloss,
        val_rank_ic=val_rank_ic,
        code_git_sha=code_git_sha,
        data_sha256=data_sha256,
        label_is_net=label_is_net,
        status="candidate",
    )


def _val_block_logloss(
    challenger: HistGBMMetaModel, X: pd.DataFrame, y: pd.Series, w: pd.Series
) -> float:
    """Weighted log-loss on the 20d isotonic block (a DIAGNOSTIC on the card)."""
    from sklearn.metrics import log_loss

    windows = challenger.windows
    ts = X.index.get_level_values(0).to_numpy(dtype=np.int64)
    iso_mask = (ts >= windows.iso_start) & (ts <= windows.fit_end)
    X_iso = X.loc[iso_mask]
    if len(X_iso.index) == 0:
        return float("nan")
    proba = challenger.predict_proba(X_iso)
    y_arr = y.reindex(X_iso.index).to_numpy(dtype=np.float64)
    w_arr = w.reindex(X_iso.index).to_numpy(dtype=np.float64)
    return float(log_loss(y_arr, proba, sample_weight=w_arr, labels=[0.0, 1.0]))


def weekly_retrain(
    asof: Ms,
    *,
    registry: ModelRegistry,
    dataset: MLDataset,
    settings: Settings,
    code_git_sha: str,
    model_id: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
    experiment_log: ExperimentLog | None = None,
    bar_ms: int = Timeframe.H1.ms,
) -> tuple[ModelCard, PromotionVerdict]:
    """The weekly challenger fit + promotion decision (09_ml.md §1.4, Sundays 00:30 UTC).

    Steps (pure of clock — ``asof`` passed in):

    1. ``windows = build_fit_windows(asof, horizon_bars=settings.signals.horizon_bars)``.
    2. Fit a challenger :class:`HistGBMMetaModel` on the ``window_days`` window
       (purged ES, disjoint isotonic) over ``dataset.matrices(train_start, fit_end)``.
    3. ``champion = registry.champion()`` (``None`` on cold start -> auto-promote).
    4. ``verdict = judge_promotion(challenger, champion, dataset, settings, asof)``.
    5. ``registry.register(card, challenger, importance=None)``; if
       ``verdict.promote`` then ``registry.promote(card.model_id)``.
    6. Append the trial config to the :class:`ExperimentLog` (findings 2/10): the
       hash carries the hyperparameters + feature-set hash + gate constants + window
       bounds, so a retuned knob is a DISTINCT trial and ``N`` is honest.

    Returns ``(challenger card, verdict)``. ``model_id`` is supplied by the caller
    (e.g. ``'histgbm_meta_2026-06-14_a1b2c3'``) so the function stays clock-free.
    """
    horizon_bars = settings.signals.horizon_bars
    windows = build_fit_windows(
        asof, horizon_bars=horizon_bars, window_days=window_days, bar_ms=bar_ms
    )

    X, y, w, t1, _side = dataset.matrices(windows.train_start, windows.fit_end)
    challenger = HistGBMMetaModel(model_id=model_id).fit(
        X, y, w, t1, windows, label_is_net=dataset.label_is_net
    )
    data_sha = dataset_content_sha(X, y, w, t1, windows)

    champion_card = registry.champion()
    champion_model = registry.load_champion() if champion_card is not None else None
    if champion_model is not None and not isinstance(champion_model, HistGBMMetaModel):
        champion_model = None  # IdentityMeta cannot be scored on the OOS logloss gate

    verdict = judge_promotion(
        challenger,
        champion_card,
        dataset,
        settings,
        asof,
        embargo_bars=embargo_bars,
        champion_model=champion_model,
        bar_ms=bar_ms,
    )

    card = _build_card(
        challenger,
        trained_at=asof,
        n_samples=challenger.n_train,
        val_logloss=_val_block_logloss(challenger, X, y, w),
        val_rank_ic=verdict.challenger_rank_ic,
        code_git_sha=code_git_sha,
        data_sha256=data_sha,
        label_is_net=dataset.label_is_net,
        model_id=model_id,
    )
    registry.register(card, challenger, importance=None)
    if verdict.promote:
        registry.promote(card.model_id)

    log = experiment_log if experiment_log is not None else ExperimentLog()
    log.record(
        _trial_config(
            challenger,
            window_days=window_days,
            embargo_bars=embargo_bars,
            logloss_tol=DEFAULT_LOGLOSS_TOL,
            ic_keep_frac=DEFAULT_IC_KEEP_FRAC,
            horizon_bars=horizon_bars,
            data_sha256=data_sha,
        ),
        sharpe_ann=float("nan"),
        sharpe_per_period=float("nan"),
        n_obs=verdict.n_oos,
        skew=float("nan"),
        kurtosis=float("nan"),
        now_ms=asof,
    )
    return card, verdict
