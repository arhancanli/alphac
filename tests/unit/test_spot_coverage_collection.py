import asyncio
import importlib.util
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "spot_coverage_collector",
    Path(__file__).resolve().parents[2] / "scripts/collect_spot_evaluation_coverage.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_nanosecond_source_age_is_not_rounded_into_eligibility():
    decision = module.timestamp_ns("2024-01-01T00:05:00Z")
    source = module.timestamp_ns("2024-01-01T00:04:58.999999999Z")
    assert decision - source == 1_000_000_001


def configure(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "coverage")
    (module.OUT / "raw").mkdir(parents=True)


def test_cache_resume_uses_exact_query_and_hash(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "data.alpaca.markets"
        return httpx.Response(200, json={"quotes": {}, "next_page_token": None})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            collector = module.Collector(client)
            params = {"symbols": "BTC/USD", "limit": 1}
            first = await collector.get("quotes", params)
            second = await module.Collector(client).get("quotes", params)
            assert first == second and len(calls) == 1
            path = next((module.OUT / "raw").glob("*.json"))
            record = json.loads(path.read_text())
            record["sha256"] = "0" * 64
            path.write_text(json.dumps(record))
            with pytest.raises(ValueError, match="hash mismatch"):
                await collector.get("quotes", params)
            assert len(calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "timestamp,status",
    [
        ("2024-01-01T00:04:59.000000000Z", "SOURCE_AGE_WITHIN_ONE_SECOND"),
        ("2024-01-01T00:04:58.999999999Z", "SOURCE_AGE_OUTSIDE_ONE_SECOND"),
        ("2024-01-01T00:05:00.000000001Z", "SOURCE_AGE_OUTSIDE_ONE_SECOND"),
        (None, "MISSING_IN_PREDECISION_MINUTE"),
    ],
)
def test_quote_coverage_distinguishes_missing_stale_and_future(
    monkeypatch, tmp_path, timestamp, status
):
    configure(monkeypatch, tmp_path)

    def handler(request):
        assert request.url.params["sort"] == "desc"
        rows = [] if timestamp is None else [{"t": timestamp}]
        return httpx.Response(200, json={"quotes": {"BTC/USD": rows}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await module.Collector(client).quote(date(2024, 1, 1), "BTC/USD")
            assert result["status"] == status

    asyncio.run(run())


def test_repeating_pagination_token_fails(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)

    def handler(request):
        return httpx.Response(200, json={"bars": {}, "next_page_token": "repeat"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="pagination cycle"):
                await module.Collector(client).bars()

    asyncio.run(run())
