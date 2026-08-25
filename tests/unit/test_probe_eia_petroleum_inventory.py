from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import probe_eia_petroleum_inventory as module
from probe_eia_petroleum_inventory import build_scores, next_session


def _weekly_events(years: int = 8) -> pd.DataFrame:
    dates = pd.date_range("2011-01-07", periods=52 * years, freq="7D")
    rows: list[dict[str, object]] = []
    for proxy, offset in (("USO", 0.0), ("UGA", 0.5)):
        for number, period_end in enumerate(dates):
            rows.append(
                {
                    "release_date": period_end + pd.Timedelta(days=5),
                    "period_end": period_end,
                    "proxy": proxy,
                    "change_million_barrels": float(np.sin(number / 8.0) + offset),
                }
            )
    return pd.DataFrame(rows)


def test_scores_require_only_prior_seasonal_and_scale_history() -> None:
    events = _weekly_events()
    baseline = build_scores(events)
    altered = events.copy()
    altered.loc[
        altered["release_date"] == altered["release_date"].max(),
        "change_million_barrels",
    ] = 999
    rerun = build_scores(altered)
    before_last = baseline["release_date"] < baseline["release_date"].max()
    pd.testing.assert_series_equal(
        baseline.loc[before_last, "score"].reset_index(drop=True),
        rerun.loc[before_last, "score"].reset_index(drop=True),
    )
    assert baseline["score"].notna().any()


def test_next_session_is_strictly_after_release_date() -> None:
    calendar = pd.date_range("2026-01-05", periods=5, freq="B")
    assert next_session(calendar, pd.Timestamp("2026-01-05")) == 1
    assert next_session(calendar, pd.Timestamp("2026-01-08")) == 4
    assert next_session(calendar, pd.Timestamp("2026-01-10")) is None


def test_archive_manifest_rejects_changed_first_release(tmp_path: Path) -> None:
    source = tmp_path / "table4.csv"
    source.write_text("original")
    manifest = {
        "schema": "canli.eia-wpsr-vintage-manifest.v1",
        "discovered_releases": 1,
        "files": [
            {
                "path": str(source),
                "sha256": module.file_sha256(source),
            }
        ],
    }
    module.validate_archive_manifest(manifest)
    source.write_text("changed")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        module.validate_archive_manifest(manifest)


def test_reproduction_environment_binds_runner_and_lockfiles() -> None:
    evidence = module.reproduction_environment()
    assert evidence["command"] == "uv run python scripts/probe_eia_petroleum_inventory.py"
    assert evidence["runner_sha256"] == module.file_sha256(module.RUNNER)
    assert evidence["pyproject_sha256"] == module.file_sha256(module.PYPROJECT)
    assert evidence["uv_lock_sha256"] == module.file_sha256(module.UV_LOCK)


def test_admission_review_is_fail_closed_against_v6(tmp_path: Path, monkeypatch) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema": "canli.alphac-sleeve-admission-contract.v6",
                "evidence_checks_per_candidate": 85,
            }
        )
    )
    monkeypatch.setattr(module, "ADMISSION_CONTRACT", contract)
    review = module.admission_review({"one": True, "two": False})
    assert review["status"] == "RESEARCH_SUBSET_FAILED"
    assert review["technically_eligible"] is False
    assert review["preregistered_research_checks_passed"] == 1
