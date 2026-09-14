import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from alphaforge.execution.spot_intents import SpotIntentJournal


def store(path):
    return SpotIntentJournal(path, account_binding="dedicated", epoch="new-spot")


def orders():
    return tuple(
        {
            "client_order_id": "afspot-" + s.split("/")[0],
            "symbol": s,
            "qty": "1",
            "side": "buy",
            "type": "limit",
            "time_in_force": "ioc",
            "limit_price": "100",
        }
        for s in ("BTC/USD", "ETH/USD")
    )


def ack(order):
    return {
        **order,
        "id": "broker-" + order["symbol"],
        "asset_class": "crypto",
        "status": "new",
        "filled_qty": "0",
        "filled_avg_price": None,
    }


def test_crash_before_or_after_network_is_never_permission_to_resend(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = store(path)
    batch = orders()
    journal.reserve(100, batch)
    assert journal.claim_submission(batch[0], now_ms=101) == "CLAIMED_NOT_RUNTIME_CLEARANCE"
    journal.close()
    journal = store(path)
    assert journal.claim_submission(batch[0], now_ms=102) == "ALREADY_ATTEMPTED_NEVER_RESEND"
    with pytest.raises(ValueError, match="uncertain"):
        journal.claim_submission(batch[1], now_ms=102)
    with pytest.raises(ValueError, match="uncertain"):
        journal.reserve(200, ())
    journal.close()


def test_one_competing_connection_can_claim_order(tmp_path):
    path = tmp_path / "journal.sqlite"
    batch = orders()
    journal = store(path)
    journal.reserve(100, batch)
    journal.close()

    def claim(_):
        connection = store(path)
        try:
            return connection.claim_submission(batch[0], now_ms=101)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(claim, range(4)))
    assert outcomes.count("CLAIMED_NOT_RUNTIME_CLEARANCE") == 1
    assert outcomes.count("ALREADY_ATTEMPTED_NEVER_RESEND") == 3


def test_ack_is_immutable_and_does_not_clear_decision(tmp_path):
    journal = store(tmp_path / "journal.sqlite")
    batch = orders()
    journal.reserve(100, batch)
    journal.claim_submission(batch[0], now_ms=101)
    response = ack(batch[0])
    journal.record_acknowledgement(batch[0]["client_order_id"], response)
    journal.record_acknowledgement(batch[0]["client_order_id"], response)
    with pytest.raises(ValueError, match="immutable"):
        journal.record_acknowledgement(
            batch[0]["client_order_id"], {**response, "status": "canceled"}
        )
    assert journal.claim_submission(batch[1], now_ms=102) == "CLAIMED_NOT_RUNTIME_CLEARANCE"
    assert journal.conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
    journal.close()


def test_bad_ack_and_changed_order_cannot_release_uncertainty(tmp_path):
    journal = store(tmp_path / "journal.sqlite")
    batch = orders()
    journal.reserve(100, batch)
    with pytest.raises(ValueError, match="reservation"):
        journal.claim_submission({**batch[0], "qty": "2"}, now_ms=101)
    journal.claim_submission(batch[0], now_ms=101)
    for response in ({**ack(batch[0]), "qty": "2"}, {**ack(batch[0]), "status": "unknown"}):
        with pytest.raises(ValueError):
            journal.record_acknowledgement(batch[0]["client_order_id"], response)
    assert (
        journal.conn.execute("SELECT acknowledgement FROM submission_attempts").fetchone()[0]
        is None
    )
    journal.close()


def test_failed_durable_claim_cannot_be_treated_as_sent(tmp_path):
    journal = store(tmp_path / "journal.sqlite")
    batch = orders()
    journal.reserve(100, batch)
    journal.conn.execute(
        "CREATE TRIGGER fail BEFORE INSERT ON submission_attempts "
        "BEGIN SELECT RAISE(ABORT,'write failed'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        journal.claim_submission(batch[0], now_ms=101)
    assert journal.conn.execute("SELECT COUNT(*) FROM submission_attempts").fetchone()[0] == 0
    journal.close()
