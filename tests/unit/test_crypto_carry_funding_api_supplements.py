from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/fetch_crypto_carry_funding_api_supplements.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_funding_supplement", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_funding_api_pagination_is_exclusive_and_monotonic(monkeypatch) -> None:
    module = _module()
    events = [
        {"fundingTime": index, "fundingRate": "0.0001", "symbol": "ICPUSDT"}
        for index in range(1, 1003)
    ]

    def fake_request(url: str):
        query = parse_qs(urlparse(url).query)
        cursor = int(query["startTime"][0])
        return [row for row in events if row["fundingTime"] >= cursor][:1000]

    monkeypatch.setattr(module, "_request_json", fake_request)
    rows, pages = module._fetch_pages("ICPUSDT", 1, 1003, "https://example.test/api")
    assert [row["fundingTime"] for row in rows] == list(range(1, 1003))
    assert [page["rows"] for page in pages] == [1000, 2]
    assert all("payload" in page for page in pages)
