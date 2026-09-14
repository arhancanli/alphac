"""One-shot dispatch of an already reserved spot decision; no installed scheduler.

Signal planning and source-bound readiness remain application responsibilities.
The driver never replans, renews a deadline, retries a POST, or infers settlement
from an acknowledgement. Recovery uses the independent read-only reconciler.
"""

import asyncio
import time

from alphaforge.execution.spot_reconcile import capture_baseline
from alphaforge.execution.spot_submit import SubmissionBlocked


async def dispatch_decision(submitter, journal, *, decision_ms: int, valid_until_ms: int):
    """Dispatch once, sequentially, and permanently close the batch on every exit.

    The caller owns the reader and journal lifecycle. A process crash after the
    durable start prevents a replacement driver from resuming submission. A
    claimed request may still be in flight; recovery must retain that uncertainty.
    """
    if submitter.enabled is not True or submitter.readiness_check is None:
        raise SubmissionBlocked("paper activation or readiness provider unavailable")
    binding = journal.conn.execute("SELECT account,epoch FROM binding").fetchone()
    if binding != (submitter.account_binding, submitter.epoch):
        raise SubmissionBlocked("driver account or epoch mismatch")
    start_wall, start_mono = time.time_ns(), time.monotonic_ns()
    now_ms = start_wall // 1_000_000
    if type(valid_until_ms) is not int or not now_ms < valid_until_ms <= now_ms + 5_000:
        raise SubmissionBlocked("short-lived batch deadline required")
    deadline_mono = start_mono + valid_until_ms * 1_000_000 - start_wall

    def check_clock():
        wall, mono = time.time_ns(), time.monotonic_ns()
        if abs((wall - start_wall) - (mono - start_mono)) > 10_000_000:
            raise SubmissionBlocked("clock discontinuity during batch")
        if wall >= valid_until_ms * 1_000_000 or mono >= deadline_mono:
            raise SubmissionBlocked("batch deadline expired")

    orders = journal.begin_dispatch(decision_ms)
    outcomes = []
    try:
        check_clock()
        try:
            async with asyncio.timeout((deadline_mono - time.monotonic_ns()) / 1e9):
                await capture_baseline(submitter.reader, journal, decision_ms=decision_ms)
        except TimeoutError:
            raise SubmissionBlocked("baseline capture exceeded batch deadline") from None
        for order in orders:
            check_clock()
            result = await submitter.submit(journal, order, valid_until_ms=valid_until_ms)
            outcomes.append({"client_order_id": order["client_order_id"], **result})
            if result["status"] != "ACKNOWLEDGED_NOT_SETTLED":
                break
        return {
            "status": "DISPATCH_FINISHED_RECONCILIATION_REQUIRED",
            "decision_ms": decision_ms,
            "outcomes": outcomes,
            "journal_clearance": False,
        }
    finally:
        # Synchronous durable operation also runs on asyncio cancellation. A hard
        # process kill is covered by the independently persisted dispatch start.
        journal.stop_submissions(decision_ms)
