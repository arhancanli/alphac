"""Coverage checks for retained equity observations, without imputing returns."""

import itertools
from dataclasses import dataclass


@dataclass(frozen=True)
class HorizonCoverage:
    expected_observations: int
    missing_observations: tuple[int, ...]
    predecessor_available: bool

    @property
    def complete(self) -> bool:
        return self.predecessor_available and not self.missing_observations


def audit_horizon(observed: list[int], expected: list[int], *, predecessor: int) -> HorizonCoverage:
    """Require each scheduled mark and a prior mark to measure the first return.

    Caller must supply the instrument calendar's complete scheduled observations;
    absent weekends are acceptable only when excluded by that calendar. This checks
    observation presence, not the validity of prices, strategy lineage or execution.
    """
    for name, values in [("observed", observed), ("expected", expected)]:
        if not values or any(type(v) is not int for v in values):
            raise ValueError(f"{name} requires nonempty integer timestamps")
        if any(b <= a for a, b in itertools.pairwise(values)):
            raise ValueError(f"{name} timestamps must be strictly increasing")
    if type(predecessor) is not int or predecessor >= expected[0]:
        raise ValueError("Predecessor must be the explicitly scheduled prior mark")
    available = set(observed)
    return HorizonCoverage(
        len(expected), tuple(t for t in expected if t not in available), predecessor in available
    )


def require_horizon(
    observed: list[int], expected: list[int], *, predecessor: int
) -> HorizonCoverage:
    coverage = audit_horizon(observed, expected, predecessor=predecessor)
    if not coverage.complete:
        raise ValueError(
            f"Incomplete horizon: {len(coverage.missing_observations)} missing scheduled marks; "
            f"predecessor_available={coverage.predecessor_available}"
        )
    return coverage
