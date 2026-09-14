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
    files = module.all_files(contract)
    columns = ["cycle_ts", "instrument_id", "qty", "avg_entry_price", "opened_ts"]
    tables = ["cycles", "equity_curve", "ladder_state", "positions_snapshots"]
    if module.expected_pre_rollout_schema(contract) == "MIGRATED" or not before:
        columns.extend(module.REQUIRED_COLUMNS)
    if not before:
        tables.extend(module.required_tables(contract))
    return {
        "database_exists": True,
        "database_sha256": "0" * 64,
        "files": {item["path"]: item.get(hash_key) for item in files},
        "position_snapshot_columns": columns,
        "tables": sorted(set(tables)),
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
    """The verifier's three files stay the three; companions ride beside them, hash-locked."""
    module = _module()
    contract = module.load_and_validate_contract(CONTRACT)
    assert tuple(item["path"] for item in contract["required_files"]) == module.EXPECTED_PATHS
    for item in module.companion_files(contract):
        assert item["path"] not in module.EXPECTED_PATHS
        assert module._sha256(ROOT / item["path"]) == item["desired_sha256"]
        assert item["remote_sha256"] is None or len(item["remote_sha256"]) == 64


def _companion_contract(module: ModuleType, tmp_path: Path) -> dict[str, object]:
    """A contract whose companions include a file the host does not have yet."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    present = ROOT / "src" / "alphaforge" / "portfolio" / "strategy.py"
    absent = ROOT / "src" / "alphaforge" / "risk" / "book_ladder.py"
    contract["companion_files"] = [
        {
            "path": "src/alphaforge/portfolio/strategy.py",
            "desired_sha256": module._sha256(present),
            "remote_sha256": "1" * 64,
        },
        {
            "path": "src/alphaforge/risk/book_ladder.py",
            "desired_sha256": module._sha256(absent),
            "remote_sha256": None,
        },
    ]
    contract["expected_pre_rollout_schema"] = "MIGRATED"
    contract["required_tables_after_rollout"] = ["strategy_last_targets"]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def test_companions_are_hash_locked_and_an_absent_one_is_installed_then_removed_on_rollback(
    tmp_path: Path,
) -> None:
    module = _module()
    _companion_contract(module, tmp_path)
    path = tmp_path / "contract.json"
    loaded = module.load_and_validate_contract(path)
    assert [c["path"] for c in module.companion_files(loaded)] == [
        "src/alphaforge/portfolio/strategy.py",
        "src/alphaforge/risk/book_ladder.py",
    ]
    script = module._remote_apply_script(loaded, "20260914T150000Z")
    assert "[ ! -e /opt/alphaforge/src/alphaforge/risk/book_ladder.py ]" in script
    assert "require_hash /opt/alphaforge/src/alphaforge/portfolio/strategy.py " + "1" * 64 in script
    assert "rm -f /opt/alphaforge/src/alphaforge/risk/book_ladder.py" in script  # rollback branch
    assert "import alphaforge.live.loop, alphaforge.cli.paper_cmds" in script
    assert "missing tables after migration" in script and "strategy_last_targets" in script
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)
    rollback = module._remote_rollback_script(loaded, "20260914T150000Z")
    assert "rm -f /opt/alphaforge/src/alphaforge/risk/book_ladder.py" in rollback
    assert "[ ! -e /opt/alphaforge/src/alphaforge/risk/book_ladder.py ]" in rollback
    subprocess.run(["bash", "-n"], input=rollback, text=True, check=True)

    before = _snapshot(module, loaded, before=True)
    assert before["files"]["src/alphaforge/risk/book_ladder.py"] is None
    module.validate_remote_snapshot(before, loaded, before_apply=True)
    after = _snapshot(module, loaded, before=False)
    module.validate_remote_snapshot(after, loaded, before_apply=False)
    after["tables"] = [t for t in after["tables"] if t != "strategy_last_targets"]
    with pytest.raises(module.PreflightError, match="missing tables"):
        module.validate_remote_snapshot(after, loaded, before_apply=False)


def test_a_drifted_companion_fails_the_contract_closed(tmp_path: Path) -> None:
    module = _module()
    contract = _companion_contract(module, tmp_path)
    contract["companion_files"][0]["desired_sha256"] = "2" * 64
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(module.PreflightError, match="local source drift"):
        module.load_and_validate_contract(path)
    contract["companion_files"][0]["desired_sha256"] = module._sha256(
        ROOT / "src" / "alphaforge" / "portfolio" / "strategy.py"
    )
    contract["companion_files"].append(dict(contract["required_files"][0]))
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(module.PreflightError, match="already required"):
        module.load_and_validate_contract(path)


def test_a_migrated_host_is_only_accepted_when_the_contract_declares_it(tmp_path: Path) -> None:
    module = _module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    before = _snapshot(module, contract, before=True)
    if module.expected_pre_rollout_schema(contract) == "MIGRATED":
        legacy = dict(contract, expected_pre_rollout_schema="PRE_MIGRATION")
        with pytest.raises(module.PreflightError, match="no longer the declared pre-migration"):
            module.validate_remote_snapshot(before, legacy, before_apply=True)
    else:
        migrated = dict(contract, expected_pre_rollout_schema="MIGRATED")
        with pytest.raises(module.PreflightError, match="not the declared migrated schema"):
            module.validate_remote_snapshot(before, migrated, before_apply=True)


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
