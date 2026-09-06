from __future__ import annotations

import copy

import pytest

from alphaforge.foundry.contract import (
    ContractError,
    FoundryContract,
    TransitionAuthorizationError,
)


def test_contract_authorizes_only_the_exact_frozen_human_transition() -> None:
    contract = FoundryContract.load()
    transition = contract.authorize(
        source="PROPOSED",
        target="RESERVED",
        action="reserve_identity",
        actor_kind="human",
        actor_role="research_approver",
    )
    assert transition.target == "RESERVED"

    with pytest.raises(TransitionAuthorizationError, match="requires one of these roles"):
        contract.authorize(
            source="PROPOSED",
            target="RESERVED",
            action="reserve_identity",
            actor_kind="human",
            actor_role="worker",
        )


def test_contract_rejects_human_override_of_a_failing_gate() -> None:
    contract = FoundryContract.load()
    with pytest.raises(TransitionAuthorizationError, match="requires system authorization"):
        contract.authorize(
            source="VALIDATING",
            target="KILLED",
            action="apply_failing_gate",
            actor_kind="human",
            actor_role="owner",
        )


def test_contract_rejects_mutation_that_grants_broker_access() -> None:
    original = FoundryContract.load()._document
    mutated = copy.deepcopy(original)
    mutated["states"]["RUNNING"]["broker_write_access"] = True
    with pytest.raises(ContractError, match="broker write access"):
        FoundryContract(mutated)
