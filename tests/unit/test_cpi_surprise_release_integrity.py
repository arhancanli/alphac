"""Regression pins for AlphaVintage's missing-release failure mode."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "probe_cpi_surprise_size_integrity", _ROOT / "scripts" / "probe_cpi_surprise_size.py"
)
assert _SPEC and _SPEC.loader
PROBE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PROBE)


def _rows(*, missing: str | None = None) -> pd.DataFrame:
    months = pd.date_range("2020-01-01", "2025-11-01", freq="MS")
    values = pd.Series(100.0 * np.exp(np.arange(len(months)) * 0.002), index=months)
    if missing:
        values.loc[pd.Timestamp(missing)] = np.nan
    return pd.DataFrame({"obs_period": months, "value": values.to_numpy()})


def test_complete_release_accepts_adjacent_latest_months() -> None:
    got = PROBE._complete_latest_monthly_release(_rows(), pd.Timestamp("2025-12-15"))
    assert got is not None
    assert got.index[-1] == pd.Timestamp("2025-11-01")


def test_missing_expected_release_skips_vintage() -> None:
    got = PROBE._complete_latest_monthly_release(
        _rows(missing="2025-11-01"), pd.Timestamp("2025-12-15")
    )
    assert got is None


def test_missing_predecessor_cannot_relabel_an_old_change_as_new() -> None:
    # Exact shape of the confirmed 2025 CPI defect: November exists, October does not.
    got = PROBE._complete_latest_monthly_release(
        _rows(missing="2025-10-01"), pd.Timestamp("2025-12-15")
    )
    assert got is None


def test_signal_recovers_only_after_two_adjacent_months_exist_again() -> None:
    rows = _rows(missing="2025-10-01")
    rows = pd.concat(
        [rows, pd.DataFrame({"obs_period": [pd.Timestamp("2025-12-01")], "value": [116.0]})],
        ignore_index=True,
    )
    got = PROBE._complete_latest_monthly_release(rows, pd.Timestamp("2026-01-15"))
    assert got is not None
    assert list(got.index[-2:]) == [pd.Timestamp("2025-11-01"), pd.Timestamp("2025-12-01")]


def test_portfolio_curve_retains_zero_exposure_sessions_inside_active_window() -> None:
    index = pd.date_range("2025-01-02", periods=6, freq="B")
    net = pd.Series([0.0, 0.01, 0.0, -0.005, 0.0, 0.0], index=index)
    weights = pd.Series([0.0, 1.0, 0.0, -1.0, 0.0, 0.0], index=index)

    got = PROBE.portfolio_calendar_returns(net, weights)

    assert got.index.equals(index[1:4])
    assert got.iloc[1] == 0.0
