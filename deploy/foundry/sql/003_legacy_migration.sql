BEGIN;

CREATE TABLE foundry.legacy_migration (
    migration_key TEXT PRIMARY KEY CHECK (migration_key ~ '^[a-z0-9][a-z0-9-]{2,95}$'),
    trial_id UUID NOT NULL UNIQUE REFERENCES foundry.trial(id),
    source_identity_key TEXT NOT NULL UNIQUE CHECK (source_identity_key ~ '^[0-9a-f]{16}$'),
    identity_packet_hash TEXT NOT NULL UNIQUE CHECK (
        identity_packet_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    input_snapshot_hash TEXT NOT NULL CHECK (input_snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
    expected_result_hash TEXT NOT NULL CHECK (expected_result_hash ~ '^sha256:[0-9a-f]{64}$'),
    prior_replay_receipt_hash TEXT NOT NULL CHECK (
        prior_replay_receipt_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    migration_manifest_hash TEXT NOT NULL UNIQUE CHECK (
        migration_manifest_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TRIGGER legacy_migration_no_update
BEFORE UPDATE OR DELETE ON foundry.legacy_migration
FOR EACH ROW EXECUTE FUNCTION foundry.reject_mutation();

CREATE FUNCTION foundry.import_legacy_killed_trial(
    p_migration_key TEXT,
    p_trial_id UUID,
    p_public_trial_id TEXT,
    p_source_identity_key TEXT,
    p_private_hypothesis_hash TEXT,
    p_historical_recorded_at TIMESTAMPTZ,
    p_identity_packet_hash TEXT,
    p_input_snapshot_hash TEXT,
    p_expected_result_hash TEXT,
    p_prior_replay_receipt_hash TEXT,
    p_migration_manifest_hash TEXT,
    p_source_commit TEXT,
    p_actor_id TEXT,
    p_authorization_reference TEXT,
    p_event_payload_hash TEXT
) RETURNS foundry.trial
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    created foundry.trial;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM foundry.contract_binding WHERE singleton) THEN
        RAISE EXCEPTION 'Foundry contracts must be bound before a legacy import';
    END IF;
    IF p_source_commit !~ '^[0-9a-f]{40}$' THEN
        RAISE EXCEPTION 'legacy import requires an exact source commit';
    END IF;

    INSERT INTO foundry.trial (
        id, public_trial_id, private_hypothesis_hash, state, identity_spent,
        foundry_identity_ordinal, migrated_legacy, source_commit, data_snapshot_hash,
        replay_status, holdout_consumptions, reserved_at
    ) VALUES (
        p_trial_id, p_public_trial_id, p_private_hypothesis_hash, 'KILLED', TRUE,
        NULL, TRUE, p_source_commit, p_input_snapshot_hash,
        'NOT_RUN', 0, p_historical_recorded_at
    ) RETURNING * INTO created;

    INSERT INTO foundry.legacy_migration (
        migration_key, trial_id, source_identity_key, identity_packet_hash,
        input_snapshot_hash, expected_result_hash, prior_replay_receipt_hash,
        migration_manifest_hash
    ) VALUES (
        p_migration_key, created.id, p_source_identity_key, p_identity_packet_hash,
        p_input_snapshot_hash, p_expected_result_hash, p_prior_replay_receipt_hash,
        p_migration_manifest_hash
    );

    INSERT INTO foundry.audit_event (
        trial_id, public_trial_id, prior_state, next_state, action,
        actor_kind, actor_id, actor_role, authorization_reference,
        source_commit, data_snapshot_hash, result_artifact_hash, event_payload_hash
    ) VALUES (
        created.id, created.public_trial_id, NULL, 'KILLED', 'import_legacy_killed_identity',
        'human', p_actor_id, 'migration_operator', p_authorization_reference,
        p_source_commit, p_input_snapshot_hash, p_identity_packet_hash, p_event_payload_hash
    );

    RETURN created;
END;
$$;

CREATE OR REPLACE FUNCTION foundry.enqueue_job(
    p_job_id UUID,
    p_trial_id UUID,
    p_kind TEXT,
    p_manifest_hash TEXT,
    p_image_digest TEXT,
    p_source_commit TEXT,
    p_cpu_millis INTEGER,
    p_memory_mebibytes INTEGER,
    p_process_limit INTEGER,
    p_disk_mebibytes INTEGER,
    p_wall_seconds INTEGER,
    p_network_policy TEXT,
    p_max_attempts SMALLINT
) RETURNS foundry.job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    current_trial foundry.trial;
    created foundry.job;
BEGIN
    SELECT * INTO STRICT current_trial
      FROM foundry.trial
     WHERE id = p_trial_id
     FOR UPDATE;

    IF current_trial.state IN (
        'RESERVED', 'SNAPSHOT_FROZEN', 'RUNNING', 'VALIDATING',
        'HOLDOUT_AUTHORIZED', 'HOLDOUT_CONSUMED'
    ) THEN
        NULL;
    ELSIF current_trial.state = 'KILLED' AND current_trial.migrated_legacy THEN
        IF p_kind = 'CLEAN_REPLAY' AND current_trial.replay_status <> 'NOT_RUN' THEN
            RAISE EXCEPTION 'legacy clean replay is one-shot and currently %',
                current_trial.replay_status;
        ELSIF p_kind = 'SANITIZE' AND current_trial.replay_status <> 'PASS' THEN
            RAISE EXCEPTION 'legacy sanitization requires a passing clean replay';
        ELSIF p_kind NOT IN ('CLEAN_REPLAY', 'SANITIZE') THEN
            RAISE EXCEPTION 'migrated killed identity permits replay and sanitization only';
        END IF;
    ELSE
        RAISE EXCEPTION 'trial state % cannot enqueue outcome-bearing work',
            current_trial.state;
    END IF;

    INSERT INTO foundry.job (
        id, trial_id, kind, manifest_hash, image_digest, source_commit,
        cpu_millis, memory_mebibytes, process_limit, disk_mebibytes,
        wall_seconds, network_policy, max_attempts
    ) VALUES (
        p_job_id, p_trial_id, p_kind, p_manifest_hash, p_image_digest, p_source_commit,
        p_cpu_millis, p_memory_mebibytes, p_process_limit, p_disk_mebibytes,
        p_wall_seconds, p_network_policy, p_max_attempts
    ) RETURNING * INTO created;

    IF current_trial.migrated_legacy AND p_kind = 'CLEAN_REPLAY' THEN
        UPDATE foundry.trial
           SET replay_status = 'PENDING', updated_at = clock_timestamp()
         WHERE id = p_trial_id;
    END IF;
    RETURN created;
END;
$$;

CREATE FUNCTION foundry.finalize_legacy_replay(
    p_trial_id UUID,
    p_job_id UUID,
    p_observed_object_hash TEXT,
    p_validator_id TEXT,
    p_authorization_reference TEXT,
    p_event_payload_hash TEXT
) RETURNS foundry.trial
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    current_trial foundry.trial;
    migration foundry.legacy_migration;
    replay_job foundry.job;
    next_replay_status TEXT;
    event_action TEXT;
BEGIN
    SELECT * INTO STRICT current_trial
      FROM foundry.trial
     WHERE id = p_trial_id
     FOR UPDATE;
    SELECT * INTO STRICT migration
      FROM foundry.legacy_migration
     WHERE trial_id = p_trial_id;
    SELECT * INTO STRICT replay_job
      FROM foundry.job
     WHERE id = p_job_id AND trial_id = p_trial_id;

    IF current_trial.state <> 'KILLED' OR NOT current_trial.migrated_legacy THEN
        RAISE EXCEPTION 'only a migrated killed identity can finalize legacy replay';
    END IF;
    IF current_trial.replay_status <> 'PENDING' OR replay_job.kind <> 'CLEAN_REPLAY' THEN
        RAISE EXCEPTION 'legacy replay is not pending for the supplied clean-replay job';
    END IF;
    IF replay_job.status NOT IN ('SUCCEEDED', 'FAILED', 'QUOTA_BREACH') THEN
        RAISE EXCEPTION 'legacy replay job is not terminal';
    END IF;
    IF p_observed_object_hash !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'validator observed object hash is malformed';
    END IF;

    IF replay_job.status = 'SUCCEEDED'
       AND replay_job.result_artifact_hash = migration.expected_result_hash
       AND p_observed_object_hash = migration.expected_result_hash THEN
        next_replay_status := 'PASS';
        event_action := 'confirm_legacy_clean_replay';
    ELSE
        next_replay_status := 'FAIL';
        event_action := 'reject_legacy_clean_replay';
    END IF;

    UPDATE foundry.trial
       SET replay_status = next_replay_status, updated_at = clock_timestamp()
     WHERE id = p_trial_id
     RETURNING * INTO current_trial;

    INSERT INTO foundry.audit_event (
        trial_id, public_trial_id, prior_state, next_state, action,
        actor_kind, actor_id, actor_role, authorization_reference,
        source_commit, image_digest, job_manifest_hash, result_artifact_hash,
        event_payload_hash
    ) VALUES (
        current_trial.id, current_trial.public_trial_id, 'KILLED', 'KILLED', event_action,
        'system', p_validator_id, NULL, p_authorization_reference,
        replay_job.source_commit, replay_job.image_digest, replay_job.manifest_hash,
        p_observed_object_hash, p_event_payload_hash
    );
    RETURN current_trial;
END;
$$;

CREATE FUNCTION foundry.publish_legacy_packet(
    p_trial_id UUID,
    p_job_id UUID,
    p_observed_sanitized_hash TEXT,
    p_publisher_id TEXT,
    p_authorization_reference TEXT,
    p_event_payload_hash TEXT
) RETURNS foundry.trial
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    current_trial foundry.trial;
    sanitize_job foundry.job;
BEGIN
    SELECT * INTO STRICT current_trial
      FROM foundry.trial
     WHERE id = p_trial_id
     FOR UPDATE;
    SELECT * INTO STRICT sanitize_job
      FROM foundry.job
     WHERE id = p_job_id AND trial_id = p_trial_id;

    IF current_trial.state <> 'KILLED' OR NOT current_trial.migrated_legacy
       OR current_trial.replay_status <> 'PASS' THEN
        RAISE EXCEPTION 'legacy publication requires a replayed migrated killed identity';
    END IF;
    IF sanitize_job.kind <> 'SANITIZE' OR sanitize_job.status <> 'SUCCEEDED'
       OR sanitize_job.result_artifact_hash IS NULL THEN
        RAISE EXCEPTION 'legacy publication requires a successful sanitizer job';
    END IF;
    IF p_observed_sanitized_hash !~ '^sha256:[0-9a-f]{64}$'
       OR p_observed_sanitized_hash <> sanitize_job.result_artifact_hash THEN
        RAISE EXCEPTION 'publisher-observed sanitizer hash differs from worker result';
    END IF;

    UPDATE foundry.trial
       SET artifact_hash = p_observed_sanitized_hash,
           updated_at = clock_timestamp()
     WHERE id = p_trial_id
     RETURNING * INTO current_trial;

    INSERT INTO foundry.audit_event (
        trial_id, public_trial_id, prior_state, next_state, action,
        actor_kind, actor_id, actor_role, authorization_reference,
        source_commit, image_digest, job_manifest_hash, result_artifact_hash,
        event_payload_hash
    ) VALUES (
        current_trial.id, current_trial.public_trial_id, 'KILLED', 'KILLED',
        'publish_legacy_sanitized_packet', 'system', p_publisher_id, NULL,
        p_authorization_reference, sanitize_job.source_commit, sanitize_job.image_digest,
        sanitize_job.manifest_hash, p_observed_sanitized_hash, p_event_payload_hash
    );
    RETURN current_trial;
END;
$$;

REVOKE ALL ON TABLE foundry.legacy_migration FROM PUBLIC;
REVOKE ALL ON FUNCTION foundry.import_legacy_killed_trial(
    TEXT, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION foundry.finalize_legacy_replay(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION foundry.publish_legacy_packet(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;

GRANT USAGE ON SCHEMA foundry TO foundry_migrator, foundry_validator, foundry_publisher;
GRANT EXECUTE ON FUNCTION foundry.import_legacy_killed_trial(
    TEXT, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TEXT, TEXT, TEXT
) TO foundry_migrator;
GRANT EXECUTE ON FUNCTION foundry.finalize_legacy_replay(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO foundry_validator;
GRANT EXECUTE ON FUNCTION foundry.publish_legacy_packet(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO foundry_publisher;

COMMIT;
