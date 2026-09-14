import asyncio
import json
import time

import httpx
import pytest

from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_paper import PaperCredentials, account_digest
from alphaforge.execution.spot_submit import PaperSubmitter, SubmissionBlocked


def intent():
    return {
        "client_order_id": "afspot-fixture",
        "symbol": "BTC/USD",
        "side": "buy",
        "qty": "1",
        "type": "limit",
        "time_in_force": "ioc",
        "limit_price": "100",
    }


def account():
    return {
        "id": "dedicated",
        "status": "ACTIVE",
        "currency": "USD",
        "crypto_status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
        "cash": "1000",
        "equity": "1000",
        "non_marginable_buying_power": "1000",
    }


async def readiness(_):
    # Synthetic provider; this is not installed in production.
    return None


def exercise(tmp_path, *, mode="ok", enabled=True, change=None, readiness_provider=readiness):
    raw_account = {**account(), **(change or {})}
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "paper-api.alpaca.markets"
        if request.method == "GET":
            return httpx.Response(200, json=raw_account)
        assert request.method == "POST" and request.url.path == "/v2/orders"
        if mode == "timeout":
            raise httpx.ReadTimeout("fixture-secret", request=request)
        if mode == "cancel":
            raise asyncio.CancelledError()
        if mode in ("redirect", "rejected", "server_error"):
            return httpx.Response(
                {"redirect": 302, "rejected": 422, "server_error": 500}[mode],
                headers={"location": "https://example.invalid"},
            )
        body = {
            **json.loads(request.content),
            "id": "broker-id",
            "asset_class": "crypto",
            "status": "new",
            "filled_qty": "0",
            "filled_avg_price": None,
        }
        if mode == "mismatch":
            body["qty"] = "2"
        return httpx.Response(201, json=body)

    binding = account_digest(account())
    path = tmp_path / "journal.sqlite"

    async def run():
        journal = SpotIntentJournal(path, account_binding=binding, epoch="new-spot")
        decision_ms = time.time_ns() // 1_000_000 - 1000
        journal.reserve(decision_ms, (intent(),))
        journal.seal_baseline(
            decision_ms,
            {
                "account_binding": binding,
                "cash": "1000",
                "positions": {},
                "observed_at_ms": decision_ms + 1,
            },
        )
        client = PaperSubmitter(
            PaperCredentials("fixture", "fixture-secret"),
            account_binding=binding,
            epoch="new-spot",
            enabled=enabled,
            readiness_check=readiness_provider,
            transport=httpx.MockTransport(handler),
        )
        try:
            if mode == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await client.submit(
                        journal, intent(), valid_until_ms=time.time_ns() // 1_000_000 + 5000
                    )
                result = {"status": "CANCELED"}
            else:
                result = await client.submit(
                    journal, intent(), valid_until_ms=time.time_ns() // 1_000_000 + 5000
                )
            journal.close()
            journal = SpotIntentJournal(path, account_binding=binding, epoch="new-spot")
            replay = await client.submit(
                journal, intent(), valid_until_ms=time.time_ns() // 1_000_000 + 5000
            )
            assert replay["status"] == "ALREADY_ATTEMPTED_RECONCILE"
            assert journal.conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
            return result
        finally:
            journal.close()
            await client.close()

    return asyncio.run(run()), calls


def test_acknowledged_order_is_sent_once_and_remains_unsettled(tmp_path):
    result, calls = exercise(tmp_path)
    assert result["status"] == "ACKNOWLEDGED_NOT_SETTLED"
    assert sum(r.method == "POST" for r in calls) == 1


@pytest.mark.parametrize(
    "mode", ["timeout", "redirect", "rejected", "server_error", "mismatch", "cancel"]
)
def test_uncertain_submission_is_never_retried_even_after_restart(tmp_path, mode):
    result, calls = exercise(tmp_path, mode=mode)
    assert result["status"] != "ACKNOWLEDGED_NOT_SETTLED"
    assert "fixture-secret" not in str(result)
    assert sum(r.method == "POST" for r in calls) == 1


def test_default_disabled_prevents_requests(tmp_path):
    with pytest.raises(SubmissionBlocked, match="activation"):
        exercise(tmp_path, enabled=False)


@pytest.mark.parametrize("change", [{"cash": "1"}, {"id": "other-sleeve"}])
def test_account_binding_and_cash_rechecked_before_claim(tmp_path, change):
    with pytest.raises(SubmissionBlocked):
        exercise(tmp_path, change=change)
    import sqlite3

    with sqlite3.connect(tmp_path / "journal.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM submission_attempts").fetchone()[0] == 0


def test_changed_readiness_payload_blocks_before_claim(tmp_path):
    async def mutate(order):
        order["qty"] = "2"

    with pytest.raises(SubmissionBlocked, match="altered"):
        exercise(tmp_path, readiness_provider=mutate)


def test_wall_clock_step_cannot_extend_submission_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import alphaforge.execution.spot_submit as module

    real_wall, real_mono = time.time_ns, time.monotonic_ns
    offset = [0]
    fake_time = SimpleNamespace(time_ns=lambda: real_wall() + offset[0], monotonic_ns=real_mono)
    monkeypatch.setattr(module, "time", fake_time)

    async def step_clock(_):
        offset[0] = -1_000_000_000

    with pytest.raises(SubmissionBlocked, match="clock discontinuity"):
        exercise(tmp_path, readiness_provider=step_clock)


@pytest.mark.parametrize("available,should_send", [("1", True), ("0.99", False)])
def test_exit_uses_available_position_even_with_no_buying_power(tmp_path, available, should_send):
    order = {**intent(), "side": "sell"}
    posts = []

    def handler(request):
        if request.url.path == "/v2/account":
            return httpx.Response(
                200, json={**account(), "cash": "0", "non_marginable_buying_power": "0"}
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "BTCUSD",
                        "asset_class": "crypto",
                        "side": "long",
                        "qty_available": available,
                    }
                ],
            )
        posts.append(request)
        return httpx.Response(
            200,
            json={
                **order,
                "id": "sell-order",
                "asset_class": "crypto",
                "status": "new",
                "filled_qty": "0",
                "filled_avg_price": None,
            },
        )

    async def run():
        binding = account_digest(account())
        journal = SpotIntentJournal(
            tmp_path / "sell.sqlite", account_binding=binding, epoch="new-spot"
        )
        decision_ms = time.time_ns() // 1_000_000 - 1000
        journal.reserve(decision_ms, (order,))
        journal.seal_baseline(
            decision_ms,
            {
                "account_binding": binding,
                "cash": "0",
                "positions": {"BTC/USD": "1"},
                "observed_at_ms": decision_ms + 1,
            },
        )
        client = PaperSubmitter(
            PaperCredentials("fixture", "fixture"),
            account_binding=binding,
            epoch="new-spot",
            enabled=True,
            readiness_check=readiness,
            transport=httpx.MockTransport(handler),
        )
        try:
            if should_send:
                assert (
                    await client.submit(
                        journal, order, valid_until_ms=time.time_ns() // 1_000_000 + 5000
                    )
                )["status"] == "ACKNOWLEDGED_NOT_SETTLED"
            else:
                with pytest.raises(SubmissionBlocked, match="available spot position"):
                    await client.submit(
                        journal, order, valid_until_ms=time.time_ns() // 1_000_000 + 5000
                    )
        finally:
            journal.close()
            await client.close()

    asyncio.run(run())
    assert len(posts) == int(should_send)


@pytest.fixture(autouse=True)
def synthetic_evidence_boundary(monkeypatch):
    # These transport/driver fixtures use arbitrary orders rather than strategy
    # plans. Real evidence reconstruction is exercised by preparation integration.
    monkeypatch.setattr(
        "alphaforge.execution.spot_submit.verify_preparation",
        lambda *args, **kwargs: {"submission_authorized": False},
    )


@pytest.fixture(autouse=True)
def synthetic_current_risk_boundary(monkeypatch):
    # Transport-only fixtures isolate the authenticated risk collector.
    async def check(*args, **kwargs):
        return None

    monkeypatch.setattr("alphaforge.execution.spot_submit.check_current_risk", check)


@pytest.fixture(autouse=True)
def synthetic_host_clock_boundary(monkeypatch):
    # Broker and strategy tests must not depend on the developer host's time.
    async def check():
        return {"status": "SYNTHETIC_CLOCK_FIXTURE"}

    monkeypatch.setattr("alphaforge.execution.spot_submit.check_host_clock", check)


def test_clock_failure_prevents_durable_submission_claim(tmp_path, monkeypatch):
    import sqlite3

    from alphaforge.execution.spot_clock import ClockBlocked

    async def reject():
        raise ClockBlocked("clock offset or uncertainty exceeds paper limits")

    monkeypatch.setattr("alphaforge.execution.spot_submit.check_host_clock", reject)
    with pytest.raises(ClockBlocked):
        exercise(tmp_path)
    with sqlite3.connect(tmp_path / "journal.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM submission_attempts").fetchone()[0] == 0
        assert conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
