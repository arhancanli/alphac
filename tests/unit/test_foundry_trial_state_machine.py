from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config" / "foundry_trial_state_machine.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


def test_foundry_contract_is_explicitly_not_a_deployment_claim() -> None:
    contract = _contract()
    assert contract["schema"] == "canli.foundry-trial-state-machine.v1"
    assert contract["status"] == "DESIGN_FROZEN_NOT_DEPLOYED"
    assert "does not establish that Foundry is deployed" in contract["claim_boundary"]


def test_every_state_denies_broker_write_access() -> None:
    contract = _contract()
    assert contract["invariants"]["broker_write_access_from_foundry"] is False
    assert all(state["broker_write_access"] is False for state in contract["states"].values())


def test_transitions_reference_states_and_terminal_states_have_no_exit() -> None:
    contract = _contract()
    states = contract["states"]
    transitions = contract["transitions"]
    pairs = [(transition["from"], transition["to"]) for transition in transitions]

    assert len(pairs) == len(set(pairs))
    assert all(source in states and target in states for source, target in pairs)
    terminal = {name for name, state in states.items() if state["terminal"]}
    assert terminal == {"ADMITTED", "KILLED", "CANCELLED", "CANCELLED_AFTER_RESERVATION"}
    assert not terminal.intersection(source for source, _ in pairs)


def test_identity_is_spent_once_at_reservation_and_never_unspent() -> None:
    contract = _contract()
    states = contract["states"]
    transitions = contract["transitions"]
    reservation = [
        transition
        for transition in transitions
        if transition["from"] == "PROPOSED" and transition["to"] == "RESERVED"
    ]

    assert reservation == [
        {
            "from": "PROPOSED",
            "to": "RESERVED",
            "authorization": "human",
            "roles": ["owner", "research_approver"],
            "action": "reserve_identity",
        }
    ]
    assert states["FEASIBILITY"]["identity_spent"] is False
    assert states["FEASIBILITY_BLOCKED"]["identity_spent"] is False
    assert states["PROPOSED"]["identity_spent"] is False
    assert states["CANCELLED"]["identity_spent"] is False
    for name, state in states.items():
        if name not in {"FEASIBILITY", "FEASIBILITY_BLOCKED", "PROPOSED", "CANCELLED"}:
            assert state["identity_spent"] is True, name


def test_outcome_access_requires_reserved_identity_and_frozen_snapshot() -> None:
    contract = _contract()
    states = contract["states"]
    assert states["RESERVED"]["return_outcome_access"] is False
    assert states["SNAPSHOT_FROZEN"]["return_outcome_access"] is False
    assert states["RUNNING"]["return_outcome_access"] is True
    assert all(
        state["identity_spent"] is True
        for state in states.values()
        if state["return_outcome_access"] is True
    )


def test_holdout_has_one_human_authorized_entry_and_one_consumption_path() -> None:
    contract = _contract()
    transitions = contract["transitions"]
    authorization = [
        transition for transition in transitions if transition["to"] == "HOLDOUT_AUTHORIZED"
    ]
    consumption = [
        transition for transition in transitions if transition["to"] == "HOLDOUT_CONSUMED"
    ]

    assert contract["invariants"]["holdout_max_consumptions_per_identity"] == 1
    assert authorization == [
        {
            "from": "HOLDOUT_PENDING",
            "to": "HOLDOUT_AUTHORIZED",
            "authorization": "human",
            "roles": ["holdout_approver"],
            "action": "authorize_one_shot_holdout",
        }
    ]
    assert consumption == [
        {
            "from": "HOLDOUT_AUTHORIZED",
            "to": "HOLDOUT_CONSUMED",
            "authorization": "system",
            "action": "consume_holdout_once",
        }
    ]


def test_public_projection_excludes_secrets_and_holdout_values() -> None:
    projection = _contract()["public_projection"]
    assert "artifact_hash" in projection["allowed_fields"]
    assert "replay_status" in projection["allowed_fields"]
    assert "broker_credentials" in projection["forbidden_fields"]
    assert "holdout_values" in projection["forbidden_fields"]
    assert set(projection["allowed_fields"]).isdisjoint(projection["forbidden_fields"])
