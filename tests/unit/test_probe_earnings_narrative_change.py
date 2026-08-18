from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "probe_earnings_narrative_change.py"
SPEC = importlib.util.spec_from_file_location("probe_earnings_narrative_change", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_return_barrier_rejects_incomplete_corpus(tmp_path: Path) -> None:
    result = tmp_path / "corpus.json"
    result.write_text(
        json.dumps(
            {
                "stage": "corpus_ingest_no_prices_no_returns",
                "complete": False,
                "hypothesis_identities_spent": 0,
            }
        )
    )
    try:
        MODULE.require_complete(result, "corpus_ingest_no_prices_no_returns")
    except RuntimeError as error:
        assert "not complete" in str(error)
    else:  # pragma: no cover
        raise AssertionError("return barrier must reject an incomplete corpus")


def test_return_barrier_rejects_stale_pair_parquet(tmp_path: Path) -> None:
    pairs = tmp_path / "pairs.parquet"
    pairs.write_bytes(b"current bytes")
    corpus = {"parts_sha256": "corpus", "processed_rows": 10}
    pair_result = {
        "source_corpus_parts_sha256": "corpus",
        "source_processed_rows": 10,
        "pair_file_sha256": "stale",
    }
    try:
        MODULE.require_bound_pairs(corpus, pair_result, pairs)
    except RuntimeError as error:
        assert "pair parquet bytes" in str(error)
    else:  # pragma: no cover
        raise AssertionError("return runner must reject a stale pair parquet")


def test_return_barrier_binds_exact_manifest_bytes(tmp_path: Path, monkeypatch) -> None:
    pairs = tmp_path / "pairs.parquet"
    pairs.write_bytes(b"pair bytes")
    manifest = tmp_path / "manifest.parquet"
    manifest.write_bytes(b"manifest bytes")
    monkeypatch.setattr(MODULE, "MANIFEST", manifest)
    corpus = {"parts_sha256": "corpus", "processed_rows": 10}
    pair_result = {
        "source_corpus_parts_sha256": "corpus",
        "source_processed_rows": 10,
        "pair_file_sha256": MODULE.file_sha256(pairs),
        "source_manifest": {
            "path": str(manifest),
            "sha256": MODULE.file_sha256(manifest),
        },
        "preregistration_sha256": MODULE.file_sha256(MODULE.PREREG),
    }

    MODULE.require_bound_pairs(corpus, pair_result, pairs)
    manifest.write_bytes(b"changed manifest bytes")

    with pytest.raises(RuntimeError, match="manifest bytes"):
        MODULE.require_bound_pairs(corpus, pair_result, pairs)


def test_return_identity_is_reserved_before_market_data_and_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("locked")
    reservation = tmp_path / "reservation.json"
    monkeypatch.setattr(MODULE, "PREREG", prereg)
    monkeypatch.setattr(MODULE, "RESERVATION", reservation)
    corpus = {"parts_sha256": "corpus-sha"}
    pairs = {"pair_file_sha256": "pair-sha"}
    config = {"direction": "locked", "horizon": 63}

    first = MODULE.reserve_return_identity(corpus, pairs, config)
    second = MODULE.reserve_return_identity(corpus, pairs, config)

    assert first == second
    assert first["hypotheses_spent"] == 1
    assert first["status"] == "RETURN_IDENTITY_RESERVED"
    assert not reservation.with_suffix(".json.tmp").exists()

    with pytest.raises(RuntimeError, match="different locked inputs"):
        MODULE.reserve_return_identity(corpus, pairs, {**config, "horizon": 64})


def test_reaction_window_requires_a_complete_post_acceptance_session() -> None:
    calendar = pd.DatetimeIndex(["2024-12-31", "2025-01-02", "2025-01-03", "2025-01-06"])
    assert MODULE.reaction_window(calendar, pd.Timestamp("2025-01-02 13:00Z")) == (0, 1)
    assert MODULE.reaction_window(calendar, pd.Timestamp("2025-01-02 17:00Z")) == (0, 2)
    assert MODULE.reaction_window(calendar, pd.Timestamp("2025-01-02 22:00Z")) == (1, 2)
    assert MODULE.reaction_window(calendar, pd.Timestamp("2025-01-04 17:00Z")) == (2, 3)


def test_entry_is_second_session_after_month_end() -> None:
    calendar = pd.DatetimeIndex(["2025-01-31", "2025-02-03", "2025-02-04", "2025-02-05"])
    assert MODULE.second_session_after_month_end(calendar, pd.Timestamp("2025-01-15")) == 2


def test_spy_hedge_refuses_missing_oos_open() -> None:
    opens = pd.DataFrame(
        {"SPY": [100.0, np.nan]},
        index=pd.to_datetime(["2016-01-04", "2016-01-05"]),
    )
    try:
        MODULE.require_complete_spy_execution(opens)
    except RuntimeError as error:
        assert "stale prices" in str(error)
    else:  # pragma: no cover
        raise AssertionError("the hedge must not trade through a missing SPY open")


def test_ticker_mapping_uses_cik_and_contemporaneous_interval() -> None:
    history = pd.DataFrame(
        {
            "cik": [1, 1, 2],
            "ticker": ["OLD", "NEW", "OLD"],
            "firstpricedate": pd.to_datetime(["2010-01-01", "2020-01-01", "2010-01-01"]),
            "lastpricedate": pd.to_datetime(["2019-12-31", "2025-12-31", "2025-12-31"]),
        }
    )
    assert MODULE.map_ticker(history, 1, pd.Timestamp("2021-01-01")) == ("NEW", "mapped")
    ticker, reason = MODULE.map_ticker(history, 1, pd.Timestamp("2015-01-01"))
    assert ticker is None
    assert reason == "ticker_reuse_ambiguous"


def test_ranked_residuals_reject_saturated_design() -> None:
    saturated = pd.DataFrame(
        {
            "fivegram_jaccard": np.linspace(0.1, 0.9, 20),
            "reaction": np.linspace(-1, 1, 20),
            "momentum": np.linspace(1, -1, 20),
            "sic2": [f"{index:02d}" for index in range(20)],
        }
    )
    assert MODULE.ranked_residuals(saturated) is None


def test_duplicate_issuer_month_cannot_receive_multiple_cohort_votes() -> None:
    calendar = pd.date_range("2023-01-02", periods=520, freq="B")
    mapped = pd.DataFrame(
        {
            "cik": [1, 1],
            "ticker": ["AAA", "AAA"],
            "cohort_month": [pd.Timestamp("2024-06-01")] * 2,
            "entry_idx": [390, 390],
            "reaction_start_idx": [370, 371],
            "reaction_end_idx": [371, 372],
            "sic": ["1234", "1234"],
        }
    )
    closes = pd.DataFrame({"AAA": 10.0, "SPY": 100.0}, index=calendar)
    volume = pd.DataFrame({"AAA": 1_000_000.0, "SPY": 1_000_000.0}, index=calendar)
    close_lr = np.log(closes).diff()
    selected, rejected = MODULE.enrich_and_select(mapped, calendar, closes, volume, close_lr)
    assert selected.empty
    assert rejected["duplicate_issuer_month"] == 2


def test_target_weights_include_beta_hedge_and_unit_gross() -> None:
    calendar = pd.date_range("2025-01-02", periods=6, freq="B")
    selected = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "cohort_month": [pd.Timestamp("2024-12-01")] * 2,
            "entry_idx": [1, 1],
            "exit_idx": [4, 4],
            "cohort_stock_weight": [0.5, -0.5],
            "beta": [0.5, 0.2],
        }
    )
    stock, beta_weight = MODULE.target_weights(selected, calendar)
    stock, beta_weight = MODULE.normalize_stock_gross(stock, beta_weight)
    weights = MODULE.hedged_weights(stock, beta_weight)
    active = weights.iloc[1:4]
    assert np.allclose(active.abs().sum(axis=1), 1.0)
    assert (active["SPY"] < 0).all()
    assert (weights.iloc[[0, 4, 5]].abs().sum(axis=1) == 0).all()


def test_stock_gross_is_normalized_after_cross_cohort_netting() -> None:
    index = pd.date_range("2025-01-02", periods=2, freq="B")
    stock = pd.DataFrame({"AAA": [0.25, 0.0], "BBB": [-0.5, 0.0]}, index=index)
    beta = pd.DataFrame({"AAA": [0.10, 0.0], "BBB": [-0.10, 0.0]}, index=index)
    stock, beta = MODULE.normalize_stock_gross(stock, beta)
    assert np.isclose(stock.iloc[0].abs().sum(), 1.0)
    assert stock.iloc[1].abs().sum() == 0.0
    assert np.isclose(beta.iloc[0, 0], 0.10 / 0.75)


def test_missing_open_defers_exit_and_realizes_reopening_interval() -> None:
    index = pd.date_range("2025-01-02", periods=5, freq="B")
    desired = pd.DataFrame(
        {"AAA": [0.0, 0.5, 0.5, 0.0, 0.0], "SPY": [0.0, -0.1, -0.1, 0.0, 0.0]},
        index=index,
    )
    beta = pd.DataFrame({"AAA": [0.0, 0.1, 0.1, 0.0, 0.0]}, index=index)
    opens = pd.DataFrame({"AAA": [10.0, 10.0, 10.5, np.nan, 8.0]}, index=index)
    executed, deferred = MODULE.executable_weights(desired, beta, opens)
    assert executed.loc[index[3], "AAA"] == 0.5
    assert executed.loc[index[4], "AAA"] == 0.0
    assert executed.loc[index[3], "SPY"] == -0.1
    assert deferred == {"AAA": 1}


def test_annual_report_persists_each_oos_year() -> None:
    returns = pd.Series(
        [0.01, -0.005, 0.02],
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2025-01-02"]),
    )
    report = MODULE.annual_report(returns)
    assert set(report) == {"2024", "2025"}
    assert report["2024"]["observations"] == 2
    assert np.isclose(report["2025"]["total_return"], 0.02)


def test_canonical_diversification_is_gap_intolerant_and_confidence_bound(
    monkeypatch,
) -> None:
    rng = np.random.default_rng(42)
    index = pd.date_range("2023-01-02", periods=756, freq="B")
    candidate = pd.Series(rng.normal(0.0006, 0.005, len(index)), index=index)
    curves = {
        name: pd.Series(rng.normal(0.0001, 0.006, len(index)), index=index)
        for name in ("One", "Two", "Three", "Four")
    }
    monkeypatch.setattr(MODULE, "SLEEVE_CURVES", {name: name for name in curves})
    monkeypatch.setattr(MODULE, "read_curve", lambda path: curves[str(path)])
    monkeypatch.setattr(MODULE, "DIV_BOOTSTRAP_SAMPLES", 200)

    result, alignment, simple = MODULE.canonical_diversification_evidence(candidate)

    assert result.observations == len(index)
    assert result.stressed_observations >= 63
    assert result.bootstrap_samples == 200
    assert result.max_pairwise_correlation_upper_95 >= result.max_pairwise_correlation
    assert alignment["internal_missing_by_series"] == {}
    assert len(simple) == len(index)

    curves["Three"] = curves["Three"].drop(index[100])
    with pytest.raises(RuntimeError, match="no rows may be dropped"):
        MODULE.canonical_diversification_evidence(candidate)

    curves["Three"] = pd.Series(index=index, dtype=float)
    with pytest.raises(RuntimeError, match="contain no valid data"):
        MODULE.canonical_diversification_evidence(candidate)


def test_research_subset_never_claims_full_technical_eligibility(
    tmp_path: Path, monkeypatch
) -> None:
    contract = tmp_path / "admission.json"
    contract.write_text(
        json.dumps(
            {
                "schema": "canli.alphac-sleeve-admission-contract.v4",
                "evidence_checks_per_candidate": 75,
                "claim_boundary": "Research gates are not an admission decision.",
            }
        )
    )
    monkeypatch.setattr(MODULE, "ADMISSION_CONTRACT", contract)

    passing = MODULE.admission_review({"one": True, "two": True}, "abc123")
    failing = MODULE.admission_review({"one": True, "two": False}, "abc123")

    assert passing["status"] == "PENDING_FULL_75_CHECK_REVIEW"
    assert passing["technically_eligible"] is False
    assert passing["research_subset_passed"] == 2
    assert passing["checks_required_for_technical_eligibility"] == 75
    assert failing["status"] == "RESEARCH_SUBSET_FAILED"
    assert failing["technically_eligible"] is False


def test_hypothesis_hash_ignores_only_evaluation_window() -> None:
    left = {"signal": "x", "start": 1, "end": 2}
    right = {"signal": "x", "start": 3, "end": 4}
    changed = {"signal": "y", "start": 1, "end": 2}
    assert MODULE.hypothesis_hash(left) == MODULE.hypothesis_hash(right)
    assert MODULE.hypothesis_hash(left) != MODULE.hypothesis_hash(changed)


def test_market_frame_hash_binds_values_timestamps_and_missingness() -> None:
    index = pd.date_range("2025-01-02", periods=3, freq="B")
    frame = pd.DataFrame(
        {"open": [1.0, 2.0, 3.0], "close": [1.1, 2.1, 3.1], "volume": [10, 20, 30]},
        index=index,
    )
    changed = frame.copy()
    changed.loc[index[1], "close"] = 2.2
    missing = frame.copy()
    missing.loc[index[1], "close"] = np.nan

    assert MODULE.market_frame_sha256(frame) == MODULE.market_frame_sha256(frame.copy())
    assert MODULE.market_frame_sha256(frame) != MODULE.market_frame_sha256(changed)
    assert MODULE.market_frame_sha256(frame) != MODULE.market_frame_sha256(missing)


def test_action_manifest_binds_exact_normalized_rows(tmp_path: Path, monkeypatch) -> None:
    action_file = tmp_path / "instrument_id=XUSE:CASH:AAAUSD" / "year=2025" / "data.parquet"
    action_file.parent.mkdir(parents=True)
    actions = pd.DataFrame(
        {
            "action_type": ["split"],
            "ex_date": [pd.Timestamp("2025-01-03")],
            "ratio": [2.0],
            "cash_amount": [np.nan],
        }
    )
    actions.to_parquet(action_file, index=False)
    monkeypatch.setattr(MODULE, "ACTION_ROOT", tmp_path)

    before = MODULE.action_data_manifest({"AAA"})
    actions.loc[0, "ratio"] = 3.0
    actions.to_parquet(action_file, index=False)
    after = MODULE.action_data_manifest({"AAA"})

    assert before["rows"] == 1
    assert before["symbols_with_actions"] == 1
    assert before["sha256"] != after["sha256"]


def test_adjusted_panels_fail_closed_on_bad_action_partition(tmp_path: Path) -> None:
    action_file = tmp_path / "instrument_id=XUSE:CASH:AAAUSD" / "year=2025" / "data.parquet"
    action_file.parent.mkdir(parents=True)
    action_file.write_bytes(b"not parquet")
    index = pd.date_range("2025-01-02", periods=2, freq="B")
    opens = pd.DataFrame({"AAA": [10.0, 11.0], "SPY": [100.0, 101.0]}, index=index)
    closes = pd.DataFrame({"AAA": [10.5, 11.5], "SPY": [100.5, 101.5]}, index=index)
    original = MODULE.ACTION_ROOT
    MODULE.ACTION_ROOT = tmp_path
    try:
        MODULE.adjusted_panels(opens, closes)
    except RuntimeError as error:
        assert "corporate-action partition" in str(error)
    else:  # pragma: no cover
        raise AssertionError("a missing adjustment shard must fail closed")
    finally:
        MODULE.ACTION_ROOT = original


def test_split_during_halt_is_applied_on_reopening_print(tmp_path: Path) -> None:
    action_file = tmp_path / "instrument_id=XUSE:CASH:AAAUSD" / "year=2025" / "data.parquet"
    action_file.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "action_type": ["split"],
            "ex_date": [pd.Timestamp("2025-01-03")],
            "ratio": [2.0],
            "cash_amount": [np.nan],
        }
    ).to_parquet(action_file, index=False)
    index = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    opens = pd.DataFrame({"AAA": [100.0, np.nan, 51.0], "SPY": [100.0, 100.0, 100.0]}, index=index)
    closes = pd.DataFrame({"AAA": [100.0, np.nan, 51.0], "SPY": [100.0, 100.0, 100.0]}, index=index)
    original = MODULE.ACTION_ROOT
    MODULE.ACTION_ROOT = tmp_path
    try:
        open_lr, close_lr = MODULE.adjusted_panels(opens, closes)
    finally:
        MODULE.ACTION_ROOT = original
    assert open_lr.loc[index[1], "AAA"] == 0.0
    assert np.isclose(open_lr.loc[index[2], "AAA"], np.log(102.0 / 100.0))
    assert np.isclose(close_lr.loc[index[2], "AAA"], np.log(102.0 / 100.0))


def test_terminal_history_is_force_flat_at_final_observed_open() -> None:
    calendar = pd.date_range("2025-01-02", periods=6, freq="B")
    selected = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "cohort_month": [pd.Timestamp("2024-12-01")] * 2,
            "entry_idx": [1, 1],
            "exit_idx": [5, 5],
            "cohort_stock_weight": [0.5, -0.5],
            "beta": [0.5, 0.2],
        }
    )
    stock, beta_weight = MODULE.target_weights(selected, calendar)
    opens = pd.DataFrame(
        {"AAA": [1.0, 1.1, 1.2, np.nan, np.nan, np.nan], "BBB": 2.0}, index=calendar
    )
    stock, beta_weight, events = MODULE.force_flat_terminal_histories(
        stock, beta_weight, opens, selected
    )
    assert stock.loc[calendar[2] :, "AAA"].eq(0.0).all()
    assert beta_weight.loc[calendar[2] :, "AAA"].eq(0.0).all()
    assert events == [
        {"ticker": "AAA", "last_observed_open": str(calendar[2].date()), "affected_cohorts": 1}
    ]
