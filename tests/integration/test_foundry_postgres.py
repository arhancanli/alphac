from __future__ import annotations

import importlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from alphaforge.foundry.contract import FoundryContract
from alphaforge.foundry.database import FoundryDatabase, TransitionRequest
from alphaforge.foundry.policy import load_foundry_policy

ADMIN_DSN = os.environ.get("FOUNDRY_TEST_ADMIN_DSN")
RESEARCHD_DSN = os.environ.get("FOUNDRY_TEST_RESEARCHD_DSN")
WORKER_DSN = os.environ.get("FOUNDRY_TEST_WORKER_DSN")
STATUS_DSN = os.environ.get("FOUNDRY_TEST_STATUS_DSN")
psycopg = importlib.import_module("psycopg") if ADMIN_DSN else None

pytestmark = pytest.mark.skipif(
    not all((ADMIN_DSN, RESEARCHD_DSN, WORKER_DSN, STATUS_DSN)),
    reason="Foundry PostgreSQL role DSNs are not configured",
)


@pytest.fixture(scope="module")
def reserved_trial() -> dict[str, object]:
    assert ADMIN_DSN is not None
    assert psycopg is not None
    assert RESEARCHD_DSN is not None
    contract = FoundryContract.load()
    FoundryDatabase(ADMIN_DSN).bind_contract(
        contract=contract,
        policy=load_foundry_policy(),
        activated_by="ci:foundry-database-contract",
    )
    database = FoundryDatabase(RESEARCHD_DSN)
    created = database.create_feasibility_trial(
        private_hypothesis={"family": "ci-fixture", "outcome_data_read": False},
        actor_id="ci-research-author",
        authorization_reference="ci://proposal/1",
    )
    proposed = database.transition(
        TransitionRequest(
            trial_id=created["id"],
            expected_state="FEASIBILITY",
            target_state="PROPOSED",
            action="submit_preregistration",
            actor_kind="human",
            actor_id="ci-research-author",
            actor_role="research_author",
            authorization_reference="ci://preregistration/1",
        ),
        contract=contract,
    )
    return database.transition(
        TransitionRequest(
            trial_id=proposed["id"],
            expected_state="PROPOSED",
            target_state="RESERVED",
            action="reserve_identity",
            actor_kind="human",
            actor_id="ci-research-approver",
            actor_role="research_approver",
            authorization_reference="ci://approval/1",
        ),
        contract=contract,
    )


def test_reservation_is_transactional_and_appends_audit_events(
    reserved_trial: dict[str, object],
) -> None:
    assert ADMIN_DSN is not None
    assert psycopg is not None
    assert reserved_trial["state"] == "RESERVED"
    assert reserved_trial["identity_spent"] is True
    assert reserved_trial["foundry_identity_ordinal"] == 229
    with psycopg.connect(ADMIN_DSN) as connection:
        events = connection.execute(
            "SELECT prior_state, next_state, action FROM foundry.audit_event "
            "WHERE trial_id = %s ORDER BY sequence",
            (reserved_trial["id"],),
        ).fetchall()
    assert events == [
        (None, "FEASIBILITY", "register_feasibility"),
        ("FEASIBILITY", "PROPOSED", "submit_preregistration"),
        ("PROPOSED", "RESERVED", "reserve_identity"),
    ]


def test_audit_event_rejects_update_even_for_database_owner(
    reserved_trial: dict[str, object],
) -> None:
    assert ADMIN_DSN is not None
    with (
        psycopg.connect(ADMIN_DSN) as connection,
        pytest.raises(psycopg.errors.RaiseException, match="append-only"),
    ):
        connection.execute(
            "UPDATE foundry.audit_event SET action = 'rewritten' WHERE trial_id = %s",
            (reserved_trial["id"],),
        )


def test_researchd_cannot_bypass_the_transition_function(
    reserved_trial: dict[str, object],
) -> None:
    assert RESEARCHD_DSN is not None
    assert psycopg is not None
    with (
        psycopg.connect(RESEARCHD_DSN) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute(
            "UPDATE foundry.trial SET state = 'ADMITTED' WHERE id = %s",
            (reserved_trial["id"],),
        )


def test_worker_lease_is_single_claim_under_concurrency(
    reserved_trial: dict[str, object],
) -> None:
    assert RESEARCHD_DSN is not None
    assert WORKER_DSN is not None
    assert psycopg is not None
    job_id = uuid.uuid4()
    with psycopg.connect(RESEARCHD_DSN) as connection:
        connection.execute(
            """
            SELECT * FROM foundry.enqueue_job(
                %s, %s, 'SNAPSHOT', %s, %s, %s,
                1000, 512, 64, 1024, 300, 'DATA_GATEWAY_ONLY', 1
            )
            """,
            (
                job_id,
                reserved_trial["id"],
                "sha256:" + "1" * 64,
                "registry.invalid/foundry@sha256:" + "2" * 64,
                "a" * 40,
            ),
        )

    def claim(worker: str) -> dict[str, object] | None:
        return FoundryDatabase(WORKER_DSN).claim_job(worker, 60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ("worker-ci-1", "worker-ci-2")))
    won = [claim for claim in claims if claim is not None]
    assert len(won) == 1
    assert won[0]["id"] == job_id
    assert won[0]["attempts"] == 1


def test_status_role_cannot_read_private_hypothesis_hash() -> None:
    assert STATUS_DSN is not None
    assert psycopg is not None
    with (
        psycopg.connect(STATUS_DSN) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("SELECT private_hypothesis_hash FROM foundry.trial").fetchall()
