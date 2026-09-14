import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from alphaforge.execution.spot_driver import dispatch_decision
from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_paper import PaperCredentials, account_digest
from alphaforge.execution.spot_reconcile import settle_decision
from alphaforge.execution.spot_submit import PaperSubmitter, SubmissionBlocked

ACCOUNT = {
    "id": "dedicated-driver",
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
BINDING = account_digest(ACCOUNT)
ORDERS = tuple(
    {
        "client_order_id": f"driver-{symbol}",
        "symbol": f"{symbol}/USD",
        "side": "buy",
        "type": "limit",
        "time_in_force": "ioc",
        "qty": "1",
        "limit_price": "100",
    }
    for symbol in ("BTC", "ETH")
)


async def synthetic_readiness(order):
    pass


@pytest.mark.parametrize("mode", ["ok", "timeout", "cancel", "not_found"])
def test_dispatch_then_reopen_and_reconcile(tmp_path, mode):
    async def run():
        posts, broker = [], {}

        def handle(request):
            if request.method == "POST":
                order = json.loads(request.content)
                posts.append(order)
                raw = {
                    **order,
                    "id": order["client_order_id"] + "-broker",
                    "asset_class": "crypto",
                    "status": "expired",
                    "filled_qty": "0",
                    "filled_avg_price": None,
                }
                if mode != "not_found":
                    broker[order["client_order_id"]] = raw
                if mode == "cancel":
                    raise asyncio.CancelledError()
                if mode in {"timeout", "not_found"}:
                    raise httpx.ReadTimeout("synthetic", request=request)
                return httpx.Response(201, json=raw)
            if request.url.path == "/v2/account":
                return httpx.Response(200, json=ACCOUNT)
            if request.url.path == "/v2/orders:by_client_order_id":
                raw = broker.get(request.url.params["client_order_id"])
                return httpx.Response(200 if raw else 404, json=raw or {})
            return httpx.Response(200, json=[])

        path = tmp_path / "driver.sqlite"
        store = SpotIntentJournal(path, account_binding=BINDING, epoch="driver")
        decision = time.time_ns() // 1_000_000 - 1000
        store.reserve(decision, ORDERS)
        client = PaperSubmitter(
            PaperCredentials("fixture", "fixture"),
            account_binding=BINDING,
            epoch="driver",
            enabled=True,
            readiness_check=synthetic_readiness,
            transport=httpx.MockTransport(handle),
        )
        try:
            if mode == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await dispatch_decision(
                        client,
                        store,
                        decision_ms=decision,
                        valid_until_ms=time.time_ns() // 1_000_000 + 5000,
                    )
            else:
                result = await dispatch_decision(
                    client,
                    store,
                    decision_ms=decision,
                    valid_until_ms=time.time_ns() // 1_000_000 + 5000,
                )
                assert result["journal_clearance"] is False
            assert len(posts) == (2 if mode == "ok" else 1)
            store.close()
            store = SpotIntentJournal(path, account_binding=BINDING, epoch="driver")
            with pytest.raises(ValueError, match="already dispatched or stopped"):
                await dispatch_decision(
                    client,
                    store,
                    decision_ms=decision,
                    valid_until_ms=time.time_ns() // 1_000_000 + 5000,
                )
            until = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

            # Inject a fixed activity receipt because today's creation window has
            # not elapsed in this instantaneous simulation. No fee/fill activity.
            async def activities(**kwargs):
                return {"records": [], "pagination_exhausted": True}

            client.reader.read_activities = activities
            if mode == "not_found":
                with pytest.raises(ValueError):
                    await settle_decision(client.reader, store, decision_ms=decision, until=until)
                assert store.conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
            else:
                result = await settle_decision(
                    client.reader, store, decision_ms=decision, until=until
                )
                assert result["orders_checked"] == len(posts)
                assert len(result["abandoned_unattempted_ids"]) == 2 - len(posts)
            assert len(posts) == (2 if mode == "ok" else 1)
        finally:
            store.close()
            await client.close()

    asyncio.run(run())


def test_disabled_driver_does_not_consume_reservation(tmp_path):
    async def run():
        store = SpotIntentJournal(tmp_path / "disabled.sqlite", account_binding=BINDING, epoch="x")
        store.reserve(1, ORDERS)
        client = PaperSubmitter(
            PaperCredentials("fixture", "fixture"),
            account_binding=BINDING,
            epoch="x",
            transport=httpx.MockTransport(lambda _: pytest.fail("network")),
        )
        try:
            with pytest.raises(SubmissionBlocked, match="activation"):
                await dispatch_decision(client, store, decision_ms=1, valid_until_ms=1)
            assert store.conn.execute("SELECT COUNT(*) FROM dispatch_starts").fetchone()[0] == 0
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_durable_start_excludes_second_driver_after_crash(tmp_path):
    path = tmp_path / "crash.sqlite"
    store = SpotIntentJournal(path, account_binding=BINDING, epoch="x")
    store.reserve(1, ORDERS)
    assert store.begin_dispatch(1) == ORDERS
    store.close()
    store = SpotIntentJournal(path, account_binding=BINDING, epoch="x")
    try:
        with pytest.raises(ValueError, match="already dispatched"):
            store.begin_dispatch(1)
        assert store.conn.execute("SELECT COUNT(*) FROM submission_attempts").fetchone()[0] == 0
    finally:
        store.close()


def test_expired_baseline_capture_stops_without_post(tmp_path, monkeypatch):
    async def run():
        async def slow_capture(*args, **kwargs):
            await asyncio.sleep(1)

        monkeypatch.setattr("alphaforge.execution.spot_driver.capture_baseline", slow_capture)
        store = SpotIntentJournal(tmp_path / "slow.sqlite", account_binding=BINDING, epoch="x")
        store.reserve(1, ORDERS)
        client = PaperSubmitter(
            PaperCredentials("fixture", "fixture"),
            account_binding=BINDING,
            epoch="x",
            enabled=True,
            readiness_check=synthetic_readiness,
            transport=httpx.MockTransport(lambda _: pytest.fail("network")),
        )
        try:
            with pytest.raises(SubmissionBlocked, match="baseline capture exceeded"):
                await dispatch_decision(
                    client, store, decision_ms=1, valid_until_ms=time.time_ns() // 1_000_000 + 100
                )
            assert store.conn.execute("SELECT COUNT(*) FROM submission_attempts").fetchone()[0] == 0
            assert store.conn.execute("SELECT COUNT(*) FROM submission_stops").fetchone()[0] == 1
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


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
