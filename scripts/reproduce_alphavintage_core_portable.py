#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "numpy==2.4.3",
#   "pandas==3.0.3",
#   "pyarrow==24.0.0",
# ]
# ///
"""Standalone AlphaVintage core reproduction from independently fetched inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

ANN: Final = 252
COST_ONEWAY: Final = 0.0006
AR_LAGS: Final = 3
CLIP: Final = 3.0


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _complete_latest_monthly_release(
    vintage_rows: pd.DataFrame, vintage_date: pd.Timestamp
) -> pd.Series | None:
    expected = (vintage_date.to_period("M") - 1).to_timestamp()
    previous = (expected.to_period("M") - 1).to_timestamp()
    frame = vintage_rows.copy()
    frame["obs_period"] = pd.to_datetime(frame["obs_period"]).dt.to_period("M").dt.to_timestamp()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.drop_duplicates("obs_period", keep="last").sort_values("obs_period")
    by_month = frame.set_index("obs_period")["value"]
    if expected not in by_month.index or previous not in by_month.index:
        return None
    if pd.isna(by_month.loc[expected]) or pd.isna(by_month.loc[previous]):
        return None
    return by_month.loc[:expected]


def _surprise(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    frame["obs_period"] = pd.to_datetime(frame["obs_period"])
    frame["vintage_date"] = pd.to_datetime(frame["vintage_date"])
    values: dict[pd.Timestamp, float] = {}
    for vintage, group in frame.groupby("vintage_date"):
        complete = _complete_latest_monthly_release(group, pd.Timestamp(vintage))
        if complete is None:
            continue
        growth = pd.Series(np.log(complete.to_numpy(dtype=float))).diff().dropna().values
        if len(growth) < 45:
            continue
        new, history = growth[-1], growth[:-1]
        if len(history) < 40:
            continue
        target = history[AR_LAGS:]
        features = np.column_stack(
            [history[AR_LAGS - lag - 1 : len(history) - lag - 1] for lag in range(AR_LAGS)]
        )
        design = np.column_stack([np.ones(len(target)), features])
        beta, *_ = np.linalg.lstsq(design, target, rcond=None)
        sd = (target - design @ beta).std(ddof=AR_LAGS + 1)
        prediction = beta[0] + sum(beta[lag + 1] * history[-(lag + 1)] for lag in range(AR_LAGS))
        values[pd.Timestamp(vintage)] = float(
            np.clip((new - prediction) / max(sd, 1e-12), -CLIP, CLIP)
        )
    return pd.Series(values).sort_index()


def _prices(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    return pd.Series(
        frame["close"].astype(float).values, index=pd.to_datetime(frame["date"])
    ).sort_index()


def _sharpe(returns: pd.Series) -> float:
    deviation = returns.std(ddof=0)
    return float(returns.mean() / deviation * np.sqrt(ANN)) if deviation > 0 else 0.0


def _nw_t(returns: pd.Series, lags: int = 10) -> float:
    values = np.asarray(returns, float)
    residuals = values - values.mean()
    variance = (residuals @ residuals) / len(values)
    for lag in range(1, lags + 1):
        variance += (
            2 * (1 - lag / (lags + 1)) * ((residuals[lag:] @ residuals[:-lag]) / len(values))
        )
    return float(values.mean() / np.sqrt(max(variance, 1e-18) / len(values)))


def build(macro_dir: Path, market_dir: Path) -> dict[str, Any]:
    signal = (
        (
            _surprise(macro_dir / "PCPI_vintage_long.parquet")
            + _surprise(macro_dir / "PCPIX_vintage_long.parquet")
        )
        / 2.0
    ).dropna()
    iwm = _prices(market_dir / "IWM.adjusted_close.parquet")
    spy = _prices(market_dir / "SPY.adjusted_close.parquet")
    qqq = _prices(market_dir / "QQQ.adjusted_close.parquet")
    index = iwm.index.intersection(spy.index)
    spread = (np.log(iwm.reindex(index)).diff() - np.log(spy.reindex(index)).diff()).dropna()
    weights = pd.Series(0.0, index=spread.index)
    vintages = list(signal.index)
    for position, vintage in enumerate(vintages[:-1]):
        after = spread.index[spread.index > vintage]
        if not len(after):
            continue
        entry = after[0]
        segment = (spread.index > entry) & (spread.index <= vintages[position + 1])
        weights.loc[segment] = -float(np.clip(signal[vintage], -1, 1))
    turnover = (weights - weights.shift(1)).abs().fillna(0.0)
    gross = weights * spread
    net = gross - turnover * COST_ONEWAY * 2
    active = weights.abs() > 0
    active_index = weights.index[active]
    portfolio = net.loc[active_index.min() : active_index.max()]
    live = net[active]
    placebo_index = qqq.index.intersection(spy.index)
    placebo_spread = (
        np.log(qqq.reindex(placebo_index)).diff() - np.log(spy.reindex(placebo_index)).diff()
    ).dropna()
    placebo_weights = weights.reindex(placebo_spread.index).fillna(0.0)
    placebo = (placebo_weights * placebo_spread)[placebo_weights.abs() > 0]
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-core-portable-reproduction.v1",
        "spec": {
            "instruments": ["IWM", "SPY"],
            "placebo_instrument": "QQQ",
            "ar_lags": AR_LAGS,
            "clip": CLIP,
            "cost_oneway_bp": COST_ONEWAY * 1e4,
        },
        "signal_vintages": len(signal),
        "net_sharpe": _sharpe(portfolio),
        "nw_t": _nw_t(portfolio),
        "active_day_net_sharpe_superseded": _sharpe(live),
        "portfolio_days": len(portfolio),
        "active_days": len(live),
        "gross_sharpe": _sharpe(gross[active]),
        "placebo_sharpe": _sharpe(placebo),
        "placebo_nw_t": _nw_t(placebo),
        "significance_gate_passes": abs(_nw_t(portfolio)) >= 1.5,
        "placebo_gate_passes": abs(_nw_t(placebo)) < 1.5,
        "verdict_from_significance_gate": "ADD" if abs(_nw_t(portfolio)) >= 1.5 else "KILLED",
        "full_diversification_checks_replayed": False,
        "claim_boundary": (
            "This standalone implementation reproduces the signal, return, cost, significance "
            "and placebo calculations from freshly acquired CPI and ETF inputs. It does not replay "
            "the separate three-sleeve diversification curves or establish independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--market-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    document = build(arguments.macro_dir.resolve(), arguments.market_dir.resolve())
    arguments.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
