from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import probe_insider_clusters as module
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


def test_market_hash_binds_values_timestamps_and_missingness() -> None:
    index = pd.date_range("2025-01-02", periods=2, freq="B")
    frame = pd.DataFrame(
        {"open": [1.0, 2.0], "close": [1.1, 2.1], "volume": [10.0, 20.0]},
        index=index,
    )
    changed = frame.copy()
    changed.loc[index[1], "close"] = 2.2
    missing = frame.copy()
    missing.loc[index[1], "close"] = float("nan")
    assert module.market_frame_sha256(frame) != module.market_frame_sha256(changed)
    assert module.market_frame_sha256(frame) != module.market_frame_sha256(missing)


def test_reproduction_environment_binds_runner_and_lockfiles() -> None:
    evidence = module.reproduction_environment()
    assert evidence["command"] == "uv run python scripts/probe_insider_clusters.py"
    assert evidence["runner_sha256"] == module.file_sha256(module.RUNNER)
    assert evidence["pyproject_sha256"] == module.file_sha256(module.PYPROJECT)
    assert evidence["uv_lock_sha256"] == module.file_sha256(module.UV_LOCK)


def test_admission_review_is_fail_closed_against_v6(tmp_path: Path, monkeypatch) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema": "canli.alphac-sleeve-admission-contract.v6",
                "evidence_checks_per_candidate": 85,
            }
        )
    )
    monkeypatch.setattr(module, "ADMISSION_CONTRACT", contract)
    review = module.admission_review({"one": True, "two": False})
    assert review["status"] == "RESEARCH_SUBSET_FAILED"
    assert review["technically_eligible"] is False


def test_ledger_reconciliation_rejects_an_extended_replay() -> None:
    returns = pd.Series([0.01, -0.02, 0.03])
    current_population = module.sharpe(returns) * (3 / 2) ** 0.5
    record = type(
        "Record",
        (),
        {
            "config": {"probe": "insider_purchase_clusters"},
            "config_hash": "abc",
            "n_obs": 2,
            "sharpe_ann": current_population,
            "now_ms": 1,
        },
    )()
    reconciliation = module.reconcile_ledger_measurement(record, returns)
    assert reconciliation["observation_delta"] == 1
    assert reconciliation["exact_first_measurement_reproduced"] is False
    assert reconciliation["packet_completion_eligible"] is False
    assert reconciliation["relation"] == "OOS_EXTENSION_NOT_EXACT_REPRODUCTION"
