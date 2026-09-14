import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from alphaforge.execution.spot_intents import SpotIntentJournal


def journal(path):
    return SpotIntentJournal(path, account_binding="dedicated", epoch="spot-1")


ORDERS = ({"client_order_id": "afspot-btc", "symbol": "BTC/USD", "qty": "1"},)


def test_restart_never_resubmits_and_conflicting_replay_blocks(tmp_path):
    path = tmp_path / "intents.sqlite"
    first = journal(path)
    assert first.reserve(100, ORDERS) == "NEW"
    first.close()
    second = journal(path)
    assert second.reserve(100, ORDERS) == "REPLAY_PENDING"
    with pytest.raises(ValueError, match="conflicting"):
        second.reserve(100, ({**ORDERS[0], "qty": "2"},))
    with pytest.raises(ValueError, match="uncertain"):
        second.reserve(200, ())
    second.close()


def test_competing_process_equivalent_connections_only_one_new(tmp_path):
    path = tmp_path / "intents.sqlite"
    journal(path).close()

    def reserve(_):
        store = journal(path)
        try:
            return store.reserve(100, ORDERS)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert results.count("NEW") == 1
    assert results.count("REPLAY_PENDING") == 3


def test_terminal_is_bound_and_immutable(tmp_path):
    store = journal(tmp_path / "intents.sqlite")
    store.reserve(100, ORDERS)
    payload = json.dumps(ORDERS, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with pytest.raises(ValueError, match="bind"):
        store.record_terminal(100, reconciled_payload_sha256="wrong", evidence=b"fixture")
    store.record_terminal(100, reconciled_payload_sha256=digest, evidence=b"fixture")
    store.record_terminal(100, reconciled_payload_sha256=digest, evidence=b"fixture")
    with pytest.raises(ValueError, match="conflict"):
        store.record_terminal(100, reconciled_payload_sha256=digest, evidence=b"different")
    assert store.reserve(100, ORDERS) == "REPLAY_TERMINAL"
    assert store.reserve(200, ()) == "NEW"
    with pytest.raises(ValueError, match="chronology"):
        store.reserve(150, ())
    store.close()


def test_binding_and_atomic_failure(tmp_path):
    path = tmp_path / "intents.sqlite"
    store = journal(path)
    with pytest.raises(ValueError, match="another"):
        SpotIntentJournal(path, account_binding="other-sleeve", epoch="spot-1")
    store.conn.execute(
        "CREATE TRIGGER fail_insert BEFORE INSERT ON order_ids "
        "BEGIN SELECT RAISE(ABORT, 'disk fixture'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.reserve(100, ORDERS)
    assert store.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    store.conn.execute("DROP TRIGGER fail_insert")
    assert store.reserve(100, ORDERS) == "NEW"
    store.close()


BASELINE = {"account_binding": "dedicated", "cash": "1000", "positions": {}, "observed_at_ms": 101}


@pytest.mark.parametrize("orders", [ORDERS, ()])
def test_atomic_baseline_failure_rolls_back_day_and_identities(tmp_path, orders):
    store = journal(tmp_path / "atomic.sqlite")
    store.conn.execute(
        "CREATE TRIGGER fail_baseline BEFORE INSERT ON decision_baselines "
        "BEGIN SELECT RAISE(ABORT, 'injected baseline write failure'); END"
    )
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.reserve(100, orders, baseline=BASELINE)
        for table in ("decisions", "order_ids", "decision_baselines"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        store.conn.execute("DROP TRIGGER fail_baseline")
        assert store.reserve(100, orders, baseline=BASELINE) == "NEW"
        assert store.conn.execute("SELECT COUNT(*) FROM decision_baselines").fetchone()[0] == 1
    finally:
        store.close()


def test_atomic_replay_preserves_original_baseline(tmp_path):
    path = tmp_path / "replay.sqlite"
    store = journal(path)
    store.reserve(100, ORDERS, baseline=BASELINE)
    store.close()
    store = journal(path)
    try:
        assert store.reserve(100, ORDERS, baseline=BASELINE) == "REPLAY_PENDING"
        with pytest.raises(ValueError, match="immutable"):
            store.reserve(100, ORDERS, baseline={**BASELINE, "cash": "999"})
        assert store.baseline_for_order(ORDERS[0]["client_order_id"]) == BASELINE
    finally:
        store.close()


def test_process_exit_before_commit_leaves_no_partial_decision(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "crash.sqlite"
    journal(path).close()
    code = """
import os, sys
from pathlib import Path
from alphaforge.execution.spot_intents import SpotIntentJournal
store = SpotIntentJournal(Path(sys.argv[1]), account_binding="dedicated", epoch="spot-1")
original = store._seal_baseline_in_transaction
def crash_after_sealing(*args, **kwargs):
    original(*args, **kwargs)
    os._exit(73)
store._seal_baseline_in_transaction = crash_after_sealing
store.reserve(100, ({"client_order_id":"afspot-btc"},), baseline={
    "account_binding":"dedicated", "cash":"1000", "positions":{}, "observed_at_ms":101})
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)], timeout=10, capture_output=True
    )
    assert result.returncode == 73, result.stderr.decode()
    store = journal(path)
    try:
        for table in ("decisions", "order_ids", "decision_baselines"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert store.reserve(100, ORDERS, baseline=BASELINE) == "NEW"
    finally:
        store.close()


def test_evidence_is_atomic_immutable_and_not_retroactive(tmp_path):
    store = journal(tmp_path / "evidence.sqlite")
    store.conn.execute(
        "CREATE TRIGGER fail_evidence BEFORE INSERT ON decision_evidence "
        "BEGIN SELECT RAISE(ABORT, 'injected evidence failure'); END"
    )
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.reserve(100, ORDERS, baseline=BASELINE, evidence={"fixture": "original"})
        for table in ("decisions", "order_ids", "decision_baselines", "decision_evidence"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        store.conn.execute("DROP TRIGGER fail_evidence")
        store.reserve(100, ORDERS, baseline=BASELINE, evidence={"fixture": "original"})
        with pytest.raises(ValueError, match="immutable"):
            store.reserve(100, ORDERS, baseline=BASELINE, evidence={"fixture": "altered"})
        assert store.evidence_for_decision(100) == {"fixture": "original"}
        store.conn.execute("UPDATE decision_evidence SET payload='{}'")
        with pytest.raises(ValueError, match="checksum"):
            store.evidence_for_decision(100)
    finally:
        store.close()
    legacy = journal(tmp_path / "legacy-evidence.sqlite")
    try:
        legacy.reserve(100, ORDERS)
        with pytest.raises(ValueError, match="retroactively"):
            legacy.reserve(100, ORDERS, evidence={"fixture": "late"})
    finally:
        legacy.close()
