"""An import into the canonical union must carry the evidence, leave the bulk, refuse to
overwrite, and prove its own arithmetic against the union count."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from alphaforge.validation.experiments import ExperimentLog

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "import_external_experiment_ledgers.py"
_SPEC = importlib.util.spec_from_file_location("import_external_experiment_ledgers", SCRIPT)
assert _SPEC and _SPEC.loader
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

NOW = dt.datetime(2026, 9, 14, 10, 0, tzinfo=dt.UTC)


def _cfg(n: int) -> dict:
    return {"family": "f", "param": n, "start": "2020-01-01", "end": "2025-01-01"}


def _ledger(path: Path, configs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log = ExperimentLog(path)
    for i, config in enumerate(configs):
        log.record(
            config,
            sharpe_ann=0.1,
            sharpe_per_period=0.01,
            n_obs=500,
            skew=0.0,
            kurtosis=3.0,
            now_ms=1_700_000_000_000 + i,
        )


def _engine(path: Path, active: list[dict]) -> Path:
    (path / "configs").mkdir(parents=True, exist_ok=True)
    (path / "configs" / "base.yaml").write_text("profile: test\n")
    _ledger(path / "var" / "experiments.jsonl", active)
    return path


@pytest.fixture
def trees(tmp_path: Path) -> tuple[Path, Path]:
    canonical = _engine(tmp_path / "alphaforge", [_cfg(1), _cfg(2)])
    source = _engine(tmp_path / "clone", [_cfg(1), _cfg(2)])
    study = source / "artifacts" / "analysis" / "study_20260913"
    _ledger(study / "candidate" / "experiments.jsonl", [_cfg(10)])
    _ledger(study / "candidate_stress" / "experiments.jsonl", [_cfg(11)])
    (study / "candidate" / "reservation.json").write_text('{"reservation_ordinal": 230}')
    (study / "REPORT.md").write_text("# report\n")
    (study / "workspace" / ".venv" / "bin").mkdir(parents=True)
    (study / "workspace" / ".venv" / "bin" / "ruff").write_bytes(b"\0" * 4096)
    (study / "data.parquet").write_bytes(b"\0" * 2048)
    big = study / "huge.json"
    big.write_bytes(b"{" + b" " * (MOD.MAX_EVIDENCE_BYTES + 1) + b"}")
    # A second study without any ledger is not evidence of a trial and must be ignored.
    (source / "artifacts" / "analysis" / "notes_only").mkdir(parents=True)
    (source / "artifacts" / "analysis" / "notes_only" / "REPORT.md").write_text("x")
    return canonical, source


def test_dry_run_copies_nothing_and_reports_the_plan(trees) -> None:
    canonical, source = trees
    receipt = MOD.run(source, canonical, dry_run=True, now=NOW)
    assert receipt["dry_run"] is True
    assert not (canonical / "artifacts" / "analysis" / "study_20260913").exists()
    (directory,) = receipt["directories_imported"]
    copied = {f["path"] for f in directory["copied_files"]}
    assert copied == {
        "REPORT.md",
        "candidate/experiments.jsonl",
        "candidate/reservation.json",
        "candidate_stress/experiments.jsonl",
    }
    assert directory["skipped"]["workspace"]["files"] == 1
    assert directory["skipped"]["."]["files"] == 2  # data.parquet and the oversized json
    assert receipt["union_identities_before"] == 2
    assert receipt["union_identities_after"] == 2


def test_import_copies_evidence_and_the_union_grows_by_exactly_the_new_identities(trees) -> None:
    canonical, source = trees
    receipt = MOD.run(source, canonical, dry_run=False, now=NOW)
    target = canonical / "artifacts" / "analysis" / "study_20260913"
    assert (target / "candidate" / "experiments.jsonl").is_file()
    assert (target / "candidate" / "reservation.json").is_file()
    assert not (target / "workspace").exists()
    assert not (target / "data.parquet").exists()
    assert receipt["union_identities_before"] == 2
    assert receipt["union_identities_after"] == 4
    assert receipt["union_identities_added"] == 2
    for row in receipt["directories_imported"][0]["copied_files"]:
        assert row["sha256"] == MOD._sha256(target / row["path"])
    content_hash = receipt.pop("content_hash")
    canonical_json = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    assert content_hash == "sha256:" + MOD.hashlib.sha256(canonical_json).hexdigest()


def test_an_existing_target_directory_is_refused_not_merged(trees) -> None:
    canonical, source = trees
    existing = canonical / "artifacts" / "analysis" / "study_20260913"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("canonical evidence")
    receipt = MOD.run(source, canonical, dry_run=False, now=NOW)
    assert receipt["directories_imported"] == []
    assert receipt["directories_refused_already_present"] == [
        str(source / "artifacts" / "analysis" / "study_20260913")
    ]
    assert (existing / "keep.txt").read_text() == "canonical evidence"
    assert not (existing / "candidate").exists()


def test_a_diverging_active_ledger_stops_the_import(trees) -> None:
    canonical, source = trees
    _ledger(source / "var" / "experiments.jsonl", [_cfg(99)])
    with pytest.raises(SystemExit, match="diverging active ledgers"):
        MOD.run(source, canonical, dry_run=False, now=NOW)
    assert not (canonical / "artifacts" / "analysis" / "study_20260913").exists()


def test_the_source_must_be_an_engine_checkout_and_not_the_canonical_tree(trees) -> None:
    canonical, _ = trees
    with pytest.raises(SystemExit, match="same directory"):
        MOD.run(canonical, canonical, dry_run=True, now=NOW)
    with pytest.raises(SystemExit, match="not an engine checkout"):
        MOD.run(canonical.parent / "nowhere", canonical, dry_run=True, now=NOW)


def test_the_source_is_never_modified(trees) -> None:
    canonical, source = trees
    before = sorted(str(p.relative_to(source)) for p in source.rglob("*") if p.is_file())
    MOD.run(source, canonical, dry_run=False, now=NOW)
    after = sorted(str(p.relative_to(source)) for p in source.rglob("*") if p.is_file())
    assert before == after
