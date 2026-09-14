"""Offline composition of spot signals, planning and durable daily reservation."""

from pathlib import Path

from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_plan import Asset, Quote, Snapshot, plan_orders
from alphaforge.portfolio.spot_restart import DAY_MS, DailyClose, target_weights


def reserve_daily_plan(
    *,
    journal_path: Path,
    epoch: str,
    account_binding: str,
    decision_ms: int,
    histories: dict[str, tuple[DailyClose, ...]],
    snapshot: Snapshot,
    assets: dict[str, Asset],
    quotes: dict[str, Quote],
) -> dict:
    """Synthetic/injected-input rehearsal only; never returns submission clearance.

    The first decision of a UTC day freezes that day's payload. Changed prices or
    holdings on replay cannot silently create a second daily allocation.
    """
    targets = target_weights(histories, decision_ms=decision_ms)
    orders = plan_orders(
        epoch=epoch,
        decision_ms=decision_ms,
        expected_account_binding=account_binding,
        snapshot=snapshot,
        assets=assets,
        quotes=quotes,
        targets=targets,
    )
    journal = SpotIntentJournal(journal_path, account_binding=account_binding, epoch=epoch)
    try:
        status = journal.reserve(decision_ms // DAY_MS * DAY_MS, orders)
    finally:
        journal.close()
    return {
        "status": status,
        "orders": orders,
        "submission_authorized": False,
        "performance_validated": False,
    }
