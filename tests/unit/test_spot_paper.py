import asyncio

import httpx
import pytest

from alphaforge.execution.spot_paper import (
    PAPER_ORIGIN,
    PaperCredentials,
    PaperReader,
    PaperReadError,
    account_digest,
    assess_order,
)


def account():
    return {
        "id": "fixture-account",
        "status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "currency": "USD",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
        "equity": "10000",
        "cash": "10000",
        "non_marginable_buying_power": "10000",
    }


def responses():
    return {
        "/v2/account": account(),
        "/v2/positions": [],
        "/v2/orders": [],
        "/v2/assets": [
            {
                "symbol": s,
                "class": "crypto",
                "tradable": True,
                "status": "active",
                "min_order_size": "0.0001",
                "min_trade_increment": "0.0001",
                "price_increment": "0.01",
            }
            for s in ("BTC/USD", "ETH/USD")
        ],
    }


def run_preflight(data, *, excluded=None):
    calls = []

    def handler(request):
        assert request.method == "GET" and str(request.url).startswith(PAPER_ORIGIN + "/")
        calls.append(request.url.path)
        return httpx.Response(200, json=data[request.url.path])

    async def run():
        reader = PaperReader(
            PaperCredentials("fixture-key", "fixture-secret"),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await reader.fresh_account_preflight(excluded_account_bindings=excluded or set())
        finally:
            await reader.close()

    return asyncio.run(run()), calls


def test_preflight_is_read_only_and_never_runtime_clearance():
    report, calls = run_preflight(responses())
    assert len(calls) == 4
    assert report["account_binding"] == account_digest(account())
    assert report["runtime_clearance"] is False
    assert report["dedication_verified"] is False
    assert "fixture-account" not in str(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "ACCOUNT_UPDATED"),
        ("crypto_status", None),
        ("trading_blocked", True),
        ("account_blocked", None),
        ("cash", "NaN"),
        ("non_marginable_buying_power", "0"),
    ],
)
def test_restricted_or_unknown_account_blocks(field, value):
    data = responses()
    data["/v2/account"][field] = value
    with pytest.raises(PaperReadError):
        run_preflight(data)


def test_other_sleeve_and_nonempty_accounts_block():
    with pytest.raises(PaperReadError, match="another sleeve"):
        run_preflight(responses(), excluded={account_digest(account())})
    for path in ("/v2/orders", "/v2/positions"):
        data = responses()
        data[path] = [{}]
        with pytest.raises(PaperReadError, match="empty"):
            run_preflight(data)


@pytest.mark.parametrize("mode", ["redirect", "oversize", "timeout", "bad_json", "not_found"])
def test_transport_errors_are_bounded_sanitized_and_never_retried(mode):
    calls = []

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("fixture-secret", request=request)
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "https://evil.example"})
        if mode == "oversize":
            return httpx.Response(200, content=b"x" * 1_048_577)
        if mode == "not_found":
            return httpx.Response(404, text="fixture-secret")
        return httpx.Response(200, text="fixture-secret")

    async def run():
        reader = PaperReader(
            PaperCredentials("fixture-key", "fixture-secret"),
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(PaperReadError) as error:
                await reader.get("/v2/account")
            assert "fixture-secret" not in str(error.value)
            with pytest.raises(PaperReadError, match="unapproved"):
                await reader.get("https://evil.example")
        finally:
            await reader.close()

    asyncio.run(run())
    assert len(calls) == 1


def test_credentials_never_fall_back_to_live_or_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_BASE_URL", PAPER_ORIGIN)
    path = tmp_path / "dedicated.env"
    with pytest.raises(PaperReadError):
        PaperCredentials.from_file(path)
    text = "APCA_API_KEY_ID=fixture-key\nAPCA_API_SECRET_KEY=fixture-secret\n"
    for suffix in (
        "",
        "APCA_API_BASE_URL=https://api.alpaca.markets\n",
        "APCA_API_BASE_URL=" + PAPER_ORIGIN + "\nAPCA_API_KEY_ID=duplicate\n",
    ):
        path.write_text(text + suffix)
        with pytest.raises(PaperReadError):
            PaperCredentials.from_file(path)
    path.write_text(text + "APCA_API_BASE_URL=" + PAPER_ORIGIN + "\n")
    credentials = PaperCredentials.from_file(path)
    assert "fixture-secret" not in repr(credentials)


def order():
    intent = {
        "client_order_id": "afspot-test",
        "symbol": "BTC/USD",
        "side": "buy",
        "type": "limit",
        "time_in_force": "ioc",
        "qty": "1",
        "limit_price": "100",
    }
    raw = {
        **intent,
        "id": "broker-id",
        "asset_class": "crypto",
        "status": "canceled",
        "filled_qty": "0.25",
        "filled_avg_price": "99",
    }
    return intent, raw


def test_partial_cancel_still_requires_base_fee_and_position_reconciliation():
    intent, raw = order()
    report = assess_order(intent, raw)
    assert report["execution_terminal"] is True
    assert report["filled_qty"] == "0.25"
    assert report["fee_and_balance_reconciliation_required"] is True
    assert report["journal_clearance"] is False
    assert report["resubmission_allowed"] is False
    raw["status"] = "pending_cancel"
    assert assess_order(intent, raw)["execution_terminal"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("client_order_id", "other"),
        ("symbol", "BTCUSD"),
        ("qty", "2"),
        ("limit_price", "101"),
        ("filled_qty", "1.1"),
        ("status", "filled"),
        ("status", "rejected"),
        ("filled_avg_price", "101"),
        ("filled_qty", "NaN"),
    ],
)
def test_inconsistent_recovery_blocks(field, value):
    intent, raw = order()
    raw[field] = value
    with pytest.raises(PaperReadError):
        assess_order(intent, raw)


def test_read_books_pins_data_origin_and_preserves_decimal_payload():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url).startswith(
            "https://data.alpaca.markets/v1beta3/crypto/us/latest/orderbooks?"
        )
        return httpx.Response(
            200,
            json={
                "orderbooks": {
                    s: {
                        "t": "2024-01-01T00:00:00Z",
                        "b": [{"p": 100.01, "s": 2.5}],
                        "a": [{"p": 100.02, "s": 3.5}],
                    }
                    for s in ("BTC/USD", "ETH/USD")
                }
            },
        )

    async def run():
        reader = PaperReader(
            PaperCredentials("fixture", "fixture"), transport=httpx.MockTransport(handler)
        )
        try:
            books = await reader.read_books()
            assert str(books["BTC/USD"].quote.bid) == "100.01"
            assert str(books["BTC/USD"].ask_size) == "3.5"
        finally:
            await reader.close()

    asyncio.run(run())
    assert len(calls) == 1
