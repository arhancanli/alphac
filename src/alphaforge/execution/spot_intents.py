"""Durable pre-submission reservations for the isolated spot restart.

No broker transport is included. A new reservation is the only result eligible
for a future submitter; replay is NEVER permission to resubmit. A production
reconciler must verify fills, canceled remainders and fee activities before
recording terminal evidence. This journal does not authenticate that evidence.
"""

import hashlib
import json
import sqlite3
from pathlib import Path


class SpotIntentJournal:
    def __init__(self, path: Path, *, account_binding: str, epoch: str):
        if not account_binding or not epoch:
            raise ValueError("account and epoch required")
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS binding (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                account TEXT NOT NULL, epoch TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                decision_ms INTEGER PRIMARY KEY,
                payload TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','terminal')),
                evidence TEXT
            );
            CREATE TABLE IF NOT EXISTS order_ids (
                client_order_id TEXT PRIMARY KEY,
                decision_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submission_attempts (
                client_order_id TEXT PRIMARY KEY,
                claimed_at_ms INTEGER NOT NULL,
                acknowledgement TEXT
            );
            CREATE TABLE IF NOT EXISTS dispatch_starts (
                decision_ms INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS submission_stops (
                decision_ms INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS decision_evidence (
                decision_ms INTEGER PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decision_baselines (
                decision_ms INTEGER PRIMARY KEY,
                payload TEXT NOT NULL
            );
        """)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT account, epoch FROM binding").fetchone()
            if row is None:
                self.conn.execute("INSERT INTO binding VALUES (1,?,?)", (account_binding, epoch))
            elif row != (account_binding, epoch):
                raise ValueError("journal belongs to another account or epoch")
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            self.conn.close()
            raise

    def close(self) -> None:
        self.conn.close()

    def seal_baseline(self, decision_ms: int, payload: dict) -> None:
        """Bind a baseline independently for explicit recovery and legacy callers."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._seal_baseline_in_transaction(decision_ms, payload)
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def _seal_baseline_in_transaction(self, decision_ms: int, payload: dict) -> None:
        if not self.conn.in_transaction:
            raise RuntimeError("baseline write requires a transaction")
        from alphaforge.execution.spot_paper import number

        if set(payload) != {"account_binding", "cash", "positions", "observed_at_ms"}:
            raise ValueError("exact baseline fields required")
        if (
            type(decision_ms) is not int
            or type(payload["observed_at_ms"]) is not int
            or payload["observed_at_ms"] < decision_ms
        ):
            raise ValueError("baseline timestamp precedes decision")
        number(payload["cash"])
        positions = payload["positions"]
        if not isinstance(positions, dict) or not set(positions).issubset({"BTC/USD", "ETH/USD"}):
            raise ValueError("unexpected baseline positions")
        for qty in positions.values():
            number(qty)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > 16_384:
            raise ValueError("oversized baseline")
        binding = self.conn.execute("SELECT account FROM binding").fetchone()[0]
        if payload["account_binding"] != binding:
            raise ValueError("baseline belongs to another account")
        existing = self.conn.execute(
            "SELECT payload FROM decision_baselines WHERE decision_ms=?", (decision_ms,)
        ).fetchone()
        if existing:
            if existing[0] != encoded:
                raise ValueError("baseline is immutable")
        else:
            decision = self.conn.execute(
                "SELECT state,payload FROM decisions WHERE decision_ms=?", (decision_ms,)
            ).fetchone()
            if decision is None or (decision[0] != "pending" and decision != ("terminal", "[]")):
                raise ValueError("pending decision required before sealing baseline")
            if self.conn.execute(
                "SELECT 1 FROM submission_attempts a JOIN order_ids o "
                "ON a.client_order_id=o.client_order_id WHERE o.decision_ms=?",
                (decision_ms,),
            ).fetchone():
                raise ValueError("cannot establish a baseline after a submission attempt")
            self.conn.execute("INSERT INTO decision_baselines VALUES (?,?)", (decision_ms, encoded))

    def baseline_for_order(self, client_order_id: str) -> dict:
        row = self.conn.execute(
            "SELECT b.payload FROM decision_baselines b JOIN order_ids o "
            "ON b.decision_ms=o.decision_ms WHERE o.client_order_id=?",
            (client_order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("sealed pre-submission baseline is missing")
        return json.loads(row[0])

    def claim_submission(self, order: dict[str, str], *, now_ms: int) -> str:
        """Record possible transmission BEFORE I/O. This is not runtime clearance.

        A process crash after this commit but before a request is indistinguishable
        from a lost response. Both remain reserved until explicit reconciliation;
        a replay never obtains permission to send again. No acknowledgement for
        another attempted order means stop the batch, not continue optimistically.
        """
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("invalid attempt timestamp")
        client_id = order.get("client_order_id")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT d.payload,d.state,d.decision_ms FROM decisions d JOIN order_ids o "
                "ON d.decision_ms=o.decision_ms WHERE o.client_order_id=?",
                (client_id,),
            ).fetchone()
            if row is None or order not in json.loads(row[0]):
                raise ValueError("submission differs from durable reservation")
            if self.conn.execute(
                "SELECT 1 FROM submission_attempts WHERE client_order_id=?", (client_id,)
            ).fetchone():
                result = "ALREADY_ATTEMPTED_NEVER_RESEND"
            else:
                if self.conn.execute(
                    "SELECT 1 FROM submission_stops WHERE decision_ms=?", (row[2],)
                ).fetchone():
                    raise ValueError("submissions permanently stopped for this decision")
                if row[1] != "pending" or now_ms < row[2]:
                    raise ValueError("decision not pending or timestamp regressed")
                if self.conn.execute(
                    "SELECT 1 FROM submission_attempts a JOIN order_ids o "
                    "ON a.client_order_id=o.client_order_id JOIN decisions d "
                    "ON d.decision_ms=o.decision_ms WHERE d.state='pending' "
                    "AND a.acknowledgement IS NULL"
                ).fetchone():
                    raise ValueError("uncertain prior attempt blocks further submission")
                self.conn.execute(
                    "INSERT INTO submission_attempts VALUES (?,?,NULL)", (client_id, now_ms)
                )
                result = "CLAIMED_NOT_RUNTIME_CLEARANCE"
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise

    def begin_dispatch(self, decision_ms: int) -> tuple[dict, ...]:
        """Acquire a durable one-shot dispatch; crashes require reconciliation."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT payload,state FROM decisions WHERE decision_ms=?", (decision_ms,)
            ).fetchone()
            if row is None or row[1] != "pending":
                raise ValueError("pending reserved decision required for dispatch")
            for table in ("dispatch_starts", "submission_stops"):
                if self.conn.execute(
                    f"SELECT 1 FROM {table} WHERE decision_ms=?", (decision_ms,)
                ).fetchone():
                    raise ValueError("decision already dispatched or stopped; reconcile only")
            if self.conn.execute(
                "SELECT 1 FROM submission_attempts a JOIN order_ids o "
                "ON a.client_order_id=o.client_order_id WHERE o.decision_ms=?",
                (decision_ms,),
            ).fetchone():
                raise ValueError("prior submission attempt; reconcile only")
            self.conn.execute("INSERT INTO dispatch_starts VALUES (?)", (decision_ms,))
            self.conn.commit()
            return tuple(json.loads(row[0]))
        except BaseException:
            self.conn.rollback()
            raise

    def stop_submissions(self, decision_ms: int) -> tuple[str, ...]:
        """Irreversibly close the batch and snapshot attempted IDs atomically.

        An already claimed request can still be in flight. It remains an attempt
        requiring broker reconciliation, even if no acknowledgement exists yet.
        """
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT state FROM decisions WHERE decision_ms=?", (decision_ms,)
            ).fetchone()
            if row != ("pending",):
                raise ValueError("pending decision required to stop submissions")
            self.conn.execute("INSERT OR IGNORE INTO submission_stops VALUES (?)", (decision_ms,))
            attempts = self.conn.execute(
                "SELECT a.client_order_id FROM submission_attempts a JOIN order_ids o "
                "ON a.client_order_id=o.client_order_id WHERE o.decision_ms=? "
                "ORDER BY a.client_order_id",
                (decision_ms,),
            ).fetchall()
            self.conn.commit()
            return tuple(row[0] for row in attempts)
        except BaseException:
            self.conn.rollback()
            raise

    def record_acknowledgement(self, client_order_id: str, response: dict) -> None:
        """Persist a validated first broker acknowledgement, never terminal clearance.

        Later order transitions belong in reconciliation evidence, not an edit
        of the first acknowledgement. Transport failures must leave this NULL.
        """
        from alphaforge.execution.spot_paper import assess_order

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT d.payload,a.acknowledgement FROM submission_attempts a "
                "JOIN order_ids o ON o.client_order_id=a.client_order_id "
                "JOIN decisions d ON d.decision_ms=o.decision_ms "
                "WHERE a.client_order_id=?",
                (client_order_id,),
            ).fetchone()
            if row is None:
                raise ValueError("acknowledgement without durable attempt")
            intent = next(o for o in json.loads(row[0]) if o["client_order_id"] == client_order_id)
            assess_order(intent, response)
            if response.get("status") not in {
                "accepted",
                "pending_new",
                "new",
                "partially_filled",
                "filled",
                "pending_cancel",
                "canceled",
                "expired",
                "rejected",
            }:
                raise ValueError("unrecognized acknowledgement status remains uncertain")
            fields = (
                "id",
                "client_order_id",
                "asset_class",
                "symbol",
                "side",
                "type",
                "time_in_force",
                "qty",
                "limit_price",
                "filled_qty",
                "filled_avg_price",
                "status",
            )
            encoded = json.dumps(
                {k: response.get(k) for k in fields},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if len(encoded.encode()) > 16_384:
                raise ValueError("acknowledgement exceeds size budget")
            if row[1] is not None and row[1] != encoded:
                raise ValueError("first acknowledgement is immutable")
            self.conn.execute(
                "UPDATE submission_attempts SET acknowledgement=? WHERE client_order_id=?",
                (encoded, client_order_id),
            )
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def reserve(
        self,
        decision_ms: int,
        orders: tuple[dict[str, str], ...],
        *,
        baseline: dict | None = None,
        evidence: dict | None = None,
    ) -> str:
        """Atomically reserve all intents. Returns NEW, REPLAY_PENDING or REPLAY_TERMINAL.

        When provided, the baseline is validated and sealed in the same commit.
        Any baseline failure rolls back the reservation and all order identities.
        Even an empty decision advances chronology, preventing later historical
        signals from being traded. Empty decisions are terminal immediately.
        """
        if type(decision_ms) is not int or decision_ms < 0:
            raise ValueError("invalid decision timestamp")
        payload = json.dumps(orders, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(payload.encode()) > 16_384 or len(orders) > 2:
            raise ValueError("oversized decision")
        ids = [o.get("client_order_id") for o in orders]
        if any(not isinstance(i, str) or not i or len(i) > 48 for i in ids):
            raise ValueError("invalid client order id")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate order ids")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT payload,state FROM decisions WHERE decision_ms=?", (decision_ms,)
            ).fetchone()
            if row:
                if row[0] != payload:
                    raise ValueError("conflicting decision replay")
                result = "REPLAY_" + row[1].upper()
            else:
                latest = self.conn.execute("SELECT MAX(decision_ms) FROM decisions").fetchone()[0]
                if latest is not None and decision_ms <= latest:
                    raise ValueError("decision chronology regression")
                if self.conn.execute("SELECT 1 FROM decisions WHERE state='pending'").fetchone():
                    raise ValueError("prior uncertain intents require broker reconciliation")
                self.conn.execute(
                    "INSERT INTO decisions VALUES (?,?,?,NULL)",
                    (decision_ms, payload, "pending" if orders else "terminal"),
                )
                self.conn.executemany(
                    "INSERT INTO order_ids VALUES (?,?)", [(i, decision_ms) for i in ids]
                )
                result = "NEW"
            if baseline is not None:
                self._seal_baseline_in_transaction(decision_ms, baseline)
            if evidence is not None:
                encoded = json.dumps(
                    evidence, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
                if not 0 < len(encoded.encode()) <= 131_072:
                    raise ValueError("bounded preparation evidence required")
                old = self.conn.execute(
                    "SELECT payload FROM decision_evidence WHERE decision_ms=?", (decision_ms,)
                ).fetchone()
                if old:
                    if old[0] != encoded:
                        raise ValueError("preparation evidence is immutable")
                elif result != "NEW":
                    raise ValueError("cannot attach evidence retroactively on replay")
                else:
                    self.conn.execute(
                        "INSERT INTO decision_evidence VALUES (?,?,?)",
                        (decision_ms, encoded, hashlib.sha256(encoded.encode()).hexdigest()),
                    )
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise

    def evidence_for_decision(self, decision_ms: int) -> dict:
        row = self.conn.execute(
            "SELECT payload,sha256 FROM decision_evidence WHERE decision_ms=?", (decision_ms,)
        ).fetchone()
        if row is None or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError("preparation evidence missing or checksum mismatch")
        return json.loads(row[0])

    def record_terminal(
        self, decision_ms: int, *, reconciled_payload_sha256: str, evidence: bytes
    ) -> None:
        """Persist bounded external reconciliation evidence, not a verification claim.

        Caller supplies hash of the exact stored order payload to prevent settling
        a different decision. The future broker reconciler owns evidence validation.
        """
        if not isinstance(evidence, bytes) or not 0 < len(evidence) <= 65_536:
            raise ValueError("bounded nonempty reconciliation evidence required")
        evidence_digest = hashlib.sha256(evidence).hexdigest()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT payload,state,evidence FROM decisions WHERE decision_ms=?", (decision_ms,)
            ).fetchone()
            if (
                row is None
                or hashlib.sha256(row[0].encode()).hexdigest() != reconciled_payload_sha256
            ):
                raise ValueError("reconciliation does not bind reserved payload")
            # Store the evidence itself for review, not only a caller-supplied hash.
            record = json.dumps({"sha256": evidence_digest, "hex": evidence.hex()}, sort_keys=True)
            if row[1] == "terminal":
                if row[2] != record:
                    raise ValueError("terminal evidence conflict")
            else:
                self.conn.execute(
                    "UPDATE decisions SET state='terminal',evidence=? WHERE decision_ms=?",
                    (record, decision_ms),
                )
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
