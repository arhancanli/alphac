from datetime import UTC, datetime, timedelta

import pytest

from alphaforge.validation.wasde_signal import research_basket

NOW = datetime(2024, 8, 12, 16, 5, tzinfo=UTC)


def rows():
    return [
        {
            "crop": crop,
            "date_label": "2024-08-12",
            "report_id": "651",
            "status": "REVISION_OBSERVED",
            "available_at": NOW - timedelta(minutes=5),
            "prior_available_at": NOW - timedelta(days=30),
            "stocks_to_use_change": change,
        }
        for crop, change in [("corn", -0.01), ("wheat", 0.01), ("soybeans", 0.0)]
    ]


def test_tightening_long_loosening_short_unchanged_flat():
    result = research_basket(rows(), NOW)
    assert result["weights"] == {"corn": 1 / 3, "wheat": -1 / 3, "soybeans": 0.0}
    assert result["execution_eligible"] is False


@pytest.mark.parametrize(
    "key,value",
    [
        ("available_at", None),
        ("prior_available_at", None),
        ("available_at", NOW),
        ("available_at", NOW - timedelta(days=1)),
        ("status", "CORRECTION_VERSION"),
        ("status", "NO_PRIOR_SAME_CROP_YEAR"),
        ("stocks_to_use_change", float("nan")),
        ("stocks_to_use_change", True),
        ("report_id", "wrong"),
    ],
)
def test_one_invalid_crop_blocks_entire_basket(key, value):
    data = rows()
    data[0][key] = value
    assert research_basket(data, NOW)["status"] == "BLOCKED"


def test_missing_crop_is_not_redistributed():
    assert research_basket(rows()[:2], NOW)["weights"] == {}


def test_naive_decision_rejected():
    with pytest.raises(ValueError, match="timezone"):
        research_basket(rows(), NOW.replace(tzinfo=None))
