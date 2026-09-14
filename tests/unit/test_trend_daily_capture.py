import asyncio
import copy
import hashlib
import json

import httpx
import pytest

from alphaforge.validation.trend_daily_capture import capture_daily, normalize_daily
from alphaforge.validation.trend_observation import ObservationError, session_window

SESSION = 1789084800000  # 2026-09-11
BODY = {
    "bars": {
        "SPY": [{"t": "2026-09-11T04:00:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 42}]
    },
    "next_page_token": None,
}


def test_valid():
    assert normalize_daily(BODY, session_ms=SESSION, symbols=["SPY"])[0]["close"] == 101


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.update(next_page_token="more"),
        lambda b: b["bars"].update(QQQ=b["bars"]["SPY"]),
        lambda b: b["bars"]["SPY"].append(b["bars"]["SPY"][0]),
        lambda b: b["bars"]["SPY"][0].update(t="2026-09-11T00:00:00Z"),
        lambda b: b["bars"]["SPY"][0].update(t="2026-09-11T04:00:00"),
        lambda b: b["bars"]["SPY"][0].update(c=float("nan")),
        lambda b: b["bars"]["SPY"][0].update(v=True),
        lambda b: b["bars"]["SPY"][0].update(l=101),
    ],
)
def test_bad_bars(mutation):
    body = copy.deepcopy(BODY)
    mutation(body)
    with pytest.raises(ObservationError):
        normalize_daily(body, session_ms=SESSION, symbols=["SPY"])


def run_capture(tmp_path, *, status=200, body=BODY, before=False):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False) as c:
            return await capture_daily(
                c,
                tmp_path / "capture",
                session_ms=SESSION,
                symbols=["SPY"],
                clock=lambda: session_window(SESSION)[0] + (-1 if before else 1),
            )

    return run, requests


def test_raw_saved_and_no_activation(tmp_path):
    run, requests = run_capture(tmp_path)
    result = asyncio.run(run())
    folder = tmp_path / "capture"
    receipt = json.loads((folder / "receipt.json").read_text())
    assert receipt["sha256"] == hashlib.sha256((folder / "response.bin").read_bytes()).hexdigest()
    assert not result["runtime_ready"]
    assert result["within_observation_window"]
    assert len(requests) == 1
    assert requests[0].url.params["feed"] == "sip"
    with pytest.raises(FileExistsError):
        asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize("status,body", [(403, {}), (200, {"bars": {}}), (302, {})])
def test_failed_response_retained(tmp_path, status, body):
    run, requests = run_capture(tmp_path, status=status, body=body)
    with pytest.raises(ObservationError):
        asyncio.run(run())
    assert len(requests) == 1
    assert (tmp_path / "capture/response.bin").exists()
    assert (tmp_path / "capture/failure.json").exists()
    assert not (tmp_path / "capture/normalized.json").exists()


def test_preclose_no_request(tmp_path):
    run, requests = run_capture(tmp_path, before=True)
    with pytest.raises(ObservationError):
        asyncio.run(run())
    assert not requests
