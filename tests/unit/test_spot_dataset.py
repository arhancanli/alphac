import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from alphaforge.validation.spot_dataset import normalize, utc_ns


def save(root, name, kind, params, data):
    raw = json.dumps(data).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (root / name).write_text(
        json.dumps(
            {
                "query": {
                    "url": "https://data.alpaca.markets/v1beta3/crypto/us/" + kind,
                    "params": params,
                },
                "body_hex": raw.hex(),
                "sha256": digest,
            }
        )
    )
    return {"raw": name, "sha256": digest}


def fixture(root, *, missing_quote=False, missing_close=False):
    today = datetime(2024, 1, 1, tzinfo=UTC)
    bars = {
        s: [
            {
                "t": (today - timedelta(days=i, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "c": 100,
                "v": 1,
            }
            for i in range(199, -1, -1)
        ]
        for s in ("BTC/USD", "ETH/USD")
    }
    if missing_close:
        bars["BTC/USD"].pop()
    binding = save(root, "bars.json", "bars", {"timeframe": "1Hour"}, {"bars": bars})
    quotes = []
    for i, symbol in enumerate(bars):
        params = {
            "symbols": symbol,
            "start": "2024-01-01T00:04:00Z",
            "end": "2024-01-01T00:05:00Z",
            "sort": "desc",
            "limit": 1,
        }
        rows = (
            []
            if missing_quote and i == 1
            else [{"bp": 100, "ap": 101, "bs": 2, "as": 3, "t": "2024-01-01T00:04:59.999999999Z"}]
        )
        quotes.append(
            {
                "date": "2024-01-01",
                "symbol": symbol,
                "binding": save(
                    root, f"quote{i}.json", "quotes", params, {"quotes": {symbol: rows}}
                ),
            }
        )
    return {
        "status": "COVERAGE_ONLY_NOT_RETURN_EVALUATION",
        "start": "2024-01-01",
        "end": "2024-01-01",
        "bar_coverage": {"bindings": [binding], "symbols": {}},
        "quotes": quotes,
    }


def test_close_only_inputs_preserve_nanoseconds_and_lineage_limitations(tmp_path):
    result = normalize(tmp_path, fixture(tmp_path))
    assert len(result["daily_closes"]["BTC/USD"]) == 200
    assert result["admission_ready"] is False
    quote = result["days"][0]["quotes"]["BTC/USD"]
    assert quote["source_ns"] == utc_ns("2024-01-01T00:04:59.999999999Z")
    assert quote["source_ms"] == result["days"][0]["decision_ms"] - 1


def test_missing_final_hour_is_not_forward_filled(tmp_path):
    with pytest.raises(ValueError, match="missing final-hour"):
        normalize(tmp_path, fixture(tmp_path, missing_close=True))


def test_missing_valuation_remains_in_calendar_and_blocks_readiness(tmp_path):
    result = normalize(tmp_path, fixture(tmp_path, missing_quote=True))
    assert result["status"] == "VALUATION_DATA_GATED"
    assert len(result["days"]) == 1
    assert result["days"][0]["quotes"]["ETH/USD"] is None
    assert len(result["unavailable_quotes"]) == 1


def test_changed_source_binding_is_rejected(tmp_path):
    coverage = fixture(tmp_path)
    coverage["quotes"][0]["binding"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        normalize(tmp_path, coverage)


def test_incomplete_or_duplicate_grid_cannot_pass(tmp_path):
    coverage = fixture(tmp_path)
    coverage["quotes"].pop()
    with pytest.raises(ValueError, match="incomplete quote"):
        normalize(tmp_path, coverage)
    coverage["quotes"].append(coverage["quotes"][0])
    with pytest.raises(ValueError, match="duplicate daily"):
        normalize(tmp_path, coverage)


def test_zero_volume_bar_is_valid_quote_based_signal_not_trade_execution(tmp_path):
    coverage = fixture(tmp_path)
    envelope = json.loads((tmp_path / "bars.json").read_text())
    body = json.loads(bytes.fromhex(envelope["body_hex"]))
    body["bars"]["BTC/USD"][-1]["v"] = 0
    coverage["bar_coverage"]["bindings"] = [
        save(tmp_path, "bars.json", "bars", {"timeframe": "1Hour"}, body)
    ]
    result = normalize(tmp_path, coverage)
    close = result["daily_closes"]["BTC/USD"][-1]
    assert close["close"] == "100" and close["volume"] == "0"
    assert close["price_semantics"] == "alpaca_trade_and_quote_midpoint_bar"
    assert result["admission_ready"] is False
