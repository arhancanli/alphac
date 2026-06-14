"""Operational hardening for the unattended soak (buildabilityCritique.md section 4, Phase 8).

This package holds the machinery that makes a 24/7 PAPER loop safe to run
UNATTENDED: nightly off-box backups with a genuine restore drill, a per-cycle
exchange-clock-sanity check, and the modeled-vs-realized slippage report that is
the one non-circular validation signal of paper mode (leakageCritique.md finding
8). None of these touch the trading hot path's state; they read the durable
``var/trading.sqlite`` (and ``var/ops.sqlite`` when present) and emit reports.

Public surface
--------------
- :class:`~alphaforge.ops.backup.BackupManager` -- consistent online backups of
  the SQLite stores plus a restore drill that REBUILDS and verifies the ledger on
  a clean directory (the Phase-8 gate's "ledger rebuilt from backups").
- :class:`~alphaforge.ops.clock.ClockSanity` -- per-cycle local-vs-exchange skew
  check (the defense, with the staleness breaker, against a drifting clock
  corrupting bar-close decision timing and vol-targeting into a data outage).
- :class:`~alphaforge.ops.slippage.SlippageReport` -- reads the fills audit
  columns (walked vs modeled price) and renders the genuine slippage report.
"""

from __future__ import annotations

from alphaforge.ops.backup import BackupManager, BackupReport, RestoreDrillReport
from alphaforge.ops.clock import (
    CCXTExchangeTimeSource,
    ClockCheck,
    ClockSanity,
    ExchangeTimeSource,
    FakeExchangeTimeSource,
)
from alphaforge.ops.slippage import SlippageReport, SlippageSummary

__all__ = [
    "BackupManager",
    "BackupReport",
    "CCXTExchangeTimeSource",
    "ClockCheck",
    "ClockSanity",
    "ExchangeTimeSource",
    "FakeExchangeTimeSource",
    "RestoreDrillReport",
    "SlippageReport",
    "SlippageSummary",
]
