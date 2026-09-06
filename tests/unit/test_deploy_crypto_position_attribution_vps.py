from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy_crypto_position_attribution_vps.py"
CONTRACT = ROOT / "artifacts" / "engineering" / "crypto_position_attribution_vps_preflight.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("crypto_attribution_deploy", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(
    module: ModuleType, contract: dict[str, object], *, before: bool
) -> dict[str, object]:
    hash_key = "remote_sha256" if before else "desired_sha256"
    files = contract["required_files"]
    assert isinstance(files, list)
    columns = ["cycle_ts", "instrument_id", "qty", "avg_entry_price", "opened_ts"]
    if not before:
        columns.extend(module.REQUIRED_COLUMNS)
    return {
        "database_exists": True,
        "database_sha256": "0" * 64,
        "files": {item["path"]: item[hash_key] for item in files},
        "position_snapshot_columns": columns,
        "latest_equity_cycle_ts": 1_787_479_200_000,
        "timer_state": "active",
        "service_state": "inactive",
    }


def test_apply_requires_explicit_phrase_before_any_rollout() -> None:
    module = _module()
    module.require_apply_authorization(apply=False, environ={})
    with pytest.raises(module.PreflightError, match="no mutation attempted"):
        module.require_apply_authorization(apply=True, environ={})
    module.require_apply_authorization(
        apply=True,
        environ={module.APPROVAL_ENV: module.APPROVAL_PHRASE},
    )


def test_contract_is_exactly_three_hash_locked_local_files() -> None:
    module = _module()
    contract = module.load_and_validate_contract(CONTRACT)
    assert tuple(item["path"] for item in contract["required_files"]) == module.EXPECTED_PATHS


def test_remote_state_drift_and_active_cycle_fail_closed() -> None:
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    good = _snapshot(module, contract, before=True)
    module.validate_remote_snapshot(good, contract, before_apply=True)

    drifted = dict(good)
    drifted["files"] = dict(good["files"])
    drifted["files"][module.EXPECTED_PATHS[0]] = "f" * 64
    with pytest.raises(module.PreflightError, match="hash mismatch"):
        module.validate_remote_snapshot(drifted, contract, before_apply=True)

    active = dict(good, service_state="active")
    with pytest.raises(module.PreflightError, match="not safely idle"):
        module.validate_remote_snapshot(active, contract, before_apply=True)

    failed = dict(good, service_state="failed")
    with pytest.raises(module.PreflightError, match="not safely idle"):
        module.validate_remote_snapshot(failed, contract, before_apply=True)


def test_post_deploy_requires_desired_hashes_and_all_columns() -> None:
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    good = _snapshot(module, contract, before=False)
    module.validate_remote_snapshot(good, contract, before_apply=False)

    missing = dict(good)
    missing["position_snapshot_columns"] = ["cycle_ts", *module.REQUIRED_COLUMNS[:-1]]
    with pytest.raises(module.PreflightError, match="missing attribution columns"):
        module.validate_remote_snapshot(missing, contract, before_apply=False)

    natural_cycle_started = dict(good, service_state="active")
    module.validate_remote_snapshot(natural_cycle_started, contract, before_apply=False)


def test_rollout_has_backup_rollback_and_never_forces_a_cycle() -> None:
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    script = module._remote_apply_script(contract, "20260823T143500Z")

    assert "source.backup(target)" in script
    assert "PYRESTORE" in script
    assert ".rollback" in script
    assert "trap rollback ERR INT TERM" in script
    assert 'systemctl stop "$TIMER"' in script
    assert 'systemctl start "$TIMER"' in script
    assert "TradingStore" in script
    assert "paper run" not in script
    assert "--once" not in script
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)

    rollback = module._remote_rollback_script(contract, "20260823T143500Z")
    assert 'systemctl stop "$TIMER"' in rollback
    assert 'systemctl stop "$SERVICE"' in rollback
    assert "PRAGMA integrity_check" in rollback
    assert "DEPLOYMENT_ROLLED_BACK_AFTER_POST_VALIDATION_FAILURE" in rollback
    subprocess.run(["bash", "-n"], input=rollback, text=True, check=True)


def test_failed_postflight_proves_exact_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    before = _snapshot(module, contract, before=True)
    invalid_after = _snapshot(module, contract, before=False)
    invalid_after["files"] = dict(invalid_after["files"])
    invalid_after["files"][module.EXPECTED_PATHS[0]] = "f" * 64
    snapshots = iter((invalid_after, before))
    calls: list[str] = []

    monkeypatch.setattr(module, "apply_deployment", lambda **_: calls.append("apply"))
    monkeypatch.setattr(module, "rollback_deployment", lambda **_: calls.append("rollback"))
    monkeypatch.setattr(module, "remote_snapshot", lambda **_: next(snapshots))

    with pytest.raises(module.PreflightError, match="exact pre-rollout state was restored"):
        module.apply_and_validate(
            host="example",
            identity=Path("/tmp/key"),
            contract=contract,
            before=before,
            stamp="20260823T143500Z",
        )

    assert calls == ["apply", "rollback"]


def test_remote_snapshot_sends_inspector_over_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    observed: dict[str, object] = {}

    def fake_run(command: list[str], *, input_text: str | None = None) -> object:
        observed["command"] = command
        observed["input"] = input_text
        return type("Result", (), {"stdout": '{"database_exists": true}'})()

    monkeypatch.setattr(module, "_run", fake_run)
    result = module.remote_snapshot(host="example", identity=Path("/tmp/key"))

    assert observed["command"][-2:] == ["python3", "-"]
    assert "PRAGMA table_info(positions_snapshots)" in str(observed["input"])
    assert result == {"database_exists": True}


def test_read_only_preflight_observation_is_hash_bound_and_does_not_claim_deployment() -> None:
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    snapshot = _snapshot(module, contract, before=True)
    document = module.build_preflight_observation(
        snapshot=snapshot,
        contract_path=CONTRACT,
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert document["status"] == "PASS_READ_ONLY_PREFLIGHT_DEPLOYMENT_NOT_AUTHORIZED"
    assert document["passes_read_only_preflight"] is True
    assert document["remote_query_performed"] is True
    assert document["remote_mutations_performed"] is False
    assert document["deployment_authorized"] is False
    assert document["forced_cycle_run"] is False
    assert document["remote_snapshot"] == snapshot
    assert document["content_hash"] == module._content_hash(document)
    assert "does not claim deployment" in document["claim_boundary"]
