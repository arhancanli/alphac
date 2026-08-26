from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "deploy" / "foundry" / "sql" / "001_core.sql"
PRIVILEGES = ROOT / "deploy" / "foundry" / "sql" / "002_privileges.sql"
MANIFEST = ROOT / "config" / "foundry_deployment_manifest.json"


def test_database_contract_is_append_only_budgeted_and_concurrent() -> None:
    sql = CORE.read_text(encoding="utf-8")
    assert "CREATE TRIGGER audit_event_no_update" in sql
    assert "BEFORE UPDATE OR DELETE ON foundry.audit_event" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "CREATE FUNCTION foundry.register_feasibility" in sql
    assert "CREATE FUNCTION foundry.enqueue_job" in sql
    assert "next_ordinal > binding.next_hard_review" in sql
    assert "holdout_consumptions BETWEEN 0 AND 1" in sql
    assert "broker_write_access BOOLEAN NOT NULL CHECK (broker_write_access = FALSE)" in sql
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA foundry FROM PUBLIC" in sql


def test_worker_and_status_roles_have_no_general_table_write_grant() -> None:
    sql = PRIVILEGES.read_text(encoding="utf-8")
    assert "GRANT EXECUTE ON FUNCTION foundry.claim_job" in sql
    assert "GRANT EXECUTE ON FUNCTION foundry.complete_job" in sql
    assert "GRANT SELECT (" in sql
    assert "ON foundry.trial TO foundry_status" in sql
    assert "GRANT INSERT ON foundry.trial TO foundry_worker" not in sql
    assert "GRANT UPDATE ON foundry.trial TO foundry_worker" not in sql
    assert "GRANT SELECT ON foundry.audit_event TO foundry_status" not in sql
    assert "GRANT SELECT, INSERT, UPDATE ON foundry.trial" not in sql
    assert "GRANT SELECT, INSERT, UPDATE ON foundry.job" not in sql


def test_deployment_manifest_preserves_execution_and_holdout_isolation() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "PLANNED_NOT_APPLIED"
    assert manifest["provider"]["dedicated_deployment_principal_required"] is True
    assert manifest["provider"]["existing_api_optimizer_principals_reusable"] is False
    assert manifest["networks"]["research"]["public_networking"] is False
    assert manifest["networks"]["holdout"]["peered_with_research"] is False
    assert manifest["networks"]["execution"]["managed_by_this_manifest"] is False
    assert manifest["credentials"]["broker_credentials_present"] is False
    assert manifest["object_storage"]["application_keys_managed_in_main_terraform_state"] is False
