from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts" / "replay_fundamental_single_identity.py"
    spec = importlib.util.spec_from_file_location("replay_fundamental_single_identity_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_replay_candidate_passes_fail_closed_preflight() -> None:
    module = _module()
    assert len(module.CANDIDATES) == 5
    for run_name, identity in module.CANDIDATES.items():
        audit = module.preflight(run_name)
        assert audit["hypothesis_key"] == identity
        assert audit["preregistered_at"] < audit["measured_at"]
        assert audit["artifact"]["validation"]["n_obs"] == 5_384
        assert len(audit["artifact"]["config"]["instrument_ids"]) == 6_820


def test_replay_environment_commits_dirty_local_source_tree() -> None:
    environment = _module()._source_environment()
    assert environment["schema"] == "canli.alphac-replay-source-environment.v1"
    assert environment["source_files"] > 100
    paths = {item["path"] for item in environment["leaves"]}
    assert "src/alphaforge/analytics/walkforward.py" in paths
    assert "scripts/replay_fundamental_single_identity.py" in paths
    assert environment["content_hash"].startswith("sha256:")


def test_only_the_authorized_versioned_correction_can_replace_the_base_lake(
    tmp_path: Path,
) -> None:
    module = _module()
    manifest = __import__("json").loads(module.CORRECTED_LAKE_MANIFEST.read_text())
    corrected = REPO / manifest["corrected_lake"]
    audit = module.preflight("single_operating_margin", lake_dir=corrected)
    data = audit["data_environment"]
    assert data["kind"] == "VERSIONED_SHARADAR_HDB_ZERO_MARKER_QUARANTINE"
    assert data["rows_quarantined"] == 1
    assert data["cash_amount_imputed"] is False
    assert data["versioned_correction_content_hash"] == manifest["content_hash"]

    unauthorized = tmp_path / "data" / "lake_sharadar"
    unauthorized.mkdir(parents=True)
    import pytest

    with pytest.raises(ValueError, match="not an authorized versioned correction"):
        module.preflight("single_operating_margin", lake_dir=unauthorized)


def test_operating_margin_corporate_action_replay_is_trial_specific() -> None:
    module = _module()
    manifest = __import__("json").loads(module.CORPORATE_ACTION_LAKE_MANIFEST.read_text())
    corrected = REPO / manifest["corrected_lake"]
    import pytest

    with pytest.raises(ValueError, match="authorized execution code changed"):
        module.preflight("single_operating_margin", lake_dir=corrected)
    with pytest.raises(ValueError, match="not an authorized versioned correction"):
        module.preflight("single_book_to_price", lake_dir=corrected)
