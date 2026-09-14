import pytest

from alphaforge.validation.research_horizon import audit_horizon, require_horizon


def test_closed_dates_do_not_need_marks_but_first_return_needs_predecessor():
    assert require_horizon([1, 2, 5, 6], [2, 5, 6], predecessor=1).complete
    result = audit_horizon([2, 5, 6], [2, 5, 6], predecessor=1)
    assert not result.complete and not result.predecessor_available


def test_missing_internal_observation_rejected_not_zero_filled():
    result = audit_horizon([1, 2, 6], [2, 5, 6], predecessor=1)
    assert result.missing_observations == (5,)
    with pytest.raises(ValueError, match="1 missing"):
        require_horizon([1, 2, 6], [2, 5, 6], predecessor=1)


@pytest.mark.parametrize(
    "observed,expected", [([1, 1, 2], [2]), ([2, 1], [2]), ([], [2]), ([1, 2], [])]
)
def test_malformed_observation_sequences_rejected(observed, expected):
    with pytest.raises(ValueError):
        audit_horizon(observed, expected, predecessor=0)


def test_distant_old_mark_cannot_substitute_for_required_predecessor():
    assert not audit_horizon([0, 2, 5], [2, 5], predecessor=1).complete
