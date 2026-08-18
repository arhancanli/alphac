"""Regression: the equity walk-forward universe is scoped to XUSE:* (2026-07-18).

Defect 2 of the marking-fix campaign: the equity profile shares the default lake
with crypto, whose ``universe_membership`` carries BOTH ``XUSE:CASH:*`` equities
and ``BINANCE:PERP:*`` perps — so the equity walk-forward traded crypto perps
inside the equity book (dormant since Jun 11; re-fires if crypto D1 bars resume).

These tests pin the RUNNING path: :meth:`WalkForwardRunner.run` itself (not a
helper), by asserting the scope guard executes inside ``run()`` BEFORE any leg
machinery — via its loud warning and its empty-after-scope refusal. A sentinel
signal service proves execution reached (and stopped at) the first post-guard
step, so the guard cannot silently drop out of the running code path.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from alphaforge.analytics.walkforward import WalkForwardRunner
from alphaforge.config.settings import load_settings
from alphaforge.core.instruments import InstrumentStore
from alphaforge.core.time import Ms
from alphaforge.costs import TransactionCostModel
from alphaforge.data.store.lake import LakePaths
from alphaforge.data.store.reader import PITDataReader
from alphaforge.data.universe.store import UniverseStore

DAY = 86_400_000
START = 1_672_531_200_000  # 2023-01-01T00:00:00Z (D1-aligned)
END = START + 900 * DAY

XUSE_ID = "XUSE:CASH:AAPLUSD"
CRYPTO_ID = "BINANCE:PERP:BTCUSDT"


class _Sentinel(Exception):
    """Raised by the stub signal service: proves run() got PAST the scope guard."""


class _SentinelSignals:
    def __init__(self) -> None:
        self.called = False

    def compute_research(self, start: Ms, end: Ms) -> object:
        self.called = True
        raise _Sentinel


def _runner(tmp_path: Path, signals: _SentinelSignals) -> tuple[WalkForwardRunner, InstrumentStore]:
    settings = load_settings("equity")  # the LIVE equity profile (asset_class=equity)
    store = InstrumentStore(tmp_path / "ops.sqlite")
    paths = LakePaths(tmp_path / "lake")
    runner = WalkForwardRunner(
        PITDataReader(paths),
        store,
        UniverseStore(paths),
        TransactionCostModel.from_settings(settings),
        signals,
        settings,
    )
    return runner, store


def test_equity_run_drops_binance_perp_ids_loudly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """run() with a mixed id list warns about + drops the BINANCE:PERP id BEFORE
    any leg machinery executes (the sentinel fires only after the guard)."""
    signals = _SentinelSignals()
    runner, store = _runner(tmp_path, signals)
    with (
        caplog.at_level(logging.WARNING, logger="alphaforge.analytics.walkforward"),
        pytest.raises(_Sentinel),
    ):
        runner.run(
            START,
            END,
            train_bars=365,
            test_bars=91,
            embargo_bars=274,
            instrument_ids=[XUSE_ID, CRYPTO_ID],
        )
    store.close()
    assert signals.called  # the guard let the XUSE book proceed into the run
    scope_warnings = [
        r.getMessage()
        for r in caplog.records
        if "EQUITY WALK-FORWARD UNIVERSE SCOPE" in r.getMessage()
    ]
    assert scope_warnings, "expected the loud scope-guard warning"
    assert CRYPTO_ID in scope_warnings[0]
    assert XUSE_ID not in scope_warnings[0]  # only the DROPPED ids are listed


def test_equity_run_refuses_all_crypto_universe(tmp_path: Path) -> None:
    """A universe that is entirely non-XUSE must refuse to run, not trade crypto."""
    signals = _SentinelSignals()
    runner, store = _runner(tmp_path, signals)
    with pytest.raises(ValueError, match="empty after XUSE"):
        runner.run(
            START,
            END,
            train_bars=365,
            test_bars=91,
            embargo_bars=274,
            instrument_ids=[CRYPTO_ID, "BINANCE:PERP:ETHUSDT"],
        )
    store.close()
    assert not signals.called  # refused before any machinery ran
