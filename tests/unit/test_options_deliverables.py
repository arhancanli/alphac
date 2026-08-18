"""Point-in-time adjusted option deliverable and signed basket tests."""

from __future__ import annotations

import pytest

from alphaforge.core.errors import LookaheadError
from alphaforge.execution.options import (
    AssignmentNotice,
    ExerciseStyle,
    OptionContract,
    OptionRight,
    OptionSettlement,
    SettlementStyle,
)
from alphaforge.execution.options_deliverables import (
    OptionAssetDelta,
    OptionCashAmount,
    OptionCashDelta,
    OptionDeliverableAsset,
    OptionDeliverableTerms,
    StaticOptionDeliverableDataProvider,
    apply_adjusted_assignment,
    apply_physical_deliverable,
    expiry_adjusted_delivery,
)


def _contract(
    *,
    right: OptionRight = OptionRight.CALL,
    exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN,
    settlement_style: SettlementStyle = SettlementStyle.PHYSICAL,
) -> OptionContract:
    return OptionContract(
        instrument_id="OPRA:OPTION:AAPL20260918C00200000",
        underlying_instrument_id="XUSE:CASH:AAPLUSD",
        right=right,
        strike=200.0,
        expiration_ts=1_000,
        last_trade_ts=990,
        listed_ts=10,
        metadata_available_at=100,
        exercise_style=exercise_style,
        settlement_style=settlement_style,
        contract_multiplier=100.0,
    )


def _terms(
    *,
    revision: int = 1,
    effective_ts: int = 10,
    source_observed_ts: int = 5,
    available_at: int = 10,
    assets: tuple[OptionDeliverableAsset, ...] | None = None,
    cash: tuple[OptionCashAmount, ...] | None = None,
    exercise_cash: OptionCashAmount | None = None,
) -> OptionDeliverableTerms:
    return OptionDeliverableTerms(
        instrument_id=_contract().instrument_id,
        revision=revision,
        effective_ts=effective_ts,
        source_observed_ts=source_observed_ts,
        available_at=available_at,
        assets=(
            OptionDeliverableAsset(
                instrument_id="XUSE:CASH:AAPLUSD",
                quantity_per_contract=50.0,
            ),
            OptionDeliverableAsset(
                instrument_id="XUSE:CASH:SPINUSD",
                quantity_per_contract=25.0,
            ),
        )
        if assets is None
        else assets,
        cash=(OptionCashAmount(currency="USD", amount_per_contract=300.0),)
        if cash is None
        else cash,
        exercise_cash=(
            OptionCashAmount(currency="USD", amount_per_contract=20_000.0)
            if exercise_cash is None
            else exercise_cash
        ),
        source_ref=f"occ-memo-r{revision}",
    )


def _settlement(*, price: float = 215.0, available_at: int = 1_010) -> OptionSettlement:
    return OptionSettlement(
        underlying_instrument_id="XUSE:CASH:AAPLUSD",
        settlement_ts=1_000,
        available_at=available_at,
        price=price,
    )


def test_deliverable_terms_reject_invalid_identity_lineage_and_package() -> None:
    with pytest.raises(ValueError, match="OPTION"):
        OptionDeliverableTerms(
            instrument_id="XUSE:CASH:AAPLUSD",
            revision=1,
            effective_ts=10,
            source_observed_ts=5,
            available_at=10,
            assets=(
                OptionDeliverableAsset(
                    instrument_id="XUSE:CASH:AAPLUSD",
                    quantity_per_contract=100.0,
                ),
            ),
            cash=(),
            exercise_cash=OptionCashAmount(currency="USD", amount_per_contract=20_000.0),
            source_ref="occ-memo",
        )
    with pytest.raises(ValueError, match="available_at"):
        _terms(source_observed_ts=11, available_at=10)
    with pytest.raises(ValueError, match="at least one"):
        _terms(assets=(), cash=())
    with pytest.raises(ValueError, match="source_ref"):
        terms = _terms()
        OptionDeliverableTerms(
            instrument_id=terms.instrument_id,
            revision=terms.revision,
            effective_ts=terms.effective_ts,
            source_observed_ts=terms.source_observed_ts,
            available_at=terms.available_at,
            assets=terms.assets,
            cash=terms.cash,
            exercise_cash=terms.exercise_cash,
            source_ref=" ",
        )


def test_deliverable_components_require_canonical_unique_positive_values() -> None:
    with pytest.raises(ValueError, match="currency"):
        OptionCashAmount(currency="usd", amount_per_contract=1.0)
    with pytest.raises(ValueError, match="finite and > 0"):
        OptionDeliverableAsset(
            instrument_id="XUSE:CASH:AAPLUSD",
            quantity_per_contract=0.0,
        )
    leg = OptionDeliverableAsset(
        instrument_id="XUSE:CASH:AAPLUSD",
        quantity_per_contract=50.0,
    )
    with pytest.raises(ValueError, match="asset ids must be unique"):
        _terms(assets=(leg, leg))
    amount = OptionCashAmount(currency="USD", amount_per_contract=10.0)
    with pytest.raises(ValueError, match="cash currencies must be unique"):
        _terms(cash=(amount, amount))


def test_static_provider_requires_contiguous_monotone_revision_chains() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        StaticOptionDeliverableDataProvider(revisions=(_terms(revision=2),))
    with pytest.raises(ValueError, match="effective timestamps"):
        StaticOptionDeliverableDataProvider(
            revisions=(
                _terms(revision=1, effective_ts=20, available_at=20),
                _terms(revision=2, effective_ts=10, available_at=30),
            )
        )
    with pytest.raises(ValueError, match="availability timestamps"):
        StaticOptionDeliverableDataProvider(
            revisions=(
                _terms(revision=1, effective_ts=10, available_at=20),
                _terms(revision=2, effective_ts=20, available_at=19),
            )
        )


def test_static_provider_selects_only_effective_available_revision() -> None:
    revisions = (
        _terms(revision=1, effective_ts=10, available_at=10),
        _terms(revision=2, effective_ts=500, source_observed_ts=90, available_at=100),
        _terms(revision=3, effective_ts=500, source_observed_ts=590, available_at=600),
    )
    provider = StaticOptionDeliverableDataProvider(revisions=revisions)
    iid = _contract().instrument_id
    assert provider.terms(iid, as_of=9) is None
    assert provider.terms(iid, as_of=200) == revisions[0]
    assert provider.terms(iid, as_of=550) == revisions[1]
    assert provider.terms(iid, as_of=650) == revisions[2]
    assert provider.terms("OPRA:OPTION:UNKNOWN", as_of=650) is None


def test_deliverable_require_known_fails_for_future_availability_or_effectiveness() -> None:
    with pytest.raises(LookaheadError, match="available"):
        _terms(available_at=210, source_observed_ts=205).require_known(200)
    with pytest.raises(ValueError, match="not effective"):
        _terms(effective_ts=210, available_at=190, source_observed_ts=180).require_known(200)


@pytest.mark.parametrize(
    ("right", "signed_contracts", "asset_sign", "cash_delta"),
    [
        (OptionRight.CALL, 2.0, 1.0, -39_400.0),
        (OptionRight.CALL, -2.0, -1.0, 39_400.0),
        (OptionRight.PUT, 2.0, -1.0, 39_400.0),
        (OptionRight.PUT, -2.0, 1.0, -39_400.0),
    ],
)
def test_physical_deliverable_preserves_call_put_and_long_short_signs(
    right: OptionRight,
    signed_contracts: float,
    asset_sign: float,
    cash_delta: float,
) -> None:
    delivery = apply_physical_deliverable(
        _contract(right=right),
        signed_contracts=signed_contracts,
        deliverable=_terms(),
        decision_ts=200,
        event_type="manual_exercise",
    )
    assert delivery.option_contracts_delta == -signed_contracts
    assert delivery.asset_deltas == (
        OptionAssetDelta(
            instrument_id="XUSE:CASH:AAPLUSD",
            quantity_delta=asset_sign * 100.0,
        ),
        OptionAssetDelta(
            instrument_id="XUSE:CASH:SPINUSD",
            quantity_delta=asset_sign * 50.0,
        ),
    )
    assert delivery.cash_deltas == (OptionCashDelta(currency="USD", amount_delta=cash_delta),)


def test_physical_deliverable_aggregates_and_sorts_multiple_currencies() -> None:
    terms = _terms(
        cash=(OptionCashAmount(currency="EUR", amount_per_contract=300.0),),
    )
    delivery = apply_physical_deliverable(
        _contract(),
        signed_contracts=2.0,
        deliverable=terms,
        decision_ts=200,
        event_type="manual_exercise",
    )
    assert delivery.cash_deltas == (
        OptionCashDelta(currency="EUR", amount_delta=600.0),
        OptionCashDelta(currency="USD", amount_delta=-40_000.0),
    )


def test_physical_deliverable_fails_closed_for_mismatch_or_cash_settlement() -> None:
    terms = _terms()
    mismatched = OptionDeliverableTerms(
        instrument_id="OPRA:OPTION:MSFT20260918C00200000",
        revision=1,
        effective_ts=10,
        source_observed_ts=5,
        available_at=10,
        assets=terms.assets,
        cash=terms.cash,
        exercise_cash=terms.exercise_cash,
        source_ref="occ-msft",
    )
    with pytest.raises(ValueError, match="do not match"):
        apply_physical_deliverable(
            _contract(),
            signed_contracts=1.0,
            deliverable=mismatched,
            decision_ts=200,
            event_type="manual_exercise",
        )
    with pytest.raises(ValueError, match="physical settlement"):
        apply_physical_deliverable(
            _contract(settlement_style=SettlementStyle.CASH),
            signed_contracts=1.0,
            deliverable=terms,
            decision_ts=200,
            event_type="manual_exercise",
        )


def test_adjusted_expiry_uses_official_known_settlement_and_effective_revision() -> None:
    with pytest.raises(LookaheadError, match="official settlement"):
        expiry_adjusted_delivery(
            _contract(),
            signed_contracts=1.0,
            settlement=_settlement(available_at=1_010),
            deliverable=_terms(),
            decision_ts=1_005,
        )
    delivery = expiry_adjusted_delivery(
        _contract(),
        signed_contracts=1.0,
        settlement=_settlement(),
        deliverable=_terms(revision=1),
        decision_ts=1_010,
    )
    assert delivery.event_type == "expiry_adjusted_exercise_or_assignment"
    assert delivery.deliverable_revision == 1
    assert delivery.option_contracts_delta == -1.0


def test_adjusted_expiry_lapse_closes_option_without_package_delivery() -> None:
    delivery = expiry_adjusted_delivery(
        _contract(),
        signed_contracts=3.0,
        settlement=_settlement(price=200.005),
        deliverable=_terms(),
        decision_ts=1_010,
        auto_exercise_threshold=0.01,
    )
    assert delivery.event_type == "expiry_lapse"
    assert delivery.option_contracts_delta == -3.0
    assert delivery.asset_deltas == ()
    assert delivery.cash_deltas == ()


def test_adjusted_assignment_applies_observed_notice_through_effective_revision() -> None:
    contract = _contract()
    notice = AssignmentNotice(
        instrument_id=contract.instrument_id,
        assigned_contracts=1.0,
        event_ts=500,
        available_at=510,
    )
    delivery = apply_adjusted_assignment(
        contract,
        short_contracts=2.0,
        notice=notice,
        deliverable=_terms(revision=1),
        decision_ts=510,
    )
    assert delivery.event_type == "early_adjusted_assignment"
    assert delivery.option_contracts_delta == 1.0
    assert delivery.asset_deltas[0].quantity_delta == -50.0
    assert delivery.cash_deltas == (OptionCashDelta(currency="USD", amount_delta=19_700.0),)


def test_adjusted_assignment_rejects_future_notice_and_excess_quantity() -> None:
    contract = _contract()
    future = AssignmentNotice(
        instrument_id=contract.instrument_id,
        assigned_contracts=1.0,
        event_ts=500,
        available_at=510,
    )
    with pytest.raises(LookaheadError, match="assignment notice"):
        apply_adjusted_assignment(
            contract,
            short_contracts=2.0,
            notice=future,
            deliverable=_terms(),
            decision_ts=505,
        )
    with pytest.raises(ValueError, match="exceed"):
        apply_adjusted_assignment(
            contract,
            short_contracts=0.5,
            notice=future,
            deliverable=_terms(),
            decision_ts=510,
        )
