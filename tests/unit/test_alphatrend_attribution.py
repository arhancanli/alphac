import pandas as pd
import pytest
from scripts.attribute_alphatrend_baseline import attribute_leg
from scripts.observe_alphabet_borrow import classify


def fixture():
    fills = pd.DataFrame(
        {"instrument_id": ["A"], "realized_pnl_quote": [3.0], "fee": [1.0], "notional": [100.0]}
    )
    positions = pd.DataFrame(
        {
            "ts": [1, 2],
            "instrument_id": ["A", "A"],
            "unreal_pnl": [100.0, 5.0],
            "weight": [0.2, 0.3],
        }
    )
    equity = pd.DataFrame({"ts": [1, 2], "equity": [100.0, 105.0]})
    config = {
        "initial_cash": 100.0,
        "borrow_total": -2.0,
        "financing_cashflow_total": 0.0,
        "corporate_action_cashflow_total": 0.0,
    }
    return fills, positions, equity, config


def test_terminal_unrealized_only_and_borrow_reconciles():
    result = attribute_leg(*fixture())
    assert result["instruments"][0]["pnl_after_commission_before_borrow"] == 7
    assert result["reconciliation_residual"] == 0


def test_unexplained_cashflow_is_rejected():
    f, p, e, c = fixture()
    e.loc[1, "equity"] = 110
    with pytest.raises(ValueError, match="Unreconciled"):
        attribute_leg(f, p, e, c)


def test_duplicate_snapshot_rejected():
    f, p, e, c = fixture()
    with pytest.raises(ValueError, match="Duplicate"):
        attribute_leg(f, pd.concat([p, p]), e, c)


def test_new_borrow_status_overrides_legacy_boolean():
    assert (
        classify(
            {
                "borrow_status": "hard_to_borrow",
                "easy_to_borrow": True,
                "tradable": True,
                "shortable": True,
            }
        )
        == "HTB_APPROVED_LOCATE_REQUIRED"
    )


def test_missing_new_borrow_status_remains_unknown():
    assert classify({"easy_to_borrow": True, "shortable": True, "tradable": True}).startswith(
        "UNKNOWN"
    )


def test_etb_is_only_current_paper_evidence():
    assert (
        classify({"borrow_status": "easy_to_borrow", "shortable": True, "tradable": True})
        == "CURRENT_PAPER_ETB_OBSERVATION_ONLY"
    )
