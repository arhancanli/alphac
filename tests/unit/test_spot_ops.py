import asyncio
import hashlib
import sqlite3

import pytest

from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_ops import inspect_journal, recover_decision

ORDER = {"client_order_id": "ops-test"}
BASELINE = {"account_binding": "account", "cash": "1000", "positions": {}, "observed_at_ms": 101}


@pytest.mark.parametrize("phase", ["reserved", "started", "attempted"])
def test_status_distinguishes_uncertainty_without_mutation(tmp_path, phase):
    path = tmp_path / "state.sqlite"
    journal = SpotIntentJournal(path, account_binding="account", epoch="spot")
    journal.reserve(100, (ORDER,), baseline=BASELINE)
    if phase in {"started", "attempted"}:
        journal.begin_dispatch(100)
    if phase == "attempted":
        journal.claim_submission(ORDER, now_ms=102)
    journal.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    report = inspect_journal(path)
    row = report["latest_decisions"][0]
    assert report["network_requests"] == 0
    assert report["submission_authorized"] is False
    assert row["attempted_orders"] == (1 if phase == "attempted" else 0)
    assert row["unacknowledged_attempts"] == (1 if phase == "attempted" else 0)
    assert row["next_action"] == (
        "RESERVED_NOT_EXECUTION_CLEARANCE" if phase == "reserved" else "RECONCILE_ONLY_NEVER_RESEND"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_missing_and_foreign_database_are_not_created_or_migrated(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        inspect_journal(path)
    assert not path.exists()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.close()
    with pytest.raises(ValueError, match="schema"):
        inspect_journal(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
        ("unrelated",)
    ]
    conn.close()


def test_recovery_binding_checked_before_credentials(tmp_path):
    path = tmp_path / "state.sqlite"
    journal = SpotIntentJournal(path, account_binding="account", epoch="spot")
    journal.close()
    with pytest.raises(ValueError, match="account/epoch"):
        asyncio.run(
            recover_decision(
                path,
                account_binding="other",
                epoch="spot",
                decision_ms=100,
                until="2024-01-03T00:00:00Z",
                credentials_path=tmp_path / "absent.env",
            )
        )


def test_status_preserves_missing_baseline_requirement(tmp_path):
    path = tmp_path / "state.sqlite"
    journal = SpotIntentJournal(path, account_binding="account", epoch="spot")
    journal.reserve(100, (ORDER,))
    journal.close()
    assert (
        inspect_journal(path)["latest_decisions"][0]["next_action"]
        == "BASELINE_MISSING_EXPLICIT_RECOVERY_REQUIRED"
    )
