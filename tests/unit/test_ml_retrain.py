"""Unit tests for alphaforge.ml.retrain — purged retrain + champion/challenger promotion.

These pin the load-bearing leakage controls (09_ml.md §1.4, §2; CRITIQUE_leakage
findings 9/10/18; CRITIQUE_overfit findings 2/5):

* The promotion window opens strictly after BOTH models' fit+calibration windows
  plus the embargo — never on a tail either model fit/calibrated on (finding 9, the
  load-bearing test).
* Cold start auto-promotes the first candidate.
* Promote iff BOTH the log-loss tolerance AND the direction-consistent rank-IC
  floor pass (finding 10: IC on signed bet-size vs side-signed net return).
* A short OOS window keeps the champion (``insufficient-oos``), never borrowing a
  contaminated tail.
* ``build_fit_windows`` admits only fully-realized labels (``fit_end + h·Δ <= asof``).
* Each ``weekly_retrain`` appends exactly one (idempotent) trial to the ExperimentLog,
  whose hash carries the hyperparameters + feature-set + gate constants (findings 2/5).
* ``data_sha256`` is a content hash of the materialized matrices (finding 18),
  identical regardless of row order.

Offline, pure pandas/numpy/sklearn; a tmp_path SQLite registry; all fixtures
synthetic and seeded. No lake, no clock, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import numpy as np
import pandas as pd
import pytest

from alphaforge.config.settings import Settings
from alphaforge.ml.model import EARLY_STOP_DAYS, ISOTONIC_DAYS, HistGBMMetaModel
from alphaforge.ml.registry import ModelCard, ModelRegistry
from alphaforge.ml.retrain import (
    DEFAULT_EMBARGO_BARS,
    PromotionVerdict,
    build_fit_windows,
    dataset_content_sha,
    judge_promotion,
    weekly_retrain,
)

HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_672_531_200_000  # 2023-01-01 00:00 UTC
HORIZON = 72  # Settings() default signals.horizon_bars

_FrameT = TypeVar("_FrameT", pd.Series, pd.DataFrame)


class _SyntheticDataset:
    """An in-memory MLDataset with a constructed edge in feature ``f0``.

    One decision bar per day per instrument. ``meta_label`` rises with ``f0`` so a
    fitted model's signed bet-size correlates positively with the side-signed net
    return — giving the direction-consistent promotion IC genuine signal.
    """

    def __init__(self, *, n_days: int = 500, n_iids: int = 8, seed: int = 0) -> None:
        rng = np.random.RandomState(seed)
        days = [T0 + d * DAY for d in range(n_days)]
        iids = [f"I{k}" for k in range(n_iids)]
        index = pd.MultiIndex.from_product(
            [days, iids], names=("ts_open", "instrument_id")
        )
        n = len(index)
        feats = {f"f{j}": rng.randn(n) for j in range(4)}
        self._X = pd.DataFrame(feats, index=index)
        logit = 1.6 * self._X["f0"].to_numpy() + 0.3 * rng.randn(n)
        p_true = 1.0 / (1.0 + np.exp(-logit))
        win = (rng.rand(n) < p_true).astype(float)
        self._y = pd.Series(win, index=index, name="meta_label")
        self._w = pd.Series(np.ones(n), index=index, name="w")
        ts = index.get_level_values(0).to_numpy(dtype=np.int64)
        self._t1 = pd.Series(ts + HORIZON * HOUR, index=index, name="t1")
        # side = +1 here; signed net return is positive on a win, negative on a loss.
        self._side = pd.Series(np.ones(n), index=index, name="side")
        ret = np.where(win > 0, 1.0, -1.0) * (0.5 + 0.5 * np.abs(self._X["f0"].to_numpy()))
        self._ret_signed = pd.Series(ret, index=index, name="ret")

    def _slice(self, s: _FrameT, start: int, end: int) -> _FrameT:
        ts = s.index.get_level_values(0).to_numpy(dtype=np.int64)
        return s.loc[(ts >= start) & (ts <= end)]

    def matrices(
        self, start: int, end: int
    ) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
        return (
            self._slice(self._X, start, end),
            self._slice(self._y, start, end),
            self._slice(self._w, start, end),
            self._slice(self._t1, start, end),
            self._slice(self._side, start, end),
        )

    def ret_signed(self, start: int, end: int) -> pd.Series:
        return self._slice(self._ret_signed, start, end)

    @property
    def label_is_net(self) -> bool:
        return True


def _registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(tmp_path / "registry.db", tmp_path / "artifacts")


def _fit_challenger(dataset: _SyntheticDataset, asof: int) -> HistGBMMetaModel:
    windows = build_fit_windows(asof, horizon_bars=HORIZON)
    X, y, w, t1, _ = dataset.matrices(windows.train_start, windows.fit_end)
    return HistGBMMetaModel(model_id="chal").fit(X, y, w, t1, windows)


# A challenger trained as-of an EARLIER time leaves a genuine OOS window before the
# (later) judging `asof` — the honest weekly-cadence flow (09_ml.md §2): the model
# trained last week is judged this week on the realized week in between.
ASOF_TRAIN = T0 + 420 * DAY
ASOF_NOW = T0 + 499 * DAY


class TestBuildFitWindows:
    def test_build_fit_windows_realized_only(self) -> None:
        """fit_end + horizon_bars·Δ <= asof (no unrealized label in the fit)."""
        asof = T0 + 400 * DAY
        windows = build_fit_windows(asof, horizon_bars=HORIZON)
        assert windows.fit_end + HORIZON * HOUR <= asof
        assert windows.fit_end == asof - HORIZON * HOUR
        # Strictly increasing train / ES / iso / fit_end.
        assert windows.train_start < windows.es_start < windows.iso_start <= windows.fit_end
        # ES is EARLY_STOP_DAYS wide, iso is ISOTONIC_DAYS wide.
        assert (windows.iso_start - windows.es_start) == EARLY_STOP_DAYS * DAY
        assert (windows.fit_end - windows.iso_start) == (ISOTONIC_DAYS - 1) * DAY

    def test_window_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="too short to carve"):
            build_fit_windows(T0 + 100 * DAY, horizon_bars=HORIZON, window_days=10)


class TestDatasetContentSha:
    def test_sha_is_row_order_invariant(self) -> None:
        ds = _SyntheticDataset(n_days=120)
        windows = build_fit_windows(T0 + 100 * DAY, horizon_bars=HORIZON, window_days=90)
        X, y, w, t1, _ = ds.matrices(windows.train_start, windows.fit_end)
        a = dataset_content_sha(X, y, w, t1, windows)
        shuffled = X.sample(frac=1.0, random_state=3)
        b = dataset_content_sha(
            shuffled, y.reindex(shuffled.index), w.reindex(shuffled.index),
            t1.reindex(shuffled.index), windows,
        )
        assert a == b

    def test_sha_changes_with_window_bounds(self) -> None:
        ds = _SyntheticDataset(n_days=200)
        w1 = build_fit_windows(T0 + 160 * DAY, horizon_bars=HORIZON, window_days=140)
        w2 = build_fit_windows(T0 + 170 * DAY, horizon_bars=HORIZON, window_days=140)
        X, y, w, t1, _ = ds.matrices(w1.train_start, w1.fit_end)
        assert dataset_content_sha(X, y, w, t1, w1) != dataset_content_sha(X, y, w, t1, w2)


class TestJudgePromotion:
    def test_cold_start_auto_promotes(self) -> None:
        """No champion -> promote=True, reason='cold-start'."""
        ds = _SyntheticDataset()
        asof = T0 + 460 * DAY
        chal = _fit_challenger(ds, asof)
        verdict = judge_promotion(chal, None, ds, Settings(), asof)
        assert verdict.promote is True
        assert verdict.reason == "cold-start"
        assert verdict.champion_logloss is None
        assert verdict.label_space_only is True

    def _champ_card(
        self, chal: HistGBMMetaModel, *, fit_end: int, val_logloss: float, val_rank_ic: float
    ) -> ModelCard:
        return ModelCard(
            model_id="champ",
            trained_at=fit_end,
            train_start=fit_end - 365 * DAY,
            fit_end=fit_end,
            n_samples=1000,
            feature_names=chal.feature_names,
            params_json="{}",
            val_logloss=val_logloss,
            val_rank_ic=val_rank_ic,
            code_git_sha="deadbeef",
            data_sha256="x",
            label_is_net=True,
            status="champion",
        )

    def test_promotion_window_after_both_fit_ends(self) -> None:
        """finding 9 (load-bearing): oos_start == max(champ.fit_end, chall.fit_end)
        + embargo, the judged rows lie strictly after BOTH fit spans, and a window
        with realized data is genuinely OOS for both models."""
        ds = _SyntheticDataset()
        chal = _fit_challenger(ds, ASOF_TRAIN)  # challenger fit_end ~ ASOF_TRAIN - h
        t1_chall = chal.windows.fit_end  # the LATER of the two fit ends
        t0_champ = chal.windows.fit_end - 30 * DAY  # an EARLIER champion fit_end
        champ_card = self._champ_card(chal, fit_end=t0_champ, val_logloss=5.0, val_rank_ic=0.0)
        verdict = judge_promotion(
            chal, champ_card, ds, Settings(), ASOF_NOW, embargo_bars=DEFAULT_EMBARGO_BARS
        )
        expected_oos_start = max(t0_champ, t1_chall) + DEFAULT_EMBARGO_BARS * HOUR
        assert verdict.oos_start == expected_oos_start
        # The judged window opens strictly after BOTH fit ends + embargo ...
        assert verdict.oos_start > t1_chall
        assert verdict.oos_start > t0_champ
        # ... and never enters either model's train/ES/isotonic span.
        assert verdict.oos_start > chal.windows.fit_end
        # The judged window is non-empty (genuinely-OOS realized data exists).
        assert verdict.n_oos > 0
        # Every judged row's ts is >= oos_start (asserted via the dataset slice).
        X_oos, *_ = ds.matrices(verdict.oos_start, verdict.oos_end)
        judged_ts = X_oos.index.get_level_values(0).to_numpy()
        assert judged_ts.min() >= verdict.oos_start
        assert int((judged_ts < chal.windows.fit_end).sum()) == 0  # no fit-span row leaks in

    def test_insufficient_oos_keeps_champion(self) -> None:
        """A short OOS window -> reason='insufficient-oos', no fallback to a fit block.

        Judging at the SAME asof the challenger trained leaves the embargoed OOS
        window past asof — the honest 'no realized data yet' state — so the champion
        stays and the verdict NEVER borrows a contaminated tail."""
        ds = _SyntheticDataset()
        chal = _fit_challenger(ds, ASOF_NOW)  # fit_end ~ ASOF_NOW - h, no room after
        champ_card = self._champ_card(
            chal, fit_end=chal.windows.fit_end, val_logloss=0.69, val_rank_ic=0.02
        )
        verdict = judge_promotion(
            chal, champ_card, ds, Settings(), ASOF_NOW,
            embargo_bars=DEFAULT_EMBARGO_BARS, min_oos=200,
        )
        assert verdict.promote is False
        assert verdict.reason == "insufficient-oos"
        assert verdict.oos_start > chal.windows.fit_end  # opens after the fit span
        assert verdict.n_oos < 200

    def test_promote_only_if_both_metrics_pass(self) -> None:
        """Better log-loss but rank_ic < ic_keep_frac·champ -> keep; both pass -> promote."""
        ds = _SyntheticDataset()
        chal = _fit_challenger(ds, ASOF_TRAIN)
        t0_champ = chal.windows.fit_end - 30 * DAY
        # Champion with an UNBEATABLE rank_ic floor (card-supplied; champion_model is
        # not provided so the card metrics are the fallback) -> IC gate blocks.
        hard_champ = self._champ_card(chal, fit_end=t0_champ, val_logloss=5.0, val_rank_ic=0.95)
        v_blocked = judge_promotion(chal, hard_champ, ds, Settings(), ASOF_NOW, min_oos=1)
        assert v_blocked.promote is False
        assert "ic_ok=False" in v_blocked.reason
        # Champion with a weak IC floor and weak logloss -> challenger clears both.
        easy_champ = self._champ_card(chal, fit_end=t0_champ, val_logloss=5.0, val_rank_ic=0.0)
        v_pass = judge_promotion(chal, easy_champ, ds, Settings(), ASOF_NOW, min_oos=1)
        assert v_pass.promote is True


class TestWeeklyRetrain:
    def test_cold_start_registers_and_promotes(self, tmp_path: Path) -> None:
        ds = _SyntheticDataset()
        asof = T0 + 460 * DAY
        with _registry(tmp_path) as reg:
            card, verdict = weekly_retrain(
                asof,
                registry=reg,
                dataset=ds,
                settings=Settings(),
                code_git_sha="abc123",
                model_id="histgbm_meta_2023_a1",
                experiment_log=__import__(
                    "alphaforge.validation.experiments", fromlist=["ExperimentLog"]
                ).ExperimentLog(tmp_path / "exp.jsonl"),
            )
            assert verdict.reason == "cold-start"
            assert verdict.promote is True
            champ = reg.champion()
            assert champ is not None
            assert champ.model_id == "histgbm_meta_2023_a1"
            assert champ.code_git_sha == "abc123"
            assert champ.label_is_net is True
            # The fit only used realized labels.
            assert card.fit_end + HORIZON * HOUR <= asof

    def test_retrain_logs_trial_to_experiment_log(self, tmp_path: Path) -> None:
        """Each weekly_retrain appends exactly one (idempotent) trial."""
        from alphaforge.validation.experiments import ExperimentLog

        ds = _SyntheticDataset()
        asof = T0 + 460 * DAY
        log = ExperimentLog(tmp_path / "exp.jsonl")
        with _registry(tmp_path) as reg:
            weekly_retrain(
                asof, registry=reg, dataset=ds, settings=Settings(),
                code_git_sha="abc", model_id="m1", experiment_log=log,
            )
            assert log.n_trials() == 1
            # Re-running the SAME retrain (same asof, same data -> same config hash)
            # is idempotent: N does not inflate.
            weekly_retrain(
                asof, registry=reg, dataset=ds, settings=Settings(),
                code_git_sha="abc", model_id="m1b", experiment_log=log,
            )
            assert log.n_trials() == 1

    def test_retuned_gate_constant_is_a_new_trial(self, tmp_path: Path) -> None:
        """findings 2/5: changing a gate constant creates a DISTINCT ledger trial."""
        from alphaforge.validation.experiments import ExperimentLog

        ds = _SyntheticDataset()
        asof = T0 + 460 * DAY
        log = ExperimentLog(tmp_path / "exp.jsonl")
        with _registry(tmp_path) as reg:
            weekly_retrain(
                asof, registry=reg, dataset=ds, settings=Settings(),
                code_git_sha="abc", model_id="m1", experiment_log=log,
            )
            weekly_retrain(
                asof, registry=reg, dataset=ds, settings=Settings(),
                code_git_sha="abc", model_id="m2", experiment_log=log,
                window_days=300,  # a different window_days -> a different trial config
            )
        assert log.n_trials() == 2

    def test_verdict_is_label_space_only(self, tmp_path: Path) -> None:
        """The verdict flags itself label-space-only (finding 5/12): the binding gate
        is the Phase-12 gated WF net-of-cost PnL, not these metrics."""
        ds = _SyntheticDataset()
        asof = T0 + 460 * DAY
        with _registry(tmp_path) as reg:
            _card, verdict = weekly_retrain(
                asof, registry=reg, dataset=ds, settings=Settings(),
                code_git_sha="abc", model_id="m1",
                experiment_log=__import__(
                    "alphaforge.validation.experiments", fromlist=["ExperimentLog"]
                ).ExperimentLog(tmp_path / "e.jsonl"),
            )
        assert isinstance(verdict, PromotionVerdict)
        assert verdict.label_space_only is True
