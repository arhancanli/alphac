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


def test_a_fill_after_the_sealed_episode_is_subsequent_activity_not_a_broken_seal() -> None:
    """2026-09-14: the 2026-09-10 rebalance added a fourth LAB fill and the audit raised on any
    count other than three, turning an ordinary later trade into an hourly WARN. The episode's
    numbers must be identical with and without the later fill."""
    fills = [
        {"ts": 1_000, "side": "buy", "qty": 1.0, "price": 100.0, "fee_quote": 0.05},
        {"ts": 2_000, "side": "sell", "qty": 1.0, "price": 1.0, "fee_quote": 0.05},
        {"ts": 2_000, "side": "sell", "qty": 5.0, "price": 1.0, "fee_quote": 0.01},
    ]
    later = {"ts": 9_000, "side": "sell", "qty": 20.0, "price": 0.5, "fee_quote": 0.01}
    funding = pd.DataFrame(
        {"ts_funding": [pd.Timestamp(1_500, unit="ms", tz="UTC")], "rate": [-0.01]}
    )
    sealed = MODULE.analyze(fills, funding)
    extended = MODULE.analyze([*fills, later], funding)
    assert sealed["long_episode"] == extended["long_episode"]
    assert sealed["execution_sequence"] == extended["execution_sequence"]
    assert sealed["subsequent_activity"]["fills_after_sealed_episode"] == 0
    assert extended["subsequent_activity"]["fills_after_sealed_episode"] == 1
    assert extended["subsequent_activity"]["first_utc"] == "1970-01-01T00:00:09Z"
