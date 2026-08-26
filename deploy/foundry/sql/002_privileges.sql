BEGIN;

GRANT USAGE ON SCHEMA foundry TO foundry_researchd, foundry_worker, foundry_status;

GRANT SELECT ON foundry.trial, foundry.job, foundry.audit_event TO foundry_researchd;
GRANT SELECT ON foundry.contract_binding, foundry.lifecycle_state,
    foundry.lifecycle_transition TO foundry_researchd;
GRANT EXECUTE ON FUNCTION foundry.register_feasibility(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT
) TO foundry_researchd;
GRANT EXECUTE ON FUNCTION foundry.transition_trial(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TEXT, TEXT, TEXT, TEXT
) TO foundry_researchd;
GRANT EXECUTE ON FUNCTION foundry.enqueue_job(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER, INTEGER,
    INTEGER, TEXT, SMALLINT
) TO foundry_researchd;

GRANT EXECUTE ON FUNCTION foundry.claim_job(TEXT, INTEGER) TO foundry_worker;
GRANT EXECUTE ON FUNCTION foundry.complete_job(UUID, TEXT, TEXT, TEXT) TO foundry_worker;

GRANT SELECT (
    public_trial_id, state, identity_spent, reserved_at, updated_at,
    artifact_hash, replay_status
) ON foundry.trial TO foundry_status;
GRANT SELECT (
    status, queued_at, started_at, completed_at
) ON foundry.job TO foundry_status;

ALTER DEFAULT PRIVILEGES IN SCHEMA foundry REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA foundry REVOKE ALL ON FUNCTIONS FROM PUBLIC;

COMMIT;
