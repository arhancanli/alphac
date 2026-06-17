"""Unit tests for alphaforge.config.sleeve — the per-asset-class sleeve registry.

The registry is the spine's single source of (anchor TF, calendar). The load-bearing
contract is the byte-identity default: the crypto sleeves MUST resolve H1 + the 24/7
calendar whose grid/annualization delegate to the bare ``core.time`` kernel, so routing
the spine through the registry is an identity refactor on the crypto path. The equity
sleeve resolves D1 + the XNYS session calendar (252-day basis).
"""

from __future__ import annotations

import pytest

from alphaforge.config.sleeve import (
    CRYPTO_PERP_SLEEVE,
    CRYPTO_SPOT_SLEEVE,
    EQUITY_SLEEVE,
    Sleeve,
    sleeve_for,
)
from alphaforge.core.calendar import Always24x7Calendar, XNYSCalendar, calendar_for
from alphaforge.core.errors import ConfigError
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass


class TestRegistry:
    def test_crypto_perp_resolves_h1_and_24x7(self) -> None:
        sleeve = sleeve_for(AssetClass.CRYPTO_PERP)
        assert sleeve is CRYPTO_PERP_SLEEVE
        assert sleeve.anchor_tf is Timeframe.H1
        assert isinstance(sleeve.calendar, Always24x7Calendar)

    def test_crypto_spot_resolves_h1_and_24x7(self) -> None:
        sleeve = sleeve_for(AssetClass.CRYPTO_SPOT)
        assert sleeve is CRYPTO_SPOT_SLEEVE
        assert sleeve.anchor_tf is Timeframe.H1
        assert isinstance(sleeve.calendar, Always24x7Calendar)

    def test_equity_resolves_d1_and_xnys(self) -> None:
        sleeve = sleeve_for(AssetClass.EQUITY)
        assert sleeve is EQUITY_SLEEVE
        assert sleeve.anchor_tf is Timeframe.D1
        assert isinstance(sleeve.calendar, XNYSCalendar)

    def test_every_registered_sleeve_keys_on_its_asset_class(self) -> None:
        for sleeve in (CRYPTO_PERP_SLEEVE, CRYPTO_SPOT_SLEEVE, EQUITY_SLEEVE):
            assert sleeve_for(sleeve.asset_class) is sleeve

    def test_calendar_is_the_shared_singleton(self) -> None:
        # The sleeve does not own a calendar — it delegates to calendar_for so there is
        # one source of truth (and the singleton identity is preserved).
        for ac in AssetClass:
            assert sleeve_for(ac).calendar is calendar_for(ac)


class TestPeriodsPerYear:
    def test_crypto_is_8760(self) -> None:
        # Byte-identity: the crypto annualizer must be exactly H1.bars_per_year.
        assert CRYPTO_PERP_SLEEVE.periods_per_year() == 8760.0
        assert CRYPTO_PERP_SLEEVE.periods_per_year() == Timeframe.H1.bars_per_year
        assert CRYPTO_SPOT_SLEEVE.periods_per_year() == 8760.0

    def test_equity_is_252(self) -> None:
        assert EQUITY_SLEEVE.periods_per_year() == 252.0

    def test_matches_calendar_periods_per_year(self) -> None:
        for sleeve in (CRYPTO_PERP_SLEEVE, CRYPTO_SPOT_SLEEVE, EQUITY_SLEEVE):
            assert sleeve.periods_per_year() == sleeve.calendar.periods_per_year(sleeve.anchor_tf)


class TestSleeveDataclass:
    def test_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            CRYPTO_PERP_SLEEVE.anchor_tf = Timeframe.D1  # type: ignore[misc]

    def test_is_slotted(self) -> None:
        sleeve = Sleeve(asset_class=AssetClass.EQUITY, anchor_tf=Timeframe.D1)
        assert not hasattr(sleeve, "__dict__")


class TestUnregistered:
    def test_every_asset_class_is_registered(self) -> None:
        # The contract for the live path: no real AssetClass member ever raises.
        for ac in AssetClass:
            assert isinstance(sleeve_for(ac), Sleeve)

    def test_raises_config_error_not_keyerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A future, unregistered member must surface a domain ConfigError (named), not a
        # bare KeyError. Simulate by removing one entry from the registry.
        from alphaforge.config import sleeve as sleeve_mod

        patched = dict(sleeve_mod._REGISTRY)
        del patched[AssetClass.EQUITY]
        monkeypatch.setattr(sleeve_mod, "_REGISTRY", patched)
        with pytest.raises(ConfigError, match="no sleeve registered for 'equity'"):
            sleeve_for(AssetClass.EQUITY)
