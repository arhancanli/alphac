from __future__ import annotations

import html
import importlib.util
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[2]
    / "scripts"
    / "audit_bond_etf_nav_dislocation_feasibility.py"
)
SPEC = importlib.util.spec_from_file_location(
    "audit_bond_etf_nav_dislocation_feasibility", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_balanced_object_parser_handles_nested_payload() -> None:
    text = 'prefix "premiumDiscountChartData":{"a":{"b":1},"value":["0.1"]} suffix'
    assert MODULE.extract_balanced_object(text, "premiumDiscountChartData") == {
        "a": {"b": 1},
        "value": ["0.1"],
    }


def test_premium_discount_parser_preserves_dates_and_signed_values() -> None:
    payload = (
        '"premiumDiscountChartData":{"asOfDate":[20250102,20250103],'
        '"value":["-0.25","0.10"]}'
    )
    frame = MODULE.parse_premium_discount(html.escape(payload).encode(), "HYG")
    assert frame["as_of_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-01-02",
        "2025-01-03",
    ]
    assert frame["issuer_premium_discount_percent"].tolist() == [-0.25, 0.10]


def test_holdings_header_requires_as_of_date_and_reports_schema() -> None:
    raw = (
        b'iShares Fund\nFund Holdings as of,"Aug 13, 2026"\n'
        b'Ticker,Name,Quantity,Weight (%),CUSIP\nABC,Bond,10,1.2,123456789\n'
    )
    parsed = MODULE.parse_holdings_header(raw)
    assert parsed["as_of_text"] == "Aug 13, 2026"
    assert parsed["has_cusip"] is True
    assert parsed["has_weight"] is True
    assert parsed["has_quantity"] is True
