"""Regression: the corporate-actions ingest must NOT re-poll a per-ticker reference endpoint
every run for a universe that is already current.

The equity tick stalled (2026-07-20) because ``_ingest_corporate_actions`` fetches splits/
dividends per ticker and ``until`` advances daily, so ``until > watermark+1`` stays true for
~every one of ~2500 names — re-hitting a free-tier reference API each run until it rate-limit-
walls and the live_cycle never trades. The fix: a recheck cooldown keyed on the checkpoint's
``updated_at_ms``, plus refreshing that stamp on the empty-result branch (the common case).

This pins the RUNNING path (the phantom-marks lesson: a fix is not done until a test pins the
path that runs). We drive the real ``_ingest_corporate_actions`` against a counting fake source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pytest

from alphaforge.cli import data_cmds
from alphaforge.core.time import to_ms
from alphaforge.data.ingest.checkpoints import CheckpointStore
from alphaforge.data.schemas import Dataset
from alphaforge.data.store.lake import LakePaths

_IDS = [f"XUSE:CASH:T{i:03d}USD" for i in range(20)]
_EMPTY = pa.table({"ex_date": pa.array([], type=pa.timestamp("ms", tz="UTC"))})


class _CountingSource:
    """A reference source that records every ticker it was asked to fetch."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_corporate_actions(self, instrument_id: str, *, since, until):  # noqa: ANN001
        self.calls.append(instrument_id)
        return _EMPTY  # no new actions — the common per-run case


@pytest.fixture
def wired(tmp_path: Path, monkeypatch):
    # ``_ingest_corporate_actions`` loops over ``LakePaths(...).instrument_ids(OHLCV_1D)``.
    # LakePaths is imported inside the function, so patch the class method itself (a real
    # LakePaths is still constructed from settings.paths.lake_dir).
    monkeypatch.setattr(LakePaths, "instrument_ids", lambda self, ds: list(_IDS))
    # LakeWriter is only reached on the non-empty branch (never here — the source returns empty).
    src = _CountingSource()
    monkeypatch.setattr(data_cmds, "_build_equities_reference", lambda: src)

    class _S:  # minimal settings stub — only .paths.lake_dir is read
        class paths:  # noqa: N801
            lake_dir = tmp_path / "lake"

    return _S, src, tmp_path


def test_cooldown_skips_recheck_within_window(wired, tmp_path: Path) -> None:
    settings, src, _ = wired
    db = tmp_path / "ops.sqlite"
    now1 = to_ms(datetime(2026, 7, 20, 5, 0, tzinfo=UTC))
    until = now1
    with CheckpointStore(db) as ck:
        # Run 1: fresh universe -> every ticker is fetched (first-seen keys never skipped).
        data_cmds._ingest_corporate_actions(settings, ck, until=until, now=now1)
        assert len(src.calls) == len(_IDS), "first run must backfill the whole universe"

        # Run 2, one hour later: all keys are within the cooldown -> ZERO refetches.
        src.calls.clear()
        now2 = now1 + 3_600_000
        data_cmds._ingest_corporate_actions(settings, ck, until=now2, now=now2)
        assert src.calls == [], "a current universe must not be re-polled within the cooldown"


def test_cooldown_expires_after_window(wired, tmp_path: Path) -> None:
    settings, src, _ = wired
    db = tmp_path / "ops.sqlite"
    # RELATIVE to the real clock, deliberately: CheckpointStore.set() stamps updated_at_ms from
    # the real wall clock (it takes no injected clock), while the cooldown compares that stamp
    # against the ``now`` we pass in. Anchoring this test on a FIXED calendar date made it a time
    # bomb — once real time passed that date the injected ``now`` could no longer be "later" than
    # the stamp, and the test failed for a reason that had nothing to do with the code under test.
    real_now = int(datetime.now(tz=UTC).timestamp() * 1000)
    with CheckpointStore(db) as ck:
        data_cmds._ingest_corporate_actions(settings, ck, until=real_now, now=real_now)
        src.calls.clear()
        # 6 days past the REAL stamp > the 5-day cooldown -> every ticker is re-checked again.
        later = real_now + 6 * 24 * 3_600_000
        data_cmds._ingest_corporate_actions(settings, ck, until=later, now=later)
        assert len(src.calls) == len(_IDS), "cooldown must expire so real new actions are caught"
