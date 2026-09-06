from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/audit_crypto_lab_carry_crash.py"
SPEC = importlib.util.spec_from_file_location("audit_crypto_lab_carry_crash", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_genuine_crash_sequence_is_preserved_without_authorizing_change() -> None:
    fills = [
        {"side": "buy", "qty": 10.0, "price": 10.0, "fee_quote": 0.1, "ts": 1_000},
        {"side": "sell", "qty": 10.0, "price": 0.1, "fee_quote": 0.01, "ts": 3_000},
        {"side": "sell", "qty": 50.0, "price": 0.1, "fee_quote": 0.05, "ts": 3_000},
    ]
    funding = pd.DataFrame(
        {
            "ts_funding": pd.to_datetime([1_000, 2_000, 3_000], unit="ms", utc=True),
            "rate": [-0.01, -0.001, 0.001],
        }
    )

    result = MODULE.analyze(fills, funding)

    assert result["verdict"] == "GENUINE_MARKET_CRASH_NOT_CONTRACT_IDENTITY_DEFECT"
    assert result["long_episode"]["price_return"] == -0.99
    assert result["long_episode"]["net_price_pnl_after_entry_and_close_fees_quote"] == -99.11
    assert result["decision"] == "PRESERVE_LOSS_NO_PRICE_JUMP_GUARD_NO_WEIGHT_CHANGE"
    assert result["forward_record_relation"]["classification"].startswith("PRE_FLAGSHIP")
