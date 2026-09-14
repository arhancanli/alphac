"""Issuer extraction must preserve cash details and refuse malformed evidence."""

import hashlib
import html
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/adjudicate_trend_dividends.py"
spec = importlib.util.spec_from_file_location("adjudication", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_page(tmp_path, **overrides):
    values = {
        "exDate": [20091201],
        "recordDate": [20091203],
        "payableDate": [20091207],
        "totalDistribution": ["0.580181"],
        "incomeAmount": ["0.084858"],
        "shortTermCapitalGain": ["0.098608"],
        "longTermCapitalGain": ["0.396715"],
        "returnOnCapital": ["0.0"],
    }
    values.update(overrides)
    props = {"distributionTableData": [{"name": k, "value": v} for k, v in values.items()]}
    raw = f'<walrus-render-on-client componentprops="{html.escape(json.dumps(props))}">'.encode()
    path = tmp_path / "SHY_issuer.html"
    path.write_bytes(raw)
    path.with_name("SHY_issuer_receipt.json").write_text(
        json.dumps(
            {
                "status": 200,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "received_at": "2026-09-12",
            }
        )
    )
    return path


def test_distribution_total_includes_all_components(tmp_path):
    (row,) = module.extract(fixture_page(tmp_path), "SHY")
    assert row["totalDistribution"] == "0.580181"
    assert row["total_minus_components"] == "0.000000"
    assert row["payableDate"] == "2009-12-07"


def test_missing_component_is_not_imputed_zero(tmp_path):
    (row,) = module.extract(fixture_page(tmp_path, incomeAmount=[None]), "SHY")
    assert row["incomeAmount"] is None
    assert row["total_minus_components"] is None
    assert row["totalDistribution"] == "0.580181"


@pytest.mark.parametrize(
    "overrides",
    [
        {"payableDate": []},
        {"payableDate": [20091130]},
        {"totalDistribution": ["-1"]},
    ],
)
def test_malformed_distribution_rejected(tmp_path, overrides):
    with pytest.raises(AssertionError):
        module.extract(fixture_page(tmp_path, **overrides), "SHY")


def test_changed_response_rejected(tmp_path):
    path = fixture_page(tmp_path)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AssertionError):
        module.extract(path, "SHY")
