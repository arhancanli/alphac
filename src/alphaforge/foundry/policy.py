"""Bind Foundry reservations to the active ALPHAC trial-accounting policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from alphaforge.foundry.contract import canonical_sha256

DEFAULT_POLICY_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "config" / "trial_accounting.json"
)


class PolicyError(ValueError):
    """The active identity policy cannot safely authorize a reservation."""


@dataclass(frozen=True, slots=True)
class FoundryPolicy:
    content_hash: str
    research_status: str
    observed_identities: int
    identity_budget: int
    next_hard_review: int
    staged_hard_reviews: tuple[int, ...]

    @property
    def reservation_capacity(self) -> int:
        """Identities available before the next mandatory review, not the final ceiling."""
        return max(0, self.next_hard_review - self.observed_identities)

    def assert_can_reserve(self, already_reserved: int) -> None:
        if already_reserved < 0:
            raise PolicyError("reserved identity count cannot be negative")
        next_ordinal = self.observed_identities + already_reserved + 1
        if next_ordinal > self.identity_budget:
            raise PolicyError("identity budget exhausted")
        if next_ordinal > self.next_hard_review:
            raise PolicyError(
                f"mandatory policy review reached at identity {self.next_hard_review}"
            )


def _integer(document: dict[str, Any], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PolicyError(f"trial-accounting field must be a non-negative integer: {key}")
    return value


def load_foundry_policy(path: Path = DEFAULT_POLICY_PATH) -> FoundryPolicy:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"cannot read trial-accounting policy: {path}") from error
    if not isinstance(document, dict):
        raise PolicyError("trial-accounting policy must be a JSON object")
    if document.get("schema") != "alphac.trial-accounting-policy.v2":
        raise PolicyError("unexpected trial-accounting policy schema")
    research_status = document.get("research_status")
    if research_status != "ACTIVE_STAGED_PROSPECTIVE_BUDGET":
        raise PolicyError(f"Foundry reservations are closed under status: {research_status}")
    observed = _integer(document, "observed_hypothesis_identities")
    budget = _integer(document, "hypothesis_identity_budget")
    review = document.get("prospective_v7_review")
    if not isinstance(review, dict) or review.get("status") != "IN_FORCE":
        raise PolicyError("prospective v7 review is not in force")
    raw_reviews = review.get("staged_hard_reviews")
    if (
        not isinstance(raw_reviews, list)
        or not raw_reviews
        or any(not isinstance(value, int) or isinstance(value, bool) for value in raw_reviews)
    ):
        raise PolicyError("staged hard reviews are missing or malformed")
    reviews = tuple(sorted(set(raw_reviews)))
    if reviews != tuple(raw_reviews) or reviews[-1] != budget:
        raise PolicyError("staged hard reviews must be unique, ordered, and end at the budget")
    next_review = next((value for value in reviews if value >= observed), budget)
    if observed > budget:
        raise PolicyError("observed identities exceed the active budget")
    return FoundryPolicy(
        content_hash=canonical_sha256(document),
        research_status=research_status,
        observed_identities=observed,
        identity_budget=budget,
        next_hard_review=next_review,
        staged_hard_reviews=reviews,
    )
