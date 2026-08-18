from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from probe_insider_clusters import (
    _entry_index,
    build_cluster_dates,
    capacity_report,
    target_weights,
)


def _event(owner: str, date: str, value: float, ticker: str = "AAA") -> dict[str, object]:
    return {
        "issuer_cik": "1",
        "filing_date": pd.Timestamp(date),
        "ticker": ticker,
        "owner_cik": owner,
        "purchase_value_usd": value,
        "accession_number": f"{owner}-{date}",
    }


def test_cluster_requires_two_distinct_owners_and_100k_inside_30_days() -> None:
    events = pd.DataFrame(
        [
            _event("A", "2026-01-01", 70_000),
            _event("A", "2026-01-10", 50_000),
            _event("B", "2026-01-20", 40_000),
            _event("C", "2026-03-01", 1_000_000),
        ]
    )
    clusters = build_cluster_dates(events)
    assert list(clusters["filing_date"]) == [pd.Timestamp("2026-01-20")]
    assert clusters.iloc[0]["distinct_insiders"] == 2
    assert clusters.iloc[0]["purchase_value_usd"] == 160_000


def test_target_weights_are_equal_notional_beta_hedged_and_gross_one() -> None:
    calendar = pd.date_range("2026-01-01", periods=3, freq="B")
    scheduled = pd.DataFrame(
        [
            {"ticker": "AAA", "entry_idx": 0, "exit_idx": 2, "beta": 1.0},
            {"ticker": "BBB", "entry_idx": 0, "exit_idx": 2, "beta": 2.0},
        ]
    )
    weights = target_weights(scheduled, calendar, ["AAA", "BBB", "SPY"])
    assert abs(weights.iloc[0].abs().sum() - 1.0) < 1e-12
    assert weights.iloc[0]["AAA"] == weights.iloc[0]["BBB"]
    assert weights.iloc[0]["SPY"] < 0
    assert weights.iloc[2].abs().sum() == 0


def test_capacity_uses_actual_weight_and_entry_time_adv() -> None:
    calendar = pd.date_range("2026-01-01", periods=2, freq="B")
    scheduled = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "entry_idx": 0,
                "exit_idx": 2,
                "beta": 1.0,
                "entry_adv": 10_000_000.0,
            },
            {
                "ticker": "BBB",
                "entry_idx": 0,
                "exit_idx": 2,
                "beta": 1.0,
                "entry_adv": 20_000_000.0,
            },
        ]
    )
    weights = target_weights(scheduled, calendar, ["AAA", "BBB", "SPY"])
    report = capacity_report(scheduled, weights)
    # Gross normalization makes each issuer 25%; AAA is the binding name.
    assert report["p05_usd_at_1bp_adv"] == 4_000.0
    assert report["p05_usd_at_1pct_adv"] == 400_000.0


def test_entry_index_applies_two_full_sessions_then_next_open() -> None:
    calendar = pd.DatetimeIndex(pd.date_range("2026-01-05", periods=5, freq="B"))
    # Filing Monday; Tuesday and Wednesday are the two delay sessions; enter Thursday.
    assert _entry_index(calendar, pd.Timestamp("2026-01-05")) == 3
