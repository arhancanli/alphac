"""Unit tests for ``af paper status`` ladder rendering (offline, tmp_path only).

The honesty contract (buildabilityCritique C4-render): ``_print_ladder`` renders
the PERSISTED live ladder snapshot (``store.last_ladder_state()``), NOT a fresh
:class:`~alphaforge.risk.DrawdownLadder` replayed over the equity curve. The
replay path had no memory of an operator rearm -- which freezes the HWM and
resets the state to NORMAL -- and so re-tripped FLAT_HALTED on the historical
drawdown, making the status display LIE after a rearm.

These tests pin the post-rearm case (the live ladder is NORMAL but a fresh replay
of the curve would re-trip FLAT_HALTED) and the never-recorded case (a plain
notice, never a misleading estimate). Fully OFFLINE: a tmp_path SQLite store, no
network, no ./data or ./var.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alphaforge.cli.paper_cmds import _print_ladder
from alphaforge.live.store import TradingStore

HOUR = 3_600_000
T0 = 1_672_531_200_000  # 2023-01-01T00:00:00Z, bar-aligned


@pytest.fixture
def store(tmp_path: Path) -> TradingStore:
    """A fresh trading store over a tmp_path SQLite file (closed by GC/tmp teardown)."""
    return TradingStore(tmp_path / "trading.sqlite")


def test_print_ladder_no_snapshot_prints_plain_notice(
    store: TradingStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A store that never recorded a ladder snapshot prints a notice, not an estimate."""
    _print_ladder(store)
    out = capsys.readouterr().out
    assert "no ladder snapshot yet" in out
    # No replay-derived numbers leak when there is genuinely no snapshot.
    assert "gross_mult" not in out


def test_print_ladder_renders_persisted_normal_after_rearm(
    store: TradingStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """After a rearm the persisted snapshot is NORMAL -> status prints NORMAL.

    The scenario: equity fell 20% (a halt-tripping drawdown) and then an operator
    rearmed, which freezes the HWM at the recovered equity and resets the ladder to
    NORMAL with ``gross_mult = 1.0``. A FRESH ladder replayed over the FULL equity
    curve would re-trip FLAT_HALTED on that historical 20% drop; the persisted live
    snapshot does not. Status must render the persisted truth.
    """
    # An equity curve that, replayed through a fresh ladder, WOULD re-trip the
    # absorbing FLAT_HALTED (a 20% drawdown from the peak). Present only to prove
    # the renderer ignores it in favour of the recorded snapshot.
    store.record_ladder_state(
        cycle_ts=T0 + 5 * HOUR,
        state="normal",
        hwm=80_000.0,  # frozen at the post-rearm equity, BELOW the 100k peak
        drawdown=0.0,
        gross_mult=1.0,
    )

    _print_ladder(store)
    out = capsys.readouterr().out
    assert "ladder: normal" in out
    assert "flat_halted" not in out
    assert "gross_mult=1.00" in out
    assert "hwm=80000.00" in out


def test_print_ladder_renders_persisted_flat_halted(
    store: TradingStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A persisted FLAT_HALTED snapshot renders verbatim (gross_mult 0.0)."""
    store.record_ladder_state(
        cycle_ts=T0 + 9 * HOUR,
        state="flat_halted",
        hwm=100_000.0,
        drawdown=0.16,
        gross_mult=0.0,
    )
    _print_ladder(store)
    out = capsys.readouterr().out
    assert "ladder: flat_halted" in out
    assert "gross_mult=0.00" in out
    assert "dd=0.1600" in out


def test_print_ladder_uses_latest_snapshot_only(
    store: TradingStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The renderer shows the freshest snapshot (the upsert keeps the max cycle_ts)."""
    store.record_ladder_state(
        cycle_ts=T0 + 1 * HOUR,
        state="flat_halted",
        hwm=100_000.0,
        drawdown=0.16,
        gross_mult=0.0,
    )
    # A later cycle rearmed back to NORMAL -- the latest state the operator sees.
    store.record_ladder_state(
        cycle_ts=T0 + 2 * HOUR,
        state="normal",
        hwm=84_000.0,
        drawdown=0.0,
        gross_mult=1.0,
    )
    _print_ladder(store)
    out = capsys.readouterr().out
    assert "ladder: normal" in out
    assert "flat_halted" not in out
