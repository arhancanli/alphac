import copy

import pandas as pd
import pytest

from alphaforge.validation.trend_cash_corrections import apply_cash_corrections
from alphaforge.validation.trend_observation import ObservationError


def sample():
    actions = pd.DataFrame(
        [
            {
                "event_id": "original",
                "symbol": "AAA",
                "session_ms": 1000,
                "kind": "dividend",
                "raw_value": 0.5,
                "observed_ms": 2000,
                "normalization": "original",
                "source_value": 0.5,
            },
            {
                "event_id": "other",
                "symbol": "BBB",
                "session_ms": 1000,
                "kind": "split",
                "raw_value": 2.0,
                "observed_ms": 2000,
                "normalization": "original",
                "source_value": 2.0,
            },
        ]
    )
    correction = {
        "original_event_id": "original",
        "symbol": "AAA",
        "session_ms": 1000,
        "previous_raw_cash": 0.5,
        "reviewed_raw_cash": "0.25",
        "observed_ms": 3000,
        "evidence_sha256": ["a" * 64, "b" * 64],
    }
    return actions, correction


def test_revision_changes_identity_and_preserves_source():
    actions, correction = sample()
    original = actions.copy(deep=True)
    result = apply_cash_corrections(actions, [correction])
    pd.testing.assert_frame_equal(actions, original)
    assert result.iloc[0].raw_value == 0.25
    assert result.iloc[0].source_value == 0.5
    assert result.iloc[0].observed_ms == 3000
    assert result.iloc[0].original_event_id == "original"
    assert result.iloc[0].event_id != "original"
    pd.testing.assert_series_equal(result.loc[1, actions.columns], actions.loc[1])
    with pytest.raises(ObservationError):
        apply_cash_corrections(result, [correction])


@pytest.mark.parametrize(
    "changes",
    [
        {"previous_raw_cash": 0.6},
        {"reviewed_raw_cash": float("nan")},
        {"observed_ms": 1500},
        {"symbol": "BBB"},
        {"evidence_sha256": ["a" * 64, "a" * 64]},
    ],
)
def test_invalid_revision_does_not_mutate_source(changes):
    actions, correction = sample()
    original = actions.copy(deep=True)
    correction.update(changes)
    with pytest.raises(ObservationError):
        apply_cash_corrections(actions, [correction])
    pd.testing.assert_frame_equal(actions, original)


def test_duplicate_revision_rejected():
    actions, correction = sample()
    with pytest.raises(ObservationError):
        apply_cash_corrections(actions, [correction, copy.deepcopy(correction)])
