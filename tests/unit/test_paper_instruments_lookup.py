"""``_InstrumentsAdapter.lookup``: the record for a held instrument that left the universe.

FOUND 2026-10-17: the crypto loop's ledger seed crashed on a held 1000PEPEUSDT short after
the 2026-10-01 universe refresh dropped it. The loop now resolves held ex-members through
this lookup; it must return same-class records only and ``None`` for anything else.
"""

from __future__ import annotations

from tests.unit.test_live_loop import BTC, T0, make_instrument
from tests.unit.test_signal_service import _equity_instrument

from alphaforge.cli.paper_cmds import _InstrumentsAdapter
from alphaforge.core.types import AssetClass

PEPE = "BINANCE:PERP:1000PEPEUSDT"
EQUITY = "XUSE:CASH:AALUSD"


class _Universe:
    def membership_asof(self, ts: int) -> set[str]:
        del ts
        return {BTC}


class _Records:
    def __init__(self) -> None:
        self._rows = {
            BTC: make_instrument(BTC),
            PEPE: make_instrument(PEPE),
            EQUITY: _equity_instrument(EQUITY),
        }

    def get(self, iid: str, ts: int):
        del ts
        return self._rows.get(iid)


def _adapter() -> _InstrumentsAdapter:
    return _InstrumentsAdapter(_Universe(), _Records(), AssetClass.CRYPTO_PERP)  # type: ignore[arg-type]


def test_lookup_resolves_a_held_ex_member_without_adding_it_to_the_universe() -> None:
    adapter = _adapter()
    assert set(adapter(T0)) == {BTC}
    inst = adapter.lookup(PEPE, T0)
    assert inst is not None and inst.instrument_id == PEPE


def test_lookup_refuses_other_asset_classes_and_unknown_ids() -> None:
    adapter = _adapter()
    assert adapter.lookup(EQUITY, T0) is None
    assert adapter.lookup("BINANCE:PERP:NOPEUSDT", T0) is None
