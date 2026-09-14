"""Isolated local observation journal. No broker, scheduler or performance claims.

Inputs are sealed before computation. A failed/pending decision cannot be retried
under the same session. SQLite transactions serialize writers; hash chaining detects
ordinary edits but is not an independent timestamp authority or protection against
an administrator rewriting the entire database and its external checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path


class ObservationError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def session_window(session_ms: int) -> tuple[int, int]:
    """Actual XNYS close and next session market open; midnight labels are not clocks."""
    import exchange_calendars as xcals
    import pandas as pd

    if type(session_ms) is not int or session_ms % 86400000:
        raise ObservationError("UTC-midnight session label required")
    cal = xcals.get_calendar("XNYS", start="2000-01-01", end="2030-12-31")
    session = pd.Timestamp(session_ms, unit="ms")
    if not cal.is_session(session):
        raise ObservationError("Not an XNYS session")
    next_session = cal.next_session(session)
    return (
        int(cal.session_close(session).value // 1000000),
        int(cal.session_open(next_session).value // 1000000),
    )


class TrendObservationJournal:
    def __init__(self, path: Path, *, epoch: dict, clock: Callable[[], int] | None = None):
        required = {"epoch_id", "mode", "candidate_id", "candidate_fingerprint", "initial_state"}
        if set(epoch) != required or epoch["mode"] not in {
            "SHADOW_PROSPECTIVE",
            "REPLAY_DIAGNOSTIC",
        }:
            raise ObservationError("Exact epoch fields and explicit mode required")
        if epoch["candidate_id"] != "ec7ec19175ac10a9":
            raise ObservationError("Frozen directional candidate required")
        if not epoch["epoch_id"] or len(epoch["candidate_fingerprint"]) != 64:
            raise ObservationError("Epoch ID and SHA256 candidate fingerprint required")
        int(epoch["candidate_fingerprint"], 16)
        self.epoch = json.loads(canonical(epoch))
        self.clock = clock or (lambda: time.time_ns() // 1000000)
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS epoch (
                id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, session_ms INTEGER NOT NULL, kind TEXT NOT NULL,
                recorded_ms INTEGER NOT NULL, payload TEXT NOT NULL, previous TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE, UNIQUE(session_ms,kind));
            CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT,'immutable events'); END;
            CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT,'immutable events'); END;
            CREATE TRIGGER IF NOT EXISTS no_epoch_update BEFORE UPDATE ON epoch
                BEGIN SELECT RAISE(ABORT,'immutable epoch'); END;
            CREATE TRIGGER IF NOT EXISTS no_epoch_delete BEFORE DELETE ON epoch
                BEGIN SELECT RAISE(ABORT,'immutable epoch'); END;
        """)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT payload FROM epoch WHERE id=1").fetchone()
            if row is None:
                self.conn.execute("INSERT INTO epoch VALUES(1,?)", (canonical(epoch),))
            elif row[0] != canonical(epoch):
                raise ObservationError("Epoch/config mismatch; create a separate journal")
            self.conn.commit()
            self.verify()
        except BaseException:
            if self.conn.in_transaction:
                self.conn.rollback()
            self.conn.close()
            raise

    def close(self):
        self.conn.close()

    def _append(self, session, kind, payload, now):
        assert self.conn.in_transaction
        row = self.conn.execute(
            "SELECT seq,digest,recorded_ms FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq, previous = (row[0] + 1, row[1]) if row else (1, fingerprint(self.epoch))
        if row and now < row[2]:
            raise ObservationError("Clock moved backwards")
        body = [seq, session, kind, now, payload, previous]
        digest = fingerprint(body)
        self.conn.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
            (seq, session, kind, now, canonical(payload), previous, digest),
        )
        return digest

    def verify(self):
        binding = self.conn.execute("SELECT payload FROM epoch WHERE id=1").fetchone()
        if binding is None or binding[0] != canonical(self.epoch):
            raise ObservationError("Epoch binding mismatch")
        previous = fingerprint(self.epoch)
        last_time = -1
        sessions = {}
        rows = self.conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        for i, (seq, session, kind, now, raw, prev, digest) in enumerate(rows, 1):
            payload = json.loads(raw)
            if (
                seq != i
                or prev != previous
                or now < last_time
                or digest != fingerprint([seq, session, kind, now, payload, prev])
            ):
                raise ObservationError("Journal chain mismatch")
            prior = sessions.get(session)
            if kind == "CAPTURE":
                if prior is not None:
                    raise ObservationError("Duplicate capture")
            elif kind not in {"DECISION", "FAILED", "MISSED"} or prior != "CAPTURE":
                raise ObservationError("Invalid observation lifecycle")
            sessions[session] = kind
            previous, last_time = digest, now
        return {
            "events": len(rows),
            "head_sha256": previous,
            "pending_sessions": [s for s, k in sessions.items() if k == "CAPTURE"],
            "mode": self.epoch["mode"],
            "execution_authorized": False,
        }

    def state(self):
        row = self.conn.execute(
            "SELECT payload FROM events WHERE kind='DECISION' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0])["allocation_state"] if row else self.epoch["initial_state"]

    def observe(
        self,
        *,
        session_ms: int,
        inputs: dict,
        received_ms: int,
        state_before: dict,
        compute: Callable[[dict, dict], dict],
        clock_evidence: dict | None = None,
    ):
        """Seal supplied producer evidence, then calculate at most once before next open.

        Input bytes, provider identity and vendor/receive times belong in ``inputs``;
        the journal binds those assertions but does not authenticate a vendor. A
        SHADOW record additionally requires a recent bounded clock attestation. The
        production collector must supply and independently verify that evidence.
        """
        close_ms, open_ms = session_window(session_ms)
        now = self.clock()
        if clock_evidence is not None:
            clock_evidence = json.loads(canonical(clock_evidence))
        if not isinstance(inputs, dict) or not inputs:
            raise ObservationError("Nonempty input evidence required")
        inputs = json.loads(canonical(inputs))
        state_before = json.loads(canonical(state_before))
        if type(received_ms) is not int or received_ms > now or received_ms < close_ms:
            raise ObservationError("Input receipt must follow session close and precede capture")
        if self.epoch["mode"] == "SHADOW_PROSPECTIVE":
            if not clock_evidence or set(clock_evidence) != {
                "observed_ms",
                "offset_ms",
                "uncertainty_ms",
                "source_hash",
            }:
                raise ObservationError("Bounded clock evidence required")
            offset, uncertainty = clock_evidence["offset_ms"], clock_evidence["uncertainty_ms"]
            if not all(type(v) in (int, float) and math.isfinite(v) for v in [offset, uncertainty]):
                raise ObservationError("Invalid clock bounds")
            if (
                abs(offset) > 50
                or not 0 <= uncertainty <= 100
                or not 0 <= now - clock_evidence["observed_ms"] <= 60000
            ):
                raise ObservationError("Clock evidence outside bounds")
            if len(clock_evidence["source_hash"]) != 64:
                raise ObservationError("Clock source hash required")
            int(clock_evidence["source_hash"], 16)
            # Conservative boundary incorporates the supplied worst-case clock error.
            now += math.ceil(abs(offset) + uncertainty)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.verify()
            if self.conn.execute(
                "SELECT 1 FROM events WHERE session_ms=?", (session_ms,)
            ).fetchone():
                raise ObservationError("Session already captured; no historical retries")
            if self.verify()["pending_sessions"]:
                raise ObservationError("Pending capture requires explicit missed resolution")
            latest = self.conn.execute("SELECT MAX(session_ms) FROM events").fetchone()[0]
            if latest is not None and session_ms <= latest:
                raise ObservationError("Out-of-order session")
            if canonical(state_before) != canonical(self.state()):
                raise ObservationError("Allocation state does not continue the journal")
            self._append(
                session_ms,
                "CAPTURE",
                {
                    "inputs": inputs,
                    "received_ms": received_ms,
                    "state_before": state_before,
                    "deadline_ms": open_ms,
                    "clock_evidence": clock_evidence,
                },
                now,
            )
            if now >= open_ms:
                self._append(
                    session_ms, "MISSED", {"reason": "capture at or after next market open"}, now
                )
                self.conn.commit()
                return {"status": "MISSED", "execution_authorized": False}
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        try:
            result = json.loads(canonical(compute(inputs, state_before)))
            if set(result) != {"signals", "targets", "allocation_state"}:
                raise ObservationError("Exact output fields required")
            canonical(result)
            if not isinstance(result["signals"], dict) or not isinstance(result["targets"], dict):
                raise ObservationError("Signal and target mappings required")
            if not isinstance(result["allocation_state"], dict):
                raise ObservationError("Allocation state mapping required")
            if not result["signals"]:
                raise ObservationError("Empty signal decision; record missing inputs instead")
            for value in result["signals"].values():
                if value is not None and (
                    type(value) not in (int, float) or not math.isfinite(value)
                ):
                    raise ObservationError("Finite or explicitly missing signals required")
            for value in result["targets"].values():
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ObservationError("Finite target weights required")
            finish = self.clock()
            margin = (
                math.ceil(abs(clock_evidence["offset_ms"]) + clock_evidence["uncertainty_ms"])
                if clock_evidence
                else 0
            )
            finish += margin
            if finish < now:
                raise ObservationError("Clock moved backwards during computation")
            kind = "DECISION" if finish < open_ms else "MISSED"
            payload = (
                result if kind == "DECISION" else {"reason": "computation completed after deadline"}
            )
        except Exception as error:
            kind, payload = "FAILED", {"reason": type(error).__name__}
            finish = max(now, self.clock())
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if session_ms not in self.verify()["pending_sessions"]:
                raise ObservationError("Capture already resolved; discard computed output")
            self._append(session_ms, kind, payload, finish)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return {"status": kind, "execution_authorized": False}

    def miss(self, session_ms: int, *, reason: str):
        """Record unavailable inputs explicitly, without fabricated quotes or zero returns."""
        close_ms, open_ms = session_window(session_ms)
        now = self.clock()
        if not reason or now < close_ms:
            raise ObservationError("Reason and elapsed session close required")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if self.verify()["pending_sessions"]:
                raise ObservationError("Resolve pending capture first")
            latest = self.conn.execute("SELECT MAX(session_ms) FROM events").fetchone()[0]
            if latest is not None and session_ms <= latest:
                raise ObservationError("Session already recorded or out of order")
            self._append(
                session_ms,
                "CAPTURE",
                {
                    "input_status": "UNAVAILABLE",
                    "deadline_ms": open_ms,
                    "state_before": self.state(),
                    "reason": reason,
                },
                now,
            )
            self._append(session_ms, "MISSED", {"reason": reason}, now)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def abandon_pending(self, session_ms: int, *, reason: str):
        """Mark an interrupted capture missed; never recompute or supply replacement output."""
        if not reason:
            raise ObservationError("Missing reason")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            check = self.verify()
            if session_ms not in check["pending_sessions"]:
                raise ObservationError("No pending capture")
            self._append(session_ms, "MISSED", {"reason": reason}, self.clock())
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
