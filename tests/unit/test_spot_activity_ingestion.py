import asyncio

import httpx
import pytest

from alphaforge.execution.spot_activities import convert_activities
from alphaforge.execution.spot_paper import (
    PaperCredentials,
    PaperReader,
    PaperReadError,
    account_digest,
)


def scan(pages, *, account_change=False):
    requests = []
    counters = {"account": 0, "pages": 0}

    def handle(request):
        assert request.method == "GET" and request.url.host == "paper-api.alpaca.markets"
        requests.append(request)
        if request.url.path == "/v2/account":
            counters["account"] += 1
            return httpx.Response(
                200,
                json={
                    "id": "changed" if account_change and counters["account"] > 1 else "dedicated"
                },
            )
        index = counters["pages"]
        counters["pages"] += 1
        assert "activity_types" not in request.url.params and "date" not in request.url.params
        if index:
            assert request.url.params["page_token"] == pages[index - 1][-1]["id"]
        return httpx.Response(200, json=pages[index])

    async def run():
        reader = PaperReader(
            PaperCredentials("fixture", "fixture"), transport=httpx.MockTransport(handle)
        )
        try:
            return await reader.read_activities(
                after="2024-01-01T00:00:00Z",
                until="2024-01-03T00:00:00Z",
                expected_account_binding=account_digest({"id": "dedicated"}),
            )
        finally:
            await reader.close()

    return asyncio.run(run()), requests


def test_short_page_does_not_imply_complete_and_late_fee_date_is_preserved():
    result, requests = scan(
        [
            [{"id": "a", "activity_type": "FILL"}],
            [
                {
                    "id": "b",
                    "activity_type": "CFEE",
                    "date": "2023-12-31",
                    "created_at": "2024-01-02T00:00:00Z",
                }
            ],
            [],
        ]
    )
    assert len(result["records"]) == 2 and result["pages_read"] == 3
    assert result["pagination_exhausted"] is True
    assert result["settlement_complete"] is False and result["journal_clearance"] is False
    assert len(requests) == 5


def test_duplicate_page_and_changed_account_block():
    row = {"id": "a", "activity_type": "FILL"}
    with pytest.raises(PaperReadError, match="duplicate"):
        scan([[row], [row]])
    with pytest.raises(PaperReadError, match="binding changed"):
        scan([[]], account_change=True)


def test_out_of_window_creation_is_not_accepted_using_settlement_date():
    with pytest.raises(PaperReadError, match="creation time"):
        scan(
            [
                [
                    {
                        "id": "a",
                        "activity_type": "CFEE",
                        "created_at": "2023-12-01T00:00:00Z",
                        "date": "2024-01-02",
                    }
                ]
            ]
        )


def test_pagination_budget_never_returns_partial_success():
    pages = [[{"id": str(i), "activity_type": "FILL"}] for i in range(21)]
    with pytest.raises(PaperReadError, match="pagination budget"):
        scan(pages)


def test_base_and_cash_fee_signs_are_not_confused():
    records = (
        {
            "id": "f",
            "activity_type": "FILL",
            "type": "partial_fill",
            "order_id": "o",
            "symbol": "BTCUSD",
            "qty": "1",
            "price": "100",
            "side": "buy",
        },
        {
            "id": "b",
            "activity_type": "CFEE",
            "symbol": "BTCUSD",
            "net_amount": "0",
            "qty": "-0.0025",
            "status": "executed",
        },
        {"id": "c", "activity_type": "CFEE", "net_amount": "-0.25"},
    )
    fills, fees = convert_activities(records)
    assert fills[0].symbol == "BTC/USD"
    assert [(f.asset, str(f.amount)) for f in fees] == [("BTC", "0.0025"), ("USD", "0.25")]


@pytest.mark.parametrize(
    "record",
    [
        {"activity_type": "CSD", "net_amount": "100"},
        {"activity_type": "CFEE", "net_amount": "0.25"},
        {"activity_type": "CFEE", "net_amount": "-0.25", "qty": "-1"},
        {"activity_type": "CFEE", "net_amount": "0", "qty": "-1", "symbol": "ETH/BTC"},
        {"activity_type": "CFEE", "net_amount": "-0.25", "status": "pending"},
        {"activity_type": "CFEE", "net_amount": "NaN"},
    ],
)
def test_unknown_flows_and_ambiguous_fees_fail(record):
    with pytest.raises(ValueError):
        convert_activities(({"id": "a", **record},))


@pytest.mark.parametrize(
    "after,until",
    [
        ("2024-01-01", "2024-01-02"),
        ("2024-01-02T00:00:00Z", "2024-01-01T00:00:00Z"),
        ("2024-01-01T00:00:00Z", "2024-01-09T00:00:00Z"),
        ("2099-01-01T00:00:00Z", "2099-01-02T00:00:00Z"),
    ],
)
def test_bad_window_fails_before_any_request(after, until):
    def handle(request):
        pytest.fail("invalid window made a network request")

    async def run():
        reader = PaperReader(
            PaperCredentials("fixture", "fixture"), transport=httpx.MockTransport(handle)
        )
        try:
            with pytest.raises(PaperReadError, match="UTC activity window"):
                await reader.read_activities(
                    after=after, until=until, expected_account_binding="fixture"
                )
        finally:
            await reader.close()

    asyncio.run(run())
