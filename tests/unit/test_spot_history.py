import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from alphaforge.execution.spot_history import collect_daily_history
from alphaforge.execution.spot_paper import PaperCredentials, PaperReader
from alphaforge.portfolio.spot_restart import DAY_MS, SYMBOLS

END = int(datetime(2026, 9, 11, tzinfo=UTC).timestamp()) * 1000


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "repeat_token", "future"])
def test_paginated_reader_to_completed_histories(fault):
    async def run():
        requests = []

        def handle(request):
            assert request.method == "GET"
            assert request.url.host == "data.alpaca.markets"
            assert request.url.path == "/v1beta3/crypto/us/bars"
            requests.append(request)
            index = 0 if "page_token" not in request.url.params else 1
            symbol = SYMBOLS[index]
            bars = [
                {
                    "t": datetime.fromtimestamp((END - d * DAY_MS - 3_600_000) / 1000, UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "c": "100.123456789",
                    "v": "0",
                }
                for d in reversed(range(200))
            ]
            if fault == "missing" and index == 1:
                bars.pop()
            if fault == "duplicate" and index == 1:
                symbol = SYMBOLS[0]
            if fault == "future":
                bars[-1]["t"] = "2026-09-11T00:00:00Z"
            return httpx.Response(
                200,
                json={
                    "bars": {symbol: bars},
                    "next_page_token": "second" if index == 0 or fault == "repeat_token" else None,
                },
            )

        reader = PaperReader(
            PaperCredentials("fixture", "fixture"), transport=httpx.MockTransport(handle)
        )
        try:
            if fault:
                with pytest.raises(ValueError):
                    await collect_daily_history(reader, day_end_ms=END)
            else:
                histories, packet = await collect_daily_history(reader, day_end_ms=END)
                assert len(requests) == 2  # Short first page is not exhaustion.
                assert all(len(h) == 200 for h in histories.values())
                assert histories[SYMBOLS[0]][-1].close == Decimal("100.123456789")
                assert packet["missing_intraday_hours"] == dict.fromkeys(SYMBOLS, 4600)
                assert packet["historical_known_at_verified"] is False
                for page in packet["pages"]:
                    assert (
                        hashlib.sha256(page["decoded_json"].encode()).hexdigest()
                        == page["decoded_sha256"]
                    )
                    assert json.loads(page["decoded_json"])["bars"]
        finally:
            await reader.close()

    asyncio.run(run())
