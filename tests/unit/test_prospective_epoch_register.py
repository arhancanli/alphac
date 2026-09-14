"""The prospective epoch is derived from the ledgers, never typed, and fails closed when the
arithmetic legacy + prospective = union does not hold."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from alphaforge.validation.experiments import ExperimentLog, hypothesis_hash

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_prospective_epoch_register.py"
_SPEC = importlib.util.spec_from_file_location("build_prospective_epoch_register", SCRIPT)
assert _SPEC and _SPEC.loader
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

NOW = dt.datetime(2026, 9, 14, 11, 0, tzinfo=dt.UTC)


def _cfg(n: int, **extra: object) -> dict:
    return {"family": "f", "param": n, "start": "2020-01-01", "end": "2025-01-01", **extra}


def _record(path: Path, config: dict, now_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ExperimentLog(path).record(
        config,
        sharpe_ann=0.4,
        sharpe_per_period=0.02,
        n_obs=800,
        skew=0.0,
        kurtosis=3.0,
        now_ms=now_ms,
    )


def _closure(repo: Path, keys: list[str]) -> None:
    body = {
        "schema": "test-closure",
        "status": "LEGACY_EPOCH_RETIRED_FAIL_CLOSED",
        "summary": {"retired_identities": len(keys)},
        "identities": [{"hypothesis_key": k} for k in keys],
    }
    body["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    path = repo / MOD.LEGACY_CLOSURE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def _reservation(directory: Path, key: str, ordinal: int, family: str, arm: str, at: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "reservation.json").write_text(
        json.dumps(
            {
                "schema": "canli.alphac-forward-trial-reservation.v1",
                "hypothesis_identity": key,
                "governance_epoch": {"reservation_ordinal": ordinal},
                "family_trial_account": family,
                "trial_config": {"arm": arm},
                "reserved_at": at,
                "return_identity_id": f"{family}_{arm}",
                "status": "RETURN_IDENTITY_RESERVED",
            }
        )
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "engine"
    (repo / "configs").mkdir(parents=True)
    (repo / "configs" / "base.yaml").write_text("profile: test\n")
    legacy = [_cfg(1), _cfg(2), _cfg(3)]
    for i, config in enumerate(legacy):
        _record(repo / "var" / "experiments.jsonl", config, 1_000 + i)
    _closure(repo, [hypothesis_hash(c) for c in legacy])
    # Two prospective identities in an imported study: candidate and its cost-stress arm.
    study = repo / "artifacts" / "analysis" / "study_20260913"
    _record(study / "candidate" / "experiments.jsonl", _cfg(10, arm="candidate"), 5_000)
    _record(study / "candidate_stress" / "experiments.jsonl", _cfg(11, arm="stress"), 5_001)
    _reservation(
        study / "candidate",
        hypothesis_hash(_cfg(10, arm="candidate")),
        5,
        "fam",
        "candidate",
        "2026-09-13T01:00:00+00:00",
    )
    _reservation(
        study / "candidate_stress",
        hypothesis_hash(_cfg(11, arm="stress")),
        6,
        "fam",
        "stress",
        "2026-09-13T02:00:00+00:00",
    )
    receipt = repo / "artifacts" / "audit" / "external_ledger_import_20260914T000000Z.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"dry_run": False, "directories_imported": [{"name": "study_20260913"}]})
    )
    # One canonical measurement with no reservation at all: a governance finding, not a crash.
    _record(repo / "artifacts" / "analysis" / "loose" / "experiments.jsonl", _cfg(20), 6_000)
    return repo


def test_register_derives_the_epoch_and_the_arithmetic_holds(repo: Path) -> None:
    register = MOD.build(repo, now=NOW)
    summary = register["summary"]
    assert summary["union_identities"] == 6
    assert summary["legacy_retired_identities"] == 3
    assert summary["observed_identities"] == 3
    assert summary["identity_arithmetic_holds"] is True
    assert summary["by_status"] == {
        MOD.STATUS_GOVERNED: 0,
        MOD.STATUS_IMPORTED: 2,
        MOD.STATUS_RESERVED: 0,
        MOD.STATUS_UNRESERVED: 1,
    }
    assert summary["first_reservation_ordinal"] == 5
    assert summary["latest_reservation_ordinal"] == 6
    assert summary["reservation_ordinals_contiguous"] is True
    rows = register["identities"]
    assert [r["reservation_ordinal"] for r in rows] == [5, 6, None]
    assert rows[0]["source"] == {
        "kind": "imported",
        "receipt": "artifacts/audit/external_ledger_import_20260914T000000Z.json",
    }
    assert rows[0]["arm"] == "candidate" and rows[1]["arm"] == "stress"
    assert rows[2]["status"] == MOD.STATUS_UNRESERVED and rows[2]["family_trial_account"] is None
    assert all(r["admitted"] is False and r["packet_complete"] is False for r in rows)
    assert rows[0]["first_measurement"]["n_obs"] == 800
    content_hash = register.pop("content_hash")
    assert content_hash == MOD._content_hash(register)


def test_an_ordinal_gap_is_reported_not_hidden(repo: Path) -> None:
    extra = repo / "artifacts" / "analysis" / "study_20260913" / "later"
    _record(extra / "experiments.jsonl", _cfg(12, arm="later"), 5_002)
    _reservation(
        extra,
        hypothesis_hash(_cfg(12, arm="later")),
        9,
        "fam",
        "later",
        "2026-09-13T03:00:00+00:00",
    )
    summary = MOD.build(repo, now=NOW)["summary"]
    assert summary["reservation_ordinals_contiguous"] is False
    assert summary["reservation_ordinal_gaps"] == [7, 8]


def test_two_identities_on_one_ordinal_fail_closed(repo: Path) -> None:
    clash = repo / "artifacts" / "analysis" / "study_20260913" / "clash"
    _record(clash / "experiments.jsonl", _cfg(13, arm="clash"), 5_003)
    _reservation(
        clash,
        hypothesis_hash(_cfg(13, arm="clash")),
        6,
        "fam",
        "clash",
        "2026-09-13T04:00:00+00:00",
    )
    with pytest.raises(ValueError, match="claimed by two identities"):
        MOD.build(repo, now=NOW)


def test_a_key_in_both_epochs_fails_closed(repo: Path) -> None:
    # Re-seal the closure with a key that is NOT in the union; legacy count no longer adds up.
    _closure(repo, [hypothesis_hash(_cfg(1)), hypothesis_hash(_cfg(2)), "deadbeefdeadbeef"])
    with pytest.raises(ValueError, match="!= union"):
        MOD.build(repo, now=NOW)


def test_duplicate_reservation_records_keep_the_earliest_and_are_listed(repo: Path) -> None:
    again = repo / "artifacts" / "analysis" / "study_20260913_attempt2" / "candidate"
    again.mkdir(parents=True)
    _reservation(
        again,
        hypothesis_hash(_cfg(10, arm="candidate")),
        5,
        "fam",
        "candidate",
        "2026-09-13T00:30:00+00:00",
    )
    register = MOD.build(repo, now=NOW)
    row = next(r for r in register["identities"] if r["reservation_ordinal"] == 5)
    assert row["reserved_at"] == "2026-09-13T00:30:00+00:00"
    assert len(register["summary"]["duplicate_reservation_records"]) == 1


@pytest.mark.workspace_evidence
def test_the_real_register_reconciles_with_the_public_ledger() -> None:
    path = ROOT / MOD.OUTPUT_RELATIVE
    if not path.exists():
        pytest.skip("register lives in the working tree")
    register = json.loads(path.read_text())
    summary = register["summary"]
    assert summary["identity_arithmetic_holds"] is True
    assert (
        summary["legacy_retired_identities"] + summary["observed_identities"]
        == summary["union_identities"]
    )
    assert summary["by_status"][MOD.STATUS_GOVERNED] >= 1
