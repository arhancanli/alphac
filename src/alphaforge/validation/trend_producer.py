"""Bounded corrected-candidate producer with replayable allocation state.

Adapters supply immutable input verification, causal signal computation, and a
fresh allocator. Their implementation and input sources must enter the journal
binding. This orchestrator is not a feed authenticator or an execution service.
"""

from __future__ import annotations

import json
import math

from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.validation.trend_observation import ObservationError, canonical


class CausalTrendProducer:
    def __init__(self, journal, *, verify_inputs, compute_signals, allocator_factory):
        self.journal = journal
        self.verify_inputs = verify_inputs
        self.compute_signals = compute_signals
        self.allocator_factory = allocator_factory
        if journal.epoch["candidate_id"] != "59901461092dd7a6":
            raise ObservationError("Corrected candidate journal required")
        if journal.epoch["initial_state"] != {"completed": 0, "last_session": None}:
            raise ObservationError("New producer requires an explicit empty epoch state")
        self.recover()

    def recover(self):
        self.journal.verify()
        allocator = self.allocator_factory()
        rows = self.journal.conn.execute(
            "SELECT c.session_ms,c.payload,d.payload FROM events c JOIN events d "
            "ON c.session_ms=d.session_ms WHERE c.kind='CAPTURE' "
            "AND d.kind='DECISION' ORDER BY c.seq"
        ).fetchall()
        for n, (session, capture, decision) in enumerate(rows, 1):
            inputs = json.loads(capture)["inputs"]
            result = json.loads(decision)
            self.verify_inputs(inputs)
            if dict(allocator(result["signals"], inputs["context"])) != result["targets"]:
                raise ObservationError("Recovered allocator differs from committed targets")
            if result["allocation_state"] != {"completed": n, "last_session": session}:
                raise ObservationError("Producer state sequence mismatch")
        self.recovered_state = {
            "completed": len(rows),
            "last_session": rows[-1][0] if rows else None,
        }
        self.allocator = allocator
        return len(rows)

    def produce(self, *, session_ms, inputs, received_ms, clock_evidence=None):
        # Deep copy before verification/capture; caller mutation cannot replace inputs.
        inputs = json.loads(canonical(inputs))
        if inputs.get("session_ms") != session_ms or "context" not in inputs:
            raise ObservationError("Session-bound inputs and allocation context required")
        self.verify_inputs(inputs)
        self.recover()
        state = self.recovered_state.copy()
        if state["last_session"] is not None:
            expected = calendar_for(AssetClass.EQUITY).next_bar_open(
                state["last_session"], Timeframe.D1
            )
            if session_ms != expected:
                raise ObservationError(
                    "Missing session requires an explicit new epoch; no silent reset"
                )

        def calculate(captured, prior):
            self.verify_inputs(captured)
            signals = self.compute_signals(captured)
            if sum(type(v) in (int, float) and math.isfinite(v) for v in signals.values()) < 5:
                raise ObservationError("Insufficient finite forecasts; refuse an empty decision")
            targets = dict(self.allocator(signals, captured["context"]))
            self.verify_inputs(captured)
            return {
                "signals": signals,
                "targets": targets,
                "allocation_state": {
                    "completed": prior["completed"] + 1,
                    "last_session": session_ms,
                },
            }

        try:
            return self.journal.observe(
                session_ms=session_ms,
                inputs=inputs,
                received_ms=received_ms,
                state_before=state,
                compute=calculate,
                clock_evidence=clock_evidence,
            )
        finally:
            # Failed computation may have mutated the in-memory allocator. Rebuild
            # only committed decisions, including after deadline failure/interruption.
            self.recover()
