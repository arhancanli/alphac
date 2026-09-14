import json
from pathlib import Path

import pandas as pd
import pytest

from alphaforge.validation.causal_trend_journal import CausalTrendJournal
from alphaforge.validation.trend_observation import ObservationError, fingerprint, session_window
from alphaforge.validation.trend_producer import CausalTrendProducer


def setup(tmp_path, mode="REPLAY_DIAGNOSTIC"):
    config = json.loads(
        (Path(__file__).parents[1] / "fixtures/causal_trend_config.json").read_text()
    )
    binding = {"trial_config": config, "adapter": "test"}
    epoch = {
        "epoch_id": "test",
        "mode": mode,
        "candidate_id": "59901461092dd7a6",
        "candidate_fingerprint": fingerprint(binding),
        "initial_state": {"completed": 0, "last_session": None},
    }
    session = int(pd.Timestamp("2026-08-20", tz="UTC").timestamp() * 1000)
    clock = [session_window(session)[0] + 1000]
    journal = CausalTrendJournal(
        tmp_path / "journal.sqlite", epoch=epoch, binding=binding, clock=lambda: clock[0]
    )
    return journal, binding, epoch, session, clock


class Allocator:
    def __init__(self):
        self.n = 0

    def __call__(self, signals, context):
        self.n += 1
        if context.get("fail"):
            raise ValueError("failed after allocator mutation")
        return {"A": signals["A"] * self.n}


def producer(journal, compute=None):
    def verify(inputs):
        if inputs.get("source") != "sealed":
            raise ObservationError("unbound inputs")

    def signals(inputs):
        assert journal.verify()["pending_sessions"] == [inputs["session_ms"]]
        return dict.fromkeys(["A", "B", "C", "D", "E"], 0.1)

    return CausalTrendProducer(
        journal,
        verify_inputs=verify,
        compute_signals=compute or signals,
        allocator_factory=Allocator,
    )


def observe(p, t, clock, context=None):
    return p.produce(
        session_ms=t,
        received_ms=clock[0],
        inputs={"source": "sealed", "session_ms": t, "context": context or {}},
    )


def test_capture_before_compute_and_fresh_instance_recovery(tmp_path):
    j, binding, epoch, t, clock = setup(tmp_path)
    p = producer(j)
    assert observe(p, t, clock)["status"] == "DECISION"
    j.close()
    j = CausalTrendJournal(
        tmp_path / "journal.sqlite", epoch=epoch, binding=binding, clock=lambda: clock[0]
    )
    p = producer(j)
    assert p.recover() == 1 and p.allocator.n == 1
    next_t = t + 86400000
    clock[0] = session_window(next_t)[0] + 1000
    assert observe(p, next_t, clock)["status"] == "DECISION"
    assert j.state() == {"completed": 2, "last_session": next_t}
    assert p.allocator.n == 2
    j.close()


def test_failure_restores_allocator_and_cannot_retry(tmp_path):
    j, _, _, t, clock = setup(tmp_path)
    p = producer(j)
    assert observe(p, t, clock, {"fail": True})["status"] == "FAILED"
    assert p.allocator.n == 0 and j.state()["completed"] == 0
    with pytest.raises(ObservationError):
        observe(p, t, clock)
    j.close()


def test_clock_gate_blocks_before_callback(tmp_path):
    j, _, _, t, clock = setup(tmp_path, "SHADOW_PROSPECTIVE")
    p = producer(j, compute=lambda inputs: pytest.fail("must not compute"))
    with pytest.raises(ObservationError, match="clock evidence"):
        observe(p, t, clock)
    assert j.verify()["events"] == 0
    j.close()


def test_candidate_and_binding_cannot_be_substituted(tmp_path):
    j, binding, epoch, _t, _clock = setup(tmp_path)
    j.close()
    with pytest.raises(ObservationError, match="binding"):
        CausalTrendJournal(
            tmp_path / "other.sqlite", epoch=epoch, binding={**binding, "adapter": "other"}
        )
    with pytest.raises(ObservationError, match="candidate"):
        CausalTrendJournal(
            tmp_path / "other.sqlite",
            epoch={**epoch, "candidate_id": "ec7ec19175ac10a9"},
            binding=binding,
        )


def test_missing_session_requires_new_epoch(tmp_path):
    j, _, _, t, clock = setup(tmp_path)
    p = producer(j)
    observe(p, t, clock)
    monday = t + 4 * 86400000
    clock[0] = session_window(monday)[0] + 1000
    with pytest.raises(ObservationError, match="Missing session"):
        observe(p, monday, clock)
    j.close()


def test_recovery_detects_inconsistent_allocator(tmp_path):
    j, _, _, t, clock = setup(tmp_path)
    p = producer(j)
    observe(p, t, clock)
    with pytest.raises(ObservationError, match="differs"):
        CausalTrendProducer(
            j,
            verify_inputs=lambda inputs: None,
            compute_signals=lambda inputs: {"A": 0.1},
            allocator_factory=lambda: lambda signals, context: {"A": 0.9},
        )
    j.close()


def test_missing_forecasts_are_failed_not_flat_decisions(tmp_path):
    j, _, _, t, clock = setup(tmp_path)
    p = producer(j, compute=lambda inputs: {"A": None})
    assert observe(p, t, clock)["status"] == "FAILED"
    assert j.state()["completed"] == 0
    j.close()


def test_stale_producer_recovers_another_instances_commits(tmp_path):
    j, binding, epoch, t, clock = setup(tmp_path)
    first = producer(j)
    observe(first, t, clock)
    other_j = CausalTrendJournal(
        tmp_path / "journal.sqlite", epoch=epoch, binding=binding, clock=lambda: clock[0]
    )
    other = producer(other_j)
    friday = t + 86400000
    clock[0] = session_window(friday)[0] + 1000
    observe(other, friday, clock)
    monday = t + 4 * 86400000
    clock[0] = session_window(monday)[0] + 1000
    assert observe(first, monday, clock)["status"] == "DECISION"
    assert first.allocator.n == 3
    other_j.close()
    j.close()


def test_missed_deadline_does_not_advance_allocator(tmp_path):
    j, _, _, t, clock = setup(tmp_path)

    def slow_signals(inputs):
        clock[0] = session_window(t)[1] + 1
        return dict.fromkeys(["A", "B", "C", "D", "E"], 0.1)

    p = producer(j, compute=slow_signals)
    assert observe(p, t, clock)["status"] == "MISSED"
    assert p.allocator.n == 0 and j.state()["completed"] == 0
    j.close()
