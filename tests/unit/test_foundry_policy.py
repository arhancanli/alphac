from __future__ import annotations

import json

import pytest

from alphaforge.foundry.policy import PolicyError, load_foundry_policy


def test_active_policy_stops_at_the_next_staged_review() -> None:
    policy = load_foundry_policy()
    assert policy.observed_identities == 228
    assert policy.identity_budget == 400
    assert policy.next_hard_review == 320
    assert policy.reservation_capacity == 92
    policy.assert_can_reserve(91)
    with pytest.raises(PolicyError, match="mandatory policy review"):
        policy.assert_can_reserve(92)


def test_policy_fails_closed_when_research_is_not_active(tmp_path) -> None:
    source = json.loads(
        load_foundry_policy.__globals__["DEFAULT_POLICY_PATH"].read_text(encoding="utf-8")
    )
    source["research_status"] = "PAUSED"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(PolicyError, match="reservations are closed"):
        load_foundry_policy(path)
