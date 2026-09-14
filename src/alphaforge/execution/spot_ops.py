"""Operator inspection and explicit reconciliation; no submission or activation API."""

import sqlite3
from pathlib import Path

REQUIRED_TABLES = {
    "binding",
    "decisions",
    "order_ids",
    "submission_attempts",
    "decision_baselines",
    "dispatch_starts",
    "submission_stops",
}


def inspect_journal(path: Path) -> dict:
    """Read one consistent snapshot of an existing journal, without migrations.

    No credentials or network. Report durable observations, not broker readiness.
    An unacknowledged claim may be in flight; it is never an unsent order.
    """
    path = path.resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES.issubset(tables):
            raise ValueError("unrecognized or older spot journal schema; no automatic migration")
        bindings = conn.execute("SELECT account,epoch FROM binding").fetchall()
        if len(bindings) != 1:
            raise ValueError("exactly one journal account and epoch required")
        counts = dict(conn.execute("SELECT state,COUNT(*) FROM decisions GROUP BY state"))
        rows = conn.execute("""
            SELECT d.decision_ms,d.state,d.evidence IS NOT NULL,
                b.decision_ms IS NOT NULL,ds.decision_ms IS NOT NULL,ss.decision_ms IS NOT NULL,
                (SELECT COUNT(*) FROM order_ids o WHERE o.decision_ms=d.decision_ms),
                (SELECT COUNT(*) FROM order_ids o JOIN submission_attempts a
                    ON o.client_order_id=a.client_order_id WHERE o.decision_ms=d.decision_ms),
                (SELECT COUNT(*) FROM order_ids o JOIN submission_attempts a
                    ON o.client_order_id=a.client_order_id WHERE o.decision_ms=d.decision_ms
                    AND a.acknowledgement IS NULL)
            FROM decisions d LEFT JOIN decision_baselines b ON b.decision_ms=d.decision_ms
            LEFT JOIN dispatch_starts ds ON ds.decision_ms=d.decision_ms
            LEFT JOIN submission_stops ss ON ss.decision_ms=d.decision_ms
            ORDER BY d.decision_ms DESC LIMIT 100
        """).fetchall()
        decisions = []
        for (
            day,
            state,
            evidence,
            baseline,
            started,
            stopped,
            reserved,
            attempted,
            uncertain,
        ) in rows:
            if state == "terminal":
                action = "TERMINAL_RECORDED_NOT_BROKER_REVERIFIED"
            elif not baseline:
                action = "BASELINE_MISSING_EXPLICIT_RECOVERY_REQUIRED"
            elif attempted or started or stopped:
                action = "RECONCILE_ONLY_NEVER_RESEND"
            else:
                action = "RESERVED_NOT_EXECUTION_CLEARANCE"
            decisions.append(
                {
                    "decision_ms": day,
                    "state": state,
                    "baseline_sealed": bool(baseline),
                    "dispatch_started": bool(started),
                    "submissions_stopped": bool(stopped),
                    "reserved_orders": reserved,
                    "attempted_orders": attempted,
                    "unacknowledged_attempts": uncertain,
                    "unattempted_orders": reserved - attempted,
                    "terminal_evidence_recorded": bool(evidence),
                    "next_action": action,
                }
            )
        return {
            "schema": "alphaforge.spot-operator-status.v1",
            "account_binding": bindings[0][0],
            "epoch": bindings[0][1],
            "decision_counts": counts,
            "latest_decisions": decisions,
            "truncated": sum(counts.values()) > len(decisions),
            "network_requests": 0,
            "submission_authorized": False,
            "broker_state_verified": False,
        }
    finally:
        conn.close()


async def recover_decision(
    path: Path,
    *,
    account_binding: str,
    epoch: str,
    decision_ms: int,
    until: str,
    credentials_path: Path,
) -> dict:
    """Explicit operator action: GET-only broker access, durable local reconciliation.

    Requires an existing sealed baseline. Does not reset an account, synthesize a
    missing baseline, cancel orders, resend requests, or create a new epoch.
    """
    from alphaforge.execution.spot_intents import SpotIntentJournal
    from alphaforge.execution.spot_paper import PaperCredentials, PaperReader
    from alphaforge.execution.spot_reconcile import settle_decision

    status = inspect_journal(path)
    if (status["account_binding"], status["epoch"]) != (account_binding, epoch):
        raise ValueError("operator account/epoch differs from journal")
    credentials = PaperCredentials.from_file(credentials_path)
    journal = SpotIntentJournal(path, account_binding=account_binding, epoch=epoch)
    reader = PaperReader(credentials)
    try:
        return await settle_decision(reader, journal, decision_ms=decision_ms, until=until)
    finally:
        await reader.close()
        journal.close()
