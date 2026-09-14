import sqlite3

import pandas as pd
import pytest

from alphaforge.validation.trend_observation import (
    ObservationError,
    TrendObservationJournal,
    session_window,
)


def ms(value):
    return int(pd.Timestamp(value, tz="UTC").timestamp() * 1000)


FRIDAY = ms("2026-09-11")
NOW = ms("2026-09-11 21:00")
EPOCH = {
    "epoch_id": "fixture",
    "mode": "REPLAY_DIAGNOSTIC",
    "candidate_id": "ec7ec19175ac10a9",
    "candidate_fingerprint": "a" * 64,
    "initial_state": {"n": 0},
}


def output(inputs, state):
    return {
        "signals": {"A": 0.01},
        "targets": {"A": 0.1},
        "allocation_state": {"n": state["n"] + 1},
    }


def capture(j, compute=output, **kw):
    return j.observe(
        session_ms=FRIDAY,
        inputs={"source": "synthetic"},
        received_ms=NOW,
        state_before={"n": 0},
        compute=compute,
        **kw,
    )


def test_friday_next_open_and_early_close():
    assert session_window(FRIDAY) == (ms("2026-09-11 20:00"), ms("2026-09-14 13:30"))
    assert session_window(ms("2026-11-27")) == (ms("2026-11-27 18:00"), ms("2026-11-30 14:30"))
    with pytest.raises(ObservationError):
        session_window(ms("2026-09-12"))


def test_commit_restart_state_and_immutable_epoch(tmp_path):
    path = tmp_path / "journal.sqlite"
    j = TrendObservationJournal(path, epoch=EPOCH, clock=lambda: NOW)
    assert capture(j)["status"] == "DECISION"
    head = j.verify()["head_sha256"]
    assert j.state() == {"n": 1}
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        j.conn.execute("DELETE FROM events")
    j.close()
    j = TrendObservationJournal(path, epoch=EPOCH, clock=lambda: NOW)
    assert j.verify()["head_sha256"] == head
    with pytest.raises(ObservationError, match="already captured"):
        capture(j, lambda *_: pytest.fail("must not recompute"))
    j.close()
    with pytest.raises(ObservationError, match="mismatch"):
        TrendObservationJournal(path, epoch={**EPOCH, "candidate_fingerprint": "b" * 64})


def test_late_capture_never_computes(tmp_path):
    j = TrendObservationJournal(
        tmp_path / "late.sqlite", epoch=EPOCH, clock=lambda: ms("2026-09-14 13:30")
    )
    assert capture(j, lambda *_: pytest.fail("late"))["status"] == "MISSED"
    assert j.state() == {"n": 0}
    j.close()


def test_computation_crossing_deadline_discards_output(tmp_path):
    times = iter([NOW, ms("2026-09-14 13:30")])
    j = TrendObservationJournal(tmp_path / "late.sqlite", epoch=EPOCH, clock=lambda: next(times))
    assert capture(j)["status"] == "MISSED"
    assert j.state() == {"n": 0}
    j.close()


def test_crash_capture_cannot_retry_and_can_only_be_marked_missed(tmp_path):
    j = TrendObservationJournal(tmp_path / "crash.sqlite", epoch=EPOCH, clock=lambda: NOW)

    def crash(*_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        capture(j, crash)
    assert j.verify()["pending_sessions"] == [FRIDAY]
    with pytest.raises(ObservationError, match="already captured"):
        capture(j)
    j.abandon_pending(FRIDAY, reason="interrupted computation")
    assert not j.verify()["pending_sessions"]
    assert j.state() == {"n": 0}
    j.close()


def test_second_writer_cannot_resolve_abandoned_capture(tmp_path):
    path = tmp_path / "race.sqlite"
    j = TrendObservationJournal(path, epoch=EPOCH, clock=lambda: NOW)
    other = TrendObservationJournal(path, epoch=EPOCH, clock=lambda: NOW)

    def compete(inputs, state):
        with pytest.raises(ObservationError, match="already captured"):
            capture(other)
        other.abandon_pending(FRIDAY, reason="operator classified interrupted attempt")
        return output(inputs, state)

    with pytest.raises(ObservationError, match="already resolved"):
        capture(j, compete)
    assert j.verify()["events"] == 2
    j.close()
    other.close()


def test_invalid_output_and_clock_gate(tmp_path):
    j = TrendObservationJournal(tmp_path / "bad.sqlite", epoch=EPOCH, clock=lambda: NOW)
    assert (
        capture(
            j, lambda *_: {"signals": {"A": float("nan")}, "targets": {}, "allocation_state": {}}
        )["status"]
        == "FAILED"
    )
    j.close()
    j = TrendObservationJournal(
        tmp_path / "live.sqlite", epoch={**EPOCH, "mode": "SHADOW_PROSPECTIVE"}, clock=lambda: NOW
    )
    with pytest.raises(ObservationError, match="clock evidence"):
        capture(j)
    with pytest.raises(ObservationError, match="outside bounds"):
        capture(
            j,
            clock_evidence={
                "observed_ms": NOW,
                "offset_ms": 1000,
                "uncertainty_ms": 5,
                "source_hash": "b" * 64,
            },
        )
    assert (
        capture(
            j,
            clock_evidence={
                "observed_ms": NOW,
                "offset_ms": 1,
                "uncertainty_ms": 5,
                "source_hash": "b" * 64,
            },
        )["status"]
        == "DECISION"
    )
    assert j.verify()["execution_authorized"] is False
    j.close()


def test_state_discontinuity_and_future_receipt_fail_before_capture(tmp_path):
    j = TrendObservationJournal(tmp_path / "bad.sqlite", epoch=EPOCH, clock=lambda: NOW)
    for receipt, state in [(NOW + 1, {"n": 0}), (NOW, {"n": 99})]:
        with pytest.raises(ObservationError):
            j.observe(
                session_ms=FRIDAY,
                inputs={"x": 1},
                received_ms=receipt,
                state_before=state,
                compute=output,
            )
    assert j.verify()["events"] == 0
    j.close()


def test_missing_data_event_and_content_tamper_detection(tmp_path):
    j = TrendObservationJournal(tmp_path / "missing.sqlite", epoch=EPOCH, clock=lambda: NOW)
    j.miss(FRIDAY, reason="No authenticated completed bar receipt")
    assert j.state() == {"n": 0}
    assert j.verify()["events"] == 2
    with pytest.raises(ObservationError):
        capture(j)
    j.conn.execute("DROP TRIGGER no_event_update")
    j.conn.execute("UPDATE events SET payload='{}' WHERE seq=2")
    with pytest.raises(ObservationError, match="chain mismatch"):
        j.verify()
    j.close()
