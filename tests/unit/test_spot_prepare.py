import asyncio
import json
import time
from datetime import UTC, datetime
from decimal import Decimal as D

import httpx
import pytest

from alphaforge.execution.spot_evidence import verify_preparation
from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_paper import PaperCredentials, PaperReader, account_digest
from alphaforge.execution.spot_prepare import prepare_daily_decision
from alphaforge.execution.spot_reconcile import verify_baseline_continuity
from alphaforge.execution.spot_submit import PaperSubmitter
from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS, DailyClose


@pytest.mark.parametrize(
    "fault", [None, "stale", "changed", "missing_asset", "cash_signal", "collected_history"]
)
def test_live_input_preparation_and_daily_replay(tmp_path, fault):
    async def run():
        now = time.time_ns() // 1_000_000
        day = now // DAY_MS * DAY_MS
        calls = []
        reads = 0
        raw_account = {
            "id": "prepare",
            "status": "ACTIVE",
            "currency": "USD",
            "crypto_status": "ACTIVE",
            "account_blocked": False,
            "trading_blocked": False,
            "trade_suspended_by_user": False,
            "cash": "1000",
            "equity": "1000",
            "non_marginable_buying_power": "1000",
        }
        binding = account_digest(raw_account)

        def handle(request):
            nonlocal reads
            calls.append(request)
            assert request.method == "GET"
            if request.url.path.endswith("/bars"):
                return httpx.Response(
                    200,
                    json={
                        "bars": {
                            s: [
                                {
                                    "t": datetime.fromtimestamp(
                                        (bar.end_ms - 3_600_000) / 1000, UTC
                                    )
                                    .isoformat()
                                    .replace("+00:00", "Z"),
                                    "c": str(bar.close),
                                    "v": "0",
                                }
                                for bar in rows
                            ]
                            for s, rows in histories.items()
                        },
                        "next_page_token": None,
                    },
                )
            if request.url.path == "/v2/account":
                reads += 1
                return httpx.Response(
                    200,
                    json={
                        **raw_account,
                        "cash": "999" if fault == "changed" and reads == 3 else "1000",
                    },
                )
            if request.url.path == "/v2/assets":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "symbol": s,
                            "class": "crypto",
                            "status": "active",
                            "tradable": True,
                            "min_order_size": "0.001",
                            "min_trade_increment": "0.001",
                            "price_increment": "0.01",
                        }
                        for s in (SYMBOLS[:1] if fault == "missing_asset" else SYMBOLS)
                    ],
                )
            if request.url.path.endswith("/latest/orderbooks"):
                stamp = datetime.fromtimestamp(time.time() - (3 if fault == "stale" else 0.05), UTC)
                return httpx.Response(
                    200,
                    json={
                        "orderbooks": {
                            s: {
                                "t": stamp.isoformat().replace("+00:00", "Z"),
                                "b": [{"p": "99.99", "s": "100"}],
                                "a": [{"p": "100", "s": "100"}],
                            }
                            for s in SYMBOLS
                        }
                    },
                )
            return httpx.Response(200, json=[])

        histories = {
            s: tuple(
                DailyClose(day - (199 - i) * DAY_MS, D(100 if fault == "cash_signal" else 100 + i))
                for i in range(200)
            )
            for s in SYMBOLS
        }
        client = PaperReader(
            PaperCredentials("fixture", "fixture"), transport=httpx.MockTransport(handle)
        )
        store = SpotIntentJournal(
            tmp_path / "prepare.sqlite", account_binding=binding, epoch="prepare"
        )
        try:
            if fault in {"stale", "changed", "missing_asset"}:
                with pytest.raises(ValueError):
                    await prepare_daily_decision(client, store, histories=histories)
                assert store.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
            else:
                result = await prepare_daily_decision(
                    client,
                    store,
                    histories=None if fault == "collected_history" else histories,
                    history_receipt_path=tmp_path / "history.json",
                )
                if fault == "collected_history":
                    assert result["authenticated_history_receipt"]["sha256"]
                    assert (tmp_path / "history.json").exists()
                    verified = verify_preparation(store, decision_ms=day)
                    assert verified["orders_checked"] == 2
                    assert verified["submission_authorized"] is False
                    receipt_path = tmp_path / "history.json"
                    original = receipt_path.read_bytes()
                    receipt_path.write_bytes(original + b" ")
                    with pytest.raises(ValueError, match="checksum"):
                        verify_preparation(store, decision_ms=day)

                    async def readiness(_):
                        pass

                    submitter = PaperSubmitter(
                        PaperCredentials("fixture", "fixture"),
                        account_binding=binding,
                        epoch="prepare",
                        enabled=True,
                        readiness_check=readiness,
                        transport=httpx.MockTransport(
                            lambda _: pytest.fail("network before evidence")
                        ),
                    )
                    try:
                        with pytest.raises(ValueError, match="checksum"):
                            await submitter.submit(
                                store,
                                result["orders"][0],
                                valid_until_ms=time.time_ns() // 1_000_000 + 5000,
                            )
                        assert (
                            store.conn.execute(
                                "SELECT COUNT(*) FROM submission_attempts"
                            ).fetchone()[0]
                            == 0
                        )
                    finally:
                        await submitter.close()
                    receipt_path.write_bytes(original)
                    assert verify_preparation(store, decision_ms=day)["orders_checked"] == 2
                    sent = []

                    def broker(request):
                        if request.method == "GET":
                            return handle(request)
                        sent.append(json.loads(request.content))
                        return httpx.Response(
                            201,
                            json={
                                **sent[-1],
                                "id": "prepared-broker-id",
                                "asset_class": "crypto",
                                "status": "new",
                                "filled_qty": "0",
                                "filled_avg_price": None,
                            },
                        )

                    submitter = PaperSubmitter(
                        PaperCredentials("fixture", "fixture"),
                        account_binding=binding,
                        epoch="prepare",
                        enabled=True,
                        readiness_check=readiness,
                        transport=httpx.MockTransport(broker),
                    )
                    try:
                        outcome = await submitter.submit(
                            store,
                            result["orders"][0],
                            valid_until_ms=time.time_ns() // 1_000_000 + 5000,
                        )
                        assert outcome["status"] == "ACKNOWLEDGED_NOT_SETTLED"
                        assert sent == [result["orders"][0]]
                    finally:
                        await submitter.close()
                else:
                    with pytest.raises(ValueError, match="injected history"):
                        verify_preparation(store, decision_ms=day)
                assert result["submission_authorized"] is False
                assert len(result["orders"]) == (0 if fault == "cash_signal" else 2)
                assert (
                    store.conn.execute("SELECT COUNT(*) FROM decision_baselines").fetchone()[0] == 1
                )
                count = len(calls)
                replay = await prepare_daily_decision(client, store, histories={})
                assert replay["status"].startswith("REPLAY_")
                assert len(calls) == count
                if fault == "cash_signal":
                    with pytest.raises(ValueError, match="account changed"):
                        verify_baseline_continuity(
                            store,
                            decision_ms=day + DAY_MS,
                            payload={"account_binding": binding, "cash": "1001", "positions": {}},
                        )
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


@pytest.fixture(autouse=True)
def synthetic_host_clock_boundary(monkeypatch):
    # Broker and strategy tests must not depend on the developer host's time.
    async def check():
        return {"status": "SYNTHETIC_CLOCK_FIXTURE"}

    monkeypatch.setattr("alphaforge.execution.spot_submit.check_host_clock", check)
