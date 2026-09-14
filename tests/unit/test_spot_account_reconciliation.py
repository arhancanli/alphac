import asyncio

import httpx
import pytest

from alphaforge.execution.spot_account import observe_quiescent_account
from alphaforge.execution.spot_intents import SpotIntentJournal
from alphaforge.execution.spot_paper import PaperCredentials, PaperReader, account_digest
from alphaforge.execution.spot_reconcile import balance_payload, capture_baseline, settle_decision
from alphaforge.execution.spot_settlement import Balance

DECISION = 1_704_067_200_000
BINDING = account_digest({"id": "dedicated"})
ORDER = {
    "client_order_id": "afspot-test",
    "symbol": "BTC/USD",
    "side": "buy",
    "qty": "1",
    "limit_price": "100",
    "type": "limit",
    "time_in_force": "ioc",
}


def journal(path):
    return SpotIntentJournal(path, account_binding=BINDING, epoch="new-spot")


def baseline():
    return {
        "account_binding": BINDING,
        "cash": "1000",
        "positions": {},
        "observed_at_ms": DECISION + 1,
    }


def reader(*, missing_fee=False, changed_balance=False):
    counts = {"account": 0}

    def handle(request):
        assert request.method == "GET"
        if request.url.path == "/v2/account":
            counts["account"] += 1
            return httpx.Response(
                200,
                json={
                    "id": "dedicated",
                    "currency": "USD",
                    "status": "ACTIVE",
                    "crypto_status": "ACTIVE",
                    "account_blocked": False,
                    "trading_blocked": False,
                    "trade_suspended_by_user": False,
                    "cash": "901" if changed_balance and counts["account"] >= 5 else "900",
                    "non_marginable_buying_power": "900",
                    "equity": str(1000 + counts["account"]),
                },
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "BTCUSD",
                        "asset_class": "crypto",
                        "side": "long",
                        "qty": "0.9975",
                        "qty_available": "0.9975",
                    }
                ],
            )
        if request.url.path == "/v2/orders":
            return httpx.Response(200, json=[])
        if request.url.path == "/v2/orders:by_client_order_id":
            return httpx.Response(
                200,
                json={
                    **ORDER,
                    "id": "broker",
                    "asset_class": "crypto",
                    "status": "filled",
                    "filled_qty": "1",
                    "filled_avg_price": "100",
                },
            )
        if "page_token" in request.url.params:
            return httpx.Response(200, json=[])
        rows = [
            {
                "id": "fill",
                "activity_type": "FILL",
                "type": "fill",
                "order_id": "broker",
                "symbol": "BTCUSD",
                "side": "buy",
                "qty": "1",
                "price": "100",
            }
        ]
        if not missing_fee:
            rows.append(
                {
                    "id": "fee",
                    "activity_type": "CFEE",
                    "symbol": "BTCUSD",
                    "qty": "-0.0025",
                    "net_amount": "0",
                    "status": "executed",
                }
            )
        return httpx.Response(200, json=rows)

    return PaperReader(
        PaperCredentials("fixture", "fixture"), transport=httpx.MockTransport(handle)
    )


def test_baseline_is_immutable_and_cannot_be_created_after_attempt(tmp_path):
    store = journal(tmp_path / "sealed.sqlite")
    store.reserve(DECISION, (ORDER,))
    store.seal_baseline(DECISION, baseline())
    store.seal_baseline(DECISION, baseline())
    with pytest.raises(ValueError, match="immutable"):
        store.seal_baseline(DECISION, {**baseline(), "cash": "900"})
    store.close()
    store = journal(tmp_path / "late.sqlite")
    store.reserve(DECISION, (ORDER,))
    store.claim_submission(ORDER, now_ms=DECISION + 2)
    with pytest.raises(ValueError, match="after a submission"):
        store.seal_baseline(DECISION, baseline())
    store.close()


def test_repeated_account_reads_ignore_only_mark_to_market_equity():
    async def run():
        client = reader()
        try:
            observation = await observe_quiescent_account(client, expected_binding=BINDING)
            assert str(observation.balance.cash) == "900"
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("fault", [None, "missing_fee", "changed_balance"])
def test_reader_to_settlement_to_journal_integration(tmp_path, fault):
    async def run():
        store = journal(tmp_path / "journal.sqlite")
        store.reserve(DECISION, (ORDER,))
        store.seal_baseline(DECISION, baseline())
        store.claim_submission(ORDER, now_ms=DECISION + 2)
        client = reader(
            missing_fee=fault == "missing_fee", changed_balance=fault == "changed_balance"
        )
        try:
            if fault:
                with pytest.raises(ValueError):
                    await settle_decision(
                        client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
                    )
                assert store.conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
            else:
                result = await settle_decision(
                    client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
                )
                assert result["status"] == "SETTLEMENT_RECORDED"
                again = await settle_decision(
                    client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
                )
                assert again == {"status": "ALREADY_RECORDED", "network_requests": 0}
                store.reserve(DECISION + 86_400_000, ({**ORDER, "client_order_id": "afspot-next"},))
                await capture_baseline(client, store, decision_ms=DECISION + 86_400_000)
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_late_balance_correction_cannot_be_reset_as_new_baseline(tmp_path):
    async def run():
        store = journal(tmp_path / "journal.sqlite")
        store.reserve(DECISION, (ORDER,))
        store.seal_baseline(DECISION, baseline())
        store.claim_submission(ORDER, now_ms=DECISION + 2)
        client = reader()
        try:
            await settle_decision(client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z")
            store.reserve(DECISION + 86_400_000, ({**ORDER, "client_order_id": "next"},))
            other = reader(changed_balance=True)
            try:
                # Advance account-read fixture to its stable corrected balance.
                for _ in range(5):
                    await other.get("/v2/account")
                with pytest.raises(ValueError, match="changed since last settlement"):
                    await capture_baseline(other, store, decision_ms=DECISION + 86_400_000)
            finally:
                await other.close()
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_decimal_formatting_does_not_create_false_balance_corrections():
    from decimal import Decimal as D

    assert balance_payload(Balance(BINDING, D("900.00"), {"BTC/USD": D("0.997500")})) == {
        "account_binding": BINDING,
        "cash": "900",
        "positions": {"BTC/USD": "0.9975"},
    }


def test_partly_submitted_batch_reconciles_only_attempted_order(tmp_path):
    async def run():
        store = journal(tmp_path / "partial.sqlite")
        unsent = {**ORDER, "client_order_id": "never-sent", "symbol": "ETH/USD"}
        store.reserve(DECISION, (ORDER, unsent))
        store.seal_baseline(DECISION, baseline())
        store.claim_submission(ORDER, now_ms=DECISION + 2)
        client = reader()
        try:
            result = await settle_decision(
                client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
            )
            assert result["orders_checked"] == 1
            assert result["abandoned_unattempted_ids"] == ["never-sent"]
            with pytest.raises(ValueError, match="permanently stopped"):
                store.claim_submission(unsent, now_ms=DECISION + 3)
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_stop_survives_reopen_and_blocks_other_connection(tmp_path):
    path = tmp_path / "concurrent.sqlite"
    first, second = journal(path), journal(path)
    first.reserve(DECISION, (ORDER,))
    assert first.stop_submissions(DECISION) == ()
    with pytest.raises(ValueError, match="permanently stopped"):
        second.claim_submission(ORDER, now_ms=DECISION + 2)
    first.close()
    second.close()
    reopened = journal(path)
    assert reopened.stop_submissions(DECISION) == ()
    with pytest.raises(ValueError, match="permanently stopped"):
        reopened.claim_submission(ORDER, now_ms=DECISION + 3)
    reopened.close()


@pytest.mark.parametrize("balance_changed", [False, True])
def test_entirely_unsent_batch_requires_unchanged_account(tmp_path, balance_changed):
    async def run():
        store = journal(tmp_path / "unsent.sqlite")
        store.reserve(DECISION, (ORDER,))
        sealed = {
            **baseline(),
            "cash": "901" if balance_changed else "900",
            "positions": {"BTC/USD": "0.9975"},
        }
        store.seal_baseline(DECISION, sealed)
        client = reader()

        async def empty_scan(**kwargs):
            return {"records": [], "pagination_exhausted": True}

        client.read_activities = empty_scan
        try:
            if balance_changed:
                with pytest.raises(ValueError, match="unexplained balance"):
                    await settle_decision(
                        client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
                    )
                assert store.conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
            else:
                result = await settle_decision(
                    client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
                )
                assert result["orders_checked"] == 0
                assert result["abandoned_unattempted_ids"] == [ORDER["client_order_id"]]
            with pytest.raises(ValueError, match="permanently stopped"):
                store.claim_submission(ORDER, now_ms=DECISION + 3)
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


def test_failed_partial_reconciliation_keeps_attempt_and_freezes_unsent(tmp_path):
    async def run():
        store = journal(tmp_path / "uncertain.sqlite")
        unsent = {**ORDER, "client_order_id": "unsent"}
        store.reserve(DECISION, (ORDER, unsent))
        store.seal_baseline(DECISION, baseline())
        store.claim_submission(ORDER, now_ms=DECISION + 2)
        client = reader(missing_fee=True)
        try:
            with pytest.raises(ValueError):
                await settle_decision(
                    client, store, decision_ms=DECISION, until="2024-01-03T00:00:00Z"
                )
            assert store.conn.execute("SELECT state FROM decisions").fetchone()[0] == "pending"
            assert (
                store.claim_submission(ORDER, now_ms=DECISION + 3)
                == "ALREADY_ATTEMPTED_NEVER_RESEND"
            )
            with pytest.raises(ValueError, match="permanently stopped"):
                store.claim_submission(unsent, now_ms=DECISION + 3)
            with pytest.raises(ValueError, match="prior uncertain"):
                store.reserve(DECISION + 86_400_000, ())
        finally:
            await client.close()
            store.close()

    asyncio.run(run())
