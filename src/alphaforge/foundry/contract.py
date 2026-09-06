"""Machine-enforced lifecycle contract for bounded Foundry trials."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

DEFAULT_CONTRACT_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "config" / "foundry_trial_state_machine.json"
)


class ContractError(ValueError):
    """The Foundry lifecycle contract is malformed or contradictory."""


class TransitionAuthorizationError(PermissionError):
    """A requested state change is absent from or unauthorized by the contract."""


def canonical_sha256(value: object) -> str:
    """Return the SHA-256 binding of canonical JSON."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class Transition:
    source: str
    target: str
    action: str
    authorization: str
    roles: frozenset[str]


class FoundryContract:
    """Validated state-machine contract with fail-closed transition lookup."""

    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document
        self._validate()
        self._transitions = {
            (item["from"], item["to"], item["action"]): Transition(
                source=item["from"],
                target=item["to"],
                action=item["action"],
                authorization=item["authorization"],
                roles=frozenset(item.get("roles", [])),
            )
            for item in document["transitions"]
        }

    @classmethod
    def load(cls, path: Path = DEFAULT_CONTRACT_PATH) -> FoundryContract:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ContractError(f"cannot read Foundry contract: {path}") from error
        if not isinstance(document, dict):
            raise ContractError("Foundry contract must be a JSON object")
        return cls(document)

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self._document)

    @property
    def status(self) -> str:
        return str(self._document["status"])

    @property
    def schema(self) -> str:
        return str(self._document["schema"])

    @property
    def version(self) -> str:
        return str(self._document["version"])

    @property
    def claim_boundary(self) -> str:
        return str(self._document["claim_boundary"])

    @property
    def state_names(self) -> frozenset[str]:
        return frozenset(self._document["states"])

    @property
    def public_allowed_fields(self) -> frozenset[str]:
        return frozenset(self._document["public_projection"]["allowed_fields"])

    @property
    def public_forbidden_fields(self) -> frozenset[str]:
        return frozenset(self._document["public_projection"]["forbidden_fields"])

    def database_states(self) -> list[tuple[object, ...]]:
        """Return lifecycle-state rows in deterministic database load order."""
        return [
            (
                name,
                state["public_label"],
                state["identity_spent"],
                state["return_outcome_access"],
                state["holdout_access"],
                state["broker_write_access"],
                state["terminal"],
            )
            for name, state in sorted(self._document["states"].items())
        ]

    def database_transitions(self) -> list[tuple[object, ...]]:
        """Return lifecycle-transition rows in deterministic database load order."""
        return [
            (
                item["from"],
                item["to"],
                item["action"],
                item["authorization"],
                list(item.get("roles", [])),
            )
            for item in sorted(
                self._document["transitions"],
                key=lambda row: (row["from"], row["to"], row["action"]),
            )
        ]

    def state(self, name: str) -> dict[str, Any]:
        try:
            value = self._document["states"][name]
        except KeyError as error:
            raise ContractError(f"unknown Foundry state: {name}") from error
        return dict(value)

    def authorize(
        self,
        *,
        source: str,
        target: str,
        action: str,
        actor_kind: str,
        actor_role: str | None,
    ) -> Transition:
        """Return the exact permitted transition or fail closed."""
        key = (source, target, action)
        transition = self._transitions.get(key)
        if transition is None:
            raise TransitionAuthorizationError(
                f"transition is not in the frozen contract: {source} -> {target} ({action})"
            )
        if transition.authorization != actor_kind:
            raise TransitionAuthorizationError(
                f"{action} requires {transition.authorization} authorization"
            )
        if transition.roles and actor_role not in transition.roles:
            allowed = ", ".join(sorted(transition.roles))
            raise TransitionAuthorizationError(f"{action} requires one of these roles: {allowed}")
        if not transition.roles and actor_role is not None and actor_kind == "system":
            raise TransitionAuthorizationError("system transitions cannot assert a human role")
        return transition

    def public_trial(self, record: dict[str, Any]) -> dict[str, Any]:
        """Project one private trial record into the contract's public field set."""
        state_name = record.get("state")
        if not isinstance(state_name, str):
            raise ContractError("trial state must be a string")
        state = self.state(state_name)
        projected = {
            key: record[key]
            for key in self.public_allowed_fields
            if key in record
        }
        projected.update(
            {
                "state": state_name,
                "public_label": state["public_label"],
                "identity_spent": state["identity_spent"],
                "claim_boundary": self.claim_boundary,
            }
        )
        return projected

    def _validate(self) -> None:
        required = {
            "schema",
            "version",
            "status",
            "claim_boundary",
            "invariants",
            "states",
            "transitions",
            "public_projection",
        }
        if set(self._document) < required:
            missing = ", ".join(sorted(required - set(self._document)))
            raise ContractError(f"Foundry contract is missing fields: {missing}")
        if self._document["schema"] != "canli.foundry-trial-state-machine.v1":
            raise ContractError("unexpected Foundry contract schema")
        states = self._document["states"]
        transitions = self._document["transitions"]
        if not isinstance(states, dict) or not states:
            raise ContractError("Foundry contract has no states")
        if not isinstance(transitions, list) or not transitions:
            raise ContractError("Foundry contract has no transitions")
        seen: set[tuple[str, str, str]] = set()
        for item in transitions:
            if not isinstance(item, dict):
                raise ContractError("Foundry transition must be an object")
            key = (item.get("from"), item.get("to"), item.get("action"))
            if not all(isinstance(value, str) for value in key):
                raise ContractError("Foundry transition fields must be strings")
            typed_key = (str(key[0]), str(key[1]), str(key[2]))
            if typed_key in seen:
                raise ContractError(f"duplicate Foundry transition: {typed_key}")
            seen.add(typed_key)
            if item["from"] not in states or item["to"] not in states:
                raise ContractError(f"transition references unknown state: {typed_key}")
            if states[item["from"]]["terminal"]:
                raise ContractError(f"terminal state has an outbound transition: {item['from']}")
            authorization = item.get("authorization")
            roles = item.get("roles", [])
            if authorization not in {"human", "system"}:
                raise ContractError(f"invalid authorization kind: {authorization}")
            if authorization == "human" and not roles:
                raise ContractError(f"human transition lacks a role: {typed_key}")
            if authorization == "system" and roles:
                raise ContractError(f"system transition asserts a human role: {typed_key}")
        projection = self._document["public_projection"]
        allowed = set(projection.get("allowed_fields", []))
        forbidden = set(projection.get("forbidden_fields", []))
        if not allowed or allowed & forbidden:
            raise ContractError("public field allowlist is empty or overlaps the denylist")
        if any(bool(state.get("broker_write_access")) for state in states.values()):
            raise ContractError("a Foundry state grants broker write access")
