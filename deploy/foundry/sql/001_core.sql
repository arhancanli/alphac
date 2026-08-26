BEGIN;

CREATE SCHEMA IF NOT EXISTS foundry;

CREATE TABLE foundry.contract_binding (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    lifecycle_schema TEXT NOT NULL,
    lifecycle_version TEXT NOT NULL,
    lifecycle_hash TEXT NOT NULL CHECK (lifecycle_hash ~ '^sha256:[0-9a-f]{64}$'),
    policy_hash TEXT NOT NULL CHECK (policy_hash ~ '^sha256:[0-9a-f]{64}$'),
    observed_identities INTEGER NOT NULL CHECK (observed_identities >= 0),
    identity_budget INTEGER NOT NULL CHECK (identity_budget >= observed_identities),
    next_hard_review INTEGER NOT NULL CHECK (
        next_hard_review >= observed_identities AND next_hard_review <= identity_budget
    ),
    activated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    activated_by TEXT NOT NULL
);

CREATE TABLE foundry.lifecycle_state (
    name TEXT PRIMARY KEY,
    public_label TEXT NOT NULL,
    identity_spent BOOLEAN NOT NULL,
    return_outcome_access BOOLEAN NOT NULL,
    holdout_access BOOLEAN NOT NULL,
    broker_write_access BOOLEAN NOT NULL CHECK (broker_write_access = FALSE),
    terminal BOOLEAN NOT NULL
);

CREATE TABLE foundry.lifecycle_transition (
    source_state TEXT NOT NULL REFERENCES foundry.lifecycle_state(name),
    target_state TEXT NOT NULL REFERENCES foundry.lifecycle_state(name),
    action TEXT NOT NULL,
    authorization_kind TEXT NOT NULL CHECK (authorization_kind IN ('human', 'system')),
    allowed_roles TEXT[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (source_state, target_state, action),
    CHECK (
        (authorization_kind = 'human' AND cardinality(allowed_roles) > 0)
        OR (authorization_kind = 'system' AND cardinality(allowed_roles) = 0)
    )
);

CREATE TABLE foundry.trial (
    id UUID PRIMARY KEY,
    public_trial_id TEXT NOT NULL UNIQUE CHECK (public_trial_id ~ '^ft_[0-9a-f]{16}$'),
    private_hypothesis_hash TEXT NOT NULL UNIQUE CHECK (
        private_hypothesis_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    state TEXT NOT NULL REFERENCES foundry.lifecycle_state(name),
    identity_spent BOOLEAN NOT NULL DEFAULT FALSE,
    foundry_identity_ordinal INTEGER UNIQUE,
    migrated_legacy BOOLEAN NOT NULL DEFAULT FALSE,
    source_commit TEXT,
    image_digest TEXT,
    data_snapshot_hash TEXT,
    job_manifest_hash TEXT,
    artifact_hash TEXT,
    replay_status TEXT NOT NULL DEFAULT 'NOT_RUN' CHECK (
        replay_status IN ('NOT_RUN', 'PENDING', 'PASS', 'FAIL')
    ),
    holdout_consumptions SMALLINT NOT NULL DEFAULT 0 CHECK (
        holdout_consumptions BETWEEN 0 AND 1
    ),
    reserved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (foundry_identity_ordinal IS NULL OR identity_spent),
    CHECK (migrated_legacy OR ((foundry_identity_ordinal IS NOT NULL) = identity_spent)),
    CHECK (NOT migrated_legacy OR foundry_identity_ordinal IS NULL)
);

CREATE TABLE foundry.audit_event (
    sequence BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trial_id UUID NOT NULL REFERENCES foundry.trial(id),
    public_trial_id TEXT NOT NULL,
    prior_state TEXT,
    next_state TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human', 'system')),
    actor_id TEXT NOT NULL,
    actor_role TEXT,
    authorization_reference TEXT NOT NULL,
    source_commit TEXT,
    image_digest TEXT,
    data_snapshot_hash TEXT,
    job_manifest_hash TEXT,
    result_artifact_hash TEXT,
    event_payload_hash TEXT NOT NULL CHECK (event_payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX audit_event_trial_sequence_idx
    ON foundry.audit_event (trial_id, sequence);

CREATE TABLE foundry.job (
    id UUID PRIMARY KEY,
    trial_id UUID NOT NULL REFERENCES foundry.trial(id),
    kind TEXT NOT NULL CHECK (kind IN (
        'SNAPSHOT', 'BOUNDED_RUN', 'VALIDATION', 'CLEAN_REPLAY', 'HOLDOUT', 'SANITIZE'
    )),
    manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    image_digest TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (
        status IN ('QUEUED', 'LEASED', 'SUCCEEDED', 'FAILED', 'QUOTA_BREACH', 'CANCELLED')
    ),
    cpu_millis INTEGER NOT NULL CHECK (cpu_millis BETWEEN 100 AND 32000),
    memory_mebibytes INTEGER NOT NULL CHECK (memory_mebibytes BETWEEN 128 AND 131072),
    process_limit INTEGER NOT NULL CHECK (process_limit BETWEEN 1 AND 4096),
    disk_mebibytes INTEGER NOT NULL CHECK (disk_mebibytes BETWEEN 64 AND 1048576),
    wall_seconds INTEGER NOT NULL CHECK (wall_seconds BETWEEN 1 AND 86400),
    network_policy TEXT NOT NULL CHECK (network_policy IN (
        'NONE', 'DATA_GATEWAY_ONLY', 'RESEARCH_OBJECTS_ONLY', 'HOLDOUT_ONE_SHOT',
        'PUBLICATION_ONLY'
    )),
    lease_owner TEXT,
    lease_until TIMESTAMPTZ,
    attempts SMALLINT NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 10),
    max_attempts SMALLINT NOT NULL DEFAULT 1 CHECK (max_attempts BETWEEN 1 AND 10),
    result_artifact_hash TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE (trial_id, kind, manifest_hash),
    CHECK (
        (status = 'LEASED' AND lease_owner IS NOT NULL AND lease_until IS NOT NULL)
        OR (status <> 'LEASED')
    )
);

CREATE INDEX job_claim_idx ON foundry.job (queued_at, id)
    WHERE status IN ('QUEUED', 'LEASED');

CREATE FUNCTION foundry.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'foundry audit events are append-only';
END;
$$;

CREATE TRIGGER audit_event_no_update
BEFORE UPDATE OR DELETE ON foundry.audit_event
FOR EACH ROW EXECUTE FUNCTION foundry.reject_mutation();

CREATE FUNCTION foundry.register_feasibility(
    p_trial_id UUID,
    p_public_trial_id TEXT,
    p_private_hypothesis_hash TEXT,
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
    INSERT INTO foundry.trial (
        id, public_trial_id, private_hypothesis_hash, state, identity_spent
    ) VALUES (
        p_trial_id, p_public_trial_id, p_private_hypothesis_hash, 'FEASIBILITY', FALSE
    ) RETURNING * INTO created;

    INSERT INTO foundry.audit_event (
        trial_id, public_trial_id, prior_state, next_state, action,
        actor_kind, actor_id, actor_role, authorization_reference, event_payload_hash
    ) VALUES (
        created.id, created.public_trial_id, NULL, 'FEASIBILITY', 'register_feasibility',
        'human', p_actor_id, 'research_author', p_authorization_reference, p_event_payload_hash
    );

    RETURN created;
END;
$$;

CREATE FUNCTION foundry.transition_trial(
    p_trial_id UUID,
    p_expected_state TEXT,
    p_target_state TEXT,
    p_action TEXT,
    p_actor_kind TEXT,
    p_actor_id TEXT,
    p_actor_role TEXT,
    p_authorization_reference TEXT,
    p_event_payload_hash TEXT,
    p_source_commit TEXT DEFAULT NULL,
    p_image_digest TEXT DEFAULT NULL,
    p_data_snapshot_hash TEXT DEFAULT NULL,
    p_job_manifest_hash TEXT DEFAULT NULL,
    p_result_artifact_hash TEXT DEFAULT NULL
) RETURNS foundry.trial
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    current_trial foundry.trial;
    permitted foundry.lifecycle_transition;
    target foundry.lifecycle_state;
    binding foundry.contract_binding;
    reserved_count INTEGER;
    next_ordinal INTEGER;
BEGIN
    SELECT * INTO STRICT current_trial
      FROM foundry.trial
     WHERE id = p_trial_id
     FOR UPDATE;

    IF current_trial.state <> p_expected_state THEN
        RAISE EXCEPTION 'stale transition: expected %, observed %',
            p_expected_state, current_trial.state;
    END IF;

    SELECT * INTO STRICT permitted
      FROM foundry.lifecycle_transition
     WHERE source_state = p_expected_state
       AND target_state = p_target_state
       AND action = p_action;

    IF permitted.authorization_kind <> p_actor_kind THEN
        RAISE EXCEPTION 'transition % requires % authorization',
            p_action, permitted.authorization_kind;
    END IF;
    IF p_actor_kind = 'human' AND NOT (p_actor_role = ANY(permitted.allowed_roles)) THEN
        RAISE EXCEPTION 'actor role is not authorized for transition %', p_action;
    END IF;
    IF p_actor_kind = 'system' AND p_actor_role IS NOT NULL THEN
        RAISE EXCEPTION 'system transition cannot assert a human role';
    END IF;

    SELECT * INTO STRICT target
      FROM foundry.lifecycle_state
     WHERE name = p_target_state;

    IF p_target_state = 'RESERVED' THEN
        SELECT * INTO STRICT binding FROM foundry.contract_binding WHERE singleton;
        SELECT count(*) INTO reserved_count
          FROM foundry.trial
         WHERE foundry_identity_ordinal IS NOT NULL;
        next_ordinal := binding.observed_identities + reserved_count + 1;
        IF next_ordinal > binding.identity_budget THEN
            RAISE EXCEPTION 'identity budget exhausted at %', binding.identity_budget;
        END IF;
        IF next_ordinal > binding.next_hard_review THEN
            RAISE EXCEPTION 'mandatory policy review reached at identity %',
                binding.next_hard_review;
        END IF;
        current_trial.foundry_identity_ordinal := next_ordinal;
        current_trial.reserved_at := clock_timestamp();
    END IF;

    IF p_target_state = 'HOLDOUT_CONSUMED' THEN
        IF current_trial.holdout_consumptions <> 0 THEN
            RAISE EXCEPTION 'holdout already consumed for trial %', current_trial.public_trial_id;
        END IF;
        current_trial.holdout_consumptions := 1;
    END IF;

    UPDATE foundry.trial
       SET state = p_target_state,
           identity_spent = target.identity_spent,
           foundry_identity_ordinal = current_trial.foundry_identity_ordinal,
           reserved_at = current_trial.reserved_at,
           holdout_consumptions = current_trial.holdout_consumptions,
           source_commit = COALESCE(p_source_commit, source_commit),
           image_digest = COALESCE(p_image_digest, image_digest),
           data_snapshot_hash = COALESCE(p_data_snapshot_hash, data_snapshot_hash),
           job_manifest_hash = COALESCE(p_job_manifest_hash, job_manifest_hash),
           artifact_hash = COALESCE(p_result_artifact_hash, artifact_hash),
           updated_at = clock_timestamp()
     WHERE id = p_trial_id
     RETURNING * INTO current_trial;

    INSERT INTO foundry.audit_event (
        trial_id, public_trial_id, prior_state, next_state, action,
        actor_kind, actor_id, actor_role, authorization_reference,
        source_commit, image_digest, data_snapshot_hash, job_manifest_hash,
        result_artifact_hash, event_payload_hash
    ) VALUES (
        current_trial.id, current_trial.public_trial_id, p_expected_state, p_target_state, p_action,
        p_actor_kind, p_actor_id, p_actor_role, p_authorization_reference,
        p_source_commit, p_image_digest, p_data_snapshot_hash, p_job_manifest_hash,
        p_result_artifact_hash, p_event_payload_hash
    );

    RETURN current_trial;
END;
$$;

CREATE FUNCTION foundry.claim_job(p_worker_id TEXT, p_lease_seconds INTEGER)
RETURNS SETOF foundry.job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
BEGIN
    IF p_worker_id !~ '^[a-z0-9][a-z0-9_.-]{2,95}$' THEN
        RAISE EXCEPTION 'worker identifier is malformed';
    END IF;
    IF p_lease_seconds < 10 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease duration is outside 10..3600 seconds';
    END IF;

    RETURN QUERY
    WITH candidate AS (
        SELECT id
          FROM foundry.job
         WHERE (
             status = 'QUEUED'
             OR (status = 'LEASED' AND lease_until < clock_timestamp())
         )
           AND attempts < max_attempts
         ORDER BY queued_at, id
         FOR UPDATE SKIP LOCKED
         LIMIT 1
    )
    UPDATE foundry.job AS job
       SET status = 'LEASED',
           lease_owner = p_worker_id,
           lease_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
           attempts = attempts + 1,
           started_at = COALESCE(started_at, clock_timestamp())
      FROM candidate
     WHERE job.id = candidate.id
    RETURNING job.*;
END;
$$;

CREATE FUNCTION foundry.enqueue_job(
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
    p_max_attempts INTEGER
) RETURNS foundry.job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    trial_state TEXT;
    created foundry.job;
BEGIN
    SELECT state INTO STRICT trial_state
      FROM foundry.trial
     WHERE id = p_trial_id
     FOR UPDATE;

    IF trial_state NOT IN (
        'RESERVED', 'SNAPSHOT_FROZEN', 'RUNNING', 'VALIDATING',
        'HOLDOUT_AUTHORIZED', 'HOLDOUT_CONSUMED'
    ) THEN
        RAISE EXCEPTION 'trial state % cannot enqueue outcome-bearing work', trial_state;
    END IF;

    INSERT INTO foundry.job (
        id, trial_id, kind, manifest_hash, image_digest, source_commit,
        cpu_millis, memory_mebibytes, process_limit, disk_mebibytes,
        wall_seconds, network_policy, max_attempts
    ) VALUES (
        p_job_id, p_trial_id, p_kind, p_manifest_hash, p_image_digest, p_source_commit,
        p_cpu_millis, p_memory_mebibytes, p_process_limit, p_disk_mebibytes,
        p_wall_seconds, p_network_policy, p_max_attempts::SMALLINT
    ) RETURNING * INTO created;
    RETURN created;
END;
$$;

CREATE FUNCTION foundry.complete_job(
    p_job_id UUID,
    p_worker_id TEXT,
    p_status TEXT,
    p_result_artifact_hash TEXT
) RETURNS foundry.job
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = foundry, pg_temp
AS $$
DECLARE
    completed foundry.job;
BEGIN
    IF p_status NOT IN ('SUCCEEDED', 'FAILED', 'QUOTA_BREACH') THEN
        RAISE EXCEPTION 'invalid terminal job status: %', p_status;
    END IF;
    IF p_status = 'SUCCEEDED' AND p_result_artifact_hash !~ '^sha256:[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'successful job requires a result artifact hash';
    END IF;

    UPDATE foundry.job
       SET status = p_status,
           result_artifact_hash = p_result_artifact_hash,
           lease_owner = NULL,
           lease_until = NULL,
           completed_at = clock_timestamp()
     WHERE id = p_job_id
       AND status = 'LEASED'
       AND lease_owner = p_worker_id
       AND lease_until >= clock_timestamp()
     RETURNING * INTO STRICT completed;
    RETURN completed;
END;
$$;

REVOKE ALL ON SCHEMA foundry FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA foundry FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA foundry FROM PUBLIC;

COMMIT;
