"""Selection-union invariants for honest cross-profile DSR accounting."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from alphaforge.analytics.walkforward import compute_validation
from alphaforge.validation.dsr import DSRReport
from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

if TYPE_CHECKING:
    from pathlib import Path


def _record(
    ledger: ExperimentLog | ExperimentUnion,
    config: dict[str, object],
    sharpe: float,
    now_ms: int,
) -> None:
    ledger.record(
        config,
        sharpe_ann=sharpe * math.sqrt(365.0),
        sharpe_per_period=sharpe,
        n_obs=200,
        skew=0.0,
        kurtosis=3.0,
        now_ms=now_ms,
    )


def _root(tmp_path: Path) -> Path:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "base.yaml").write_text("{}\n", encoding="utf-8")
    return tmp_path


def test_union_appends_only_to_active_and_is_idempotent_across_profiles(tmp_path: Path) -> None:
    root = _root(tmp_path)
    active_path = root / "var" / "experiments.jsonl"
    other_path = root / "var_equity" / "experiments.jsonl"
    other = ExperimentLog(other_path)
    _record(other, {"idea": "existing"}, 0.1, 1)
    before = other_path.read_bytes()

    union = ExperimentUnion.discover(active_path, root)
    _record(union, {"idea": "existing"}, 9.9, 2)
    assert not active_path.exists()
    assert other_path.read_bytes() == before

    _record(union, {"idea": "new"}, 0.3, 3)
    assert ExperimentLog(active_path).n_trials() == 1
    assert other_path.read_bytes() == before
    assert union.n_trials() == 2
    assert union.n_hypotheses() == 2


def test_window_remeasurement_cannot_change_selection_n_or_variance(tmp_path: Path) -> None:
    root = _root(tmp_path)
    active = root / "var" / "experiments.jsonl"
    union = ExperimentUnion.discover(active, root)
    _record(union, {"idea": "a", "start": 1, "end": 2}, 0.1, 1)
    _record(union, {"idea": "b", "start": 1, "end": 2}, 0.3, 2)
    before = union.hypothesis_sharpe_variance()

    _record(union, {"idea": "a", "start": 2, "end": 3}, 5.0, 3)
    assert union.n_trials() == 3
    assert union.n_hypotheses() == 2
    assert union.window_only_reevaluations() == 1
    assert union.hypothesis_sharpe_variance() == pytest.approx(before)
    assert union.trial_sharpe_variance() != pytest.approx(before)

    _record(union, {"idea": "a", "parameter": 2, "start": 2, "end": 3}, 0.5, 4)
    assert union.n_hypotheses() == 3
    assert union.hypothesis_sharpe_variance() != pytest.approx(before)


def test_discovery_excludes_archives_and_requires_verified_root(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _record(ExperimentLog(root / "var" / "experiments.jsonl"), {"idea": "live"}, 0.1, 1)
    _record(
        ExperimentLog(root / "artifacts" / "campaign" / "experiments.jsonl"),
        {"idea": "durable-artifact"},
        0.15,
        2,
    )
    _record(
        ExperimentLog(root / "var_archive" / "experiments.jsonl"),
        {"idea": "archived"},
        0.2,
        3,
    )
    _record(
        ExperimentLog(root / "artifacts" / "archive_broken_prices" / "experiments.jsonl"),
        {"idea": "archived-artifact"},
        0.25,
        4,
    )
    union = ExperimentUnion.discover(root / "var" / "experiments.jsonl", root)
    assert union.n_hypotheses() == 2
    relative_paths = {path.relative_to(root) for path in union.paths}
    assert "artifacts/campaign/experiments.jsonl" in {str(path) for path in relative_paths}
    assert all(
        not any("archive" in part.casefold() for part in path.parts) for path in relative_paths
    )

    with pytest.raises(ValueError, match=r"configs/base\.yaml"):
        ExperimentUnion.discover(tmp_path / "bad" / "var" / "experiments.jsonl", tmp_path / "bad")


def test_compute_validation_uses_union_hypothesis_context(tmp_path: Path) -> None:
    root = _root(tmp_path)
    active = root / "var" / "experiments.jsonl"
    other = ExperimentLog(root / "var_macro" / "experiments.jsonl")
    _record(other, {"idea": "macro"}, 0.2, 1)
    union = ExperimentUnion.discover(active, root)
    seen: list[tuple[int, float]] = []

    def capture(
        returns: pd.Series,
        n_trials: int,
        variance: float,
        periods_per_year: float,
    ) -> DSRReport:
        del periods_per_year
        seen.append((n_trials, variance))
        return DSRReport(
            psr=0.8,
            dsr=0.7,
            sr_ann=1.0,
            sr_per_period=0.1,
            skew=0.0,
            kurtosis=3.0,
            n_obs=len(returns),
            expected_max_sr=0.2,
        )

    index = pd.Index(range(0, 6 * 86_400_000, 86_400_000), name="ts")
    equity = pd.Series([100.0, 101.0, 100.5, 102.0, 101.5, 103.0], index=index)
    report = compute_validation(
        equity,
        {"idea": "active"},
        union,
        now_ms=2,
        dsr_fn=capture,
        with_provenance=True,
    )

    assert report is not None
    assert report.n_trials == union.n_hypotheses() == 2
    assert seen == [(2, union.hypothesis_sharpe_variance())]
    provenance = report.to_json_obj()["_provenance"]
    assert isinstance(provenance, dict)
    assert provenance["selection_unit"] == "first_immutable_record_per_hypothesis"
    assert provenance["selection_ledger_paths"] == [str(path) for path in union.paths]


def test_paused_policy_blocks_new_identity_but_allows_operational_remeasurement(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    active = root / "var" / "experiments.jsonl"
    log = ExperimentLog(active)
    _record(log, {"idea": "live", "start": 1, "end": 2}, 0.1, 1)
    (root / "config").mkdir()
    (root / "config" / "trial_accounting.json").write_text(
        '{"research_status":"PAUSED_TRIAL_DEBT_RECONCILIATION"}\n',
        encoding="utf-8",
    )
    union = ExperimentUnion.discover(active, root)

    union.preflight_hypotheses([{"idea": "live", "start": 8, "end": 9}])
    with pytest.raises(RuntimeError, match="before computation"):
        union.preflight_hypotheses([{"idea": "live"}, {"idea": "new"}])

    _record(union, {"idea": "live", "start": 2, "end": 3}, 0.2, 2)
    assert union.n_trials() == 2
    assert union.n_hypotheses() == 1
    with pytest.raises(RuntimeError, match="registration blocked"):
        _record(union, {"idea": "new"}, 0.3, 3)


def test_active_policy_preflight_allows_new_hypotheses(tmp_path: Path) -> None:
    root = _root(tmp_path)
    union = ExperimentUnion.discover(root / "var" / "experiments.jsonl", root)

    union.preflight_hypotheses([{"idea": "new"}])
