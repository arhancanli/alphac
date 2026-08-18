from __future__ import annotations

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.execution.corporate_actions import CorporateAction, CorporateActionType


def test_split_contract_requires_null_cash() -> None:
    with pytest.raises(ValueError, match="split cash_amount"):
        CorporateAction(
            instrument_id="XUSE:CASH:ABCUSD",
            action_type=CorporateActionType.SPLIT,
            ex_date=20,
            available_at=10,
            ratio=2.0,
            cash_amount=1.0,
        )


def test_cash_dividend_contract_requires_positive_cash_and_unit_ratio() -> None:
    with pytest.raises(ValueError, match="ratio must equal 1"):
        CorporateAction(
            instrument_id="XUSE:CASH:ABCUSD",
            action_type=CorporateActionType.CASH_DIVIDEND,
            ex_date=20,
            available_at=10,
            ratio=2.0,
            cash_amount=1.0,
        )


def test_late_action_cannot_be_replayed_at_ex_boundary() -> None:
    action = CorporateAction(
        instrument_id="XUSE:CASH:ABCUSD",
        action_type=CorporateActionType.SPLIT,
        ex_date=20,
        available_at=21,
        ratio=2.0,
        cash_amount=None,
    )
    with pytest.raises(LookaheadError, match="future data"):
        action.require_known_before_boundary()
