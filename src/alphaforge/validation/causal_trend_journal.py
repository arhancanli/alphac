"""Versioned corrected-candidate journal; original journal remains reproducible.

Initialization is versioned because the original recorder pins a superseded
candidate. Lifecycle, deadlines and immutable event machinery are inherited.
A binding authenticates local content consistency, not independent timestamps.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from alphaforge.validation.experiments import hypothesis_hash
from alphaforge.validation.trend_observation import (
    ObservationError,
    TrendObservationJournal,
    canonical,
    fingerprint,
)


class CausalTrendJournal(TrendObservationJournal):
    def __init__(
        self, path: Path, *, epoch: dict, binding: dict, clock: Callable[[], int] | None = None
    ):
        required = {"epoch_id", "mode", "candidate_id", "candidate_fingerprint", "initial_state"}
        if set(epoch) != required or epoch["mode"] not in {
            "SHADOW_PROSPECTIVE",
            "REPLAY_DIAGNOSTIC",
        }:
            raise ObservationError("Exact epoch fields and explicit mode required")
        if epoch["candidate_id"] != "59901461092dd7a6":
            raise ObservationError("Corrected causal candidate required")
        if not epoch["epoch_id"] or len(epoch["candidate_fingerprint"]) != 64:
            raise ObservationError("Epoch ID and SHA256 candidate fingerprint required")
        int(epoch["candidate_fingerprint"], 16)
        if hypothesis_hash(binding["trial_config"]) != epoch["candidate_id"]:
            raise ObservationError("Candidate configuration identity mismatch")
        if fingerprint(binding) != epoch["candidate_fingerprint"]:
            raise ObservationError("Producer binding mismatch")
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
