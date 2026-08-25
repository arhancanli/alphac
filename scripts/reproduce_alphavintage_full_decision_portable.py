#!/usr/bin/env -S uv run --isolated --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "numpy==2.4.3",
#   "pandas==3.0.3",
#   "pyarrow==24.0.0",
# ]
# ///
"""Replay every locked AlphaVintage decision gate from explicit inputs.

This standalone program regenerates AlphaVintage itself from fresh macro and ETF inputs and
replays the two diversification gates against three supplied benchmark equity curves.  The
benchmark curves are inputs: this program does not regenerate those upstream strategies.
"""

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
BOOK_LABELS: Final = ("eq", "mf", "inv")
ALLOCATION_GRID: Final = (0.05, 0.10, 0.15, 0.20)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_manifest_file_bindings(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("content_hash") != _content_hash(manifest):
        raise RuntimeError(f"invalid source-manifest content hash: {manifest_path}")
    for record in manifest["records"]:
        filename = record.get("normalized_file") or (
            f"{record['symbol']}.adjusted_close.parquet" if "symbol" in record else None
        )
        if filename is None or _sha256(directory / filename) != record["normalized_sha256"]:
            raise RuntimeError(f"normalized source binding failed: {directory / str(filename)}")
    return manifest


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
        residual_sd = (target - design @ beta).std(ddof=AR_LAGS + 1)
        prediction = beta[0] + sum(
            beta[lag + 1] * history[-(lag + 1)] for lag in range(AR_LAGS)
        )
        values[pd.Timestamp(vintage)] = float(
            np.clip((new - prediction) / max(residual_sd, 1e-12), -CLIP, CLIP)
        )
    return pd.Series(values).sort_index()


def _prices(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    return pd.Series(
        frame["close"].astype(float).to_numpy(), index=pd.to_datetime(frame["date"])
    ).sort_index()


def _equity_returns(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    series = pd.Series(
        frame["equity"].astype(float).to_numpy(),
        index=pd.to_datetime(frame["ts"], unit="ms").dt.normalize().to_numpy(),
    )
    return np.log(series[~series.index.duplicated()].sort_index()).diff().dropna()


def _sharpe(returns: pd.Series) -> float:
    deviation = returns.std(ddof=0)
    return float(returns.mean() / deviation * np.sqrt(ANN)) if deviation > 0 else 0.0


def _nw_t(returns: pd.Series, lags: int = 10) -> float:
    values = np.asarray(returns, float)
    if len(values) < 30:
        return 0.0
    residuals = values - values.mean()
    variance = (residuals @ residuals) / len(values)
    for lag in range(1, lags + 1):
        variance += (
            2
            * (1 - lag / (lags + 1))
            * ((residuals[lag:] @ residuals[:-lag]) / len(values))
        )
    return float(values.mean() / np.sqrt(max(variance, 1e-18) / len(values)))


def _curve_content_hash(returns: pd.Series) -> str:
    digest = hashlib.sha256()
    for date, value in returns.items():
        digest.update(f"{pd.Timestamp(date).date().isoformat()}|{float(value):.17g}\n".encode())
    return f"sha256:{digest.hexdigest()}"


def build(
    macro_dir: Path, market_dir: Path, book_curves: dict[str, Path]
) -> dict[str, Any]:
    if set(book_curves) != set(BOOK_LABELS):
        raise ValueError(f"book curves must be exactly {BOOK_LABELS}")
    macro_manifest = _validate_manifest_file_bindings(macro_dir)
    market_manifest = _validate_manifest_file_bindings(market_dir)
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

    benchmark_returns = {label: _equity_returns(book_curves[label]) for label in BOOK_LABELS}
    joined = pd.concat(
        [*benchmark_returns.values(), portfolio.rename("candidate")],
        axis=1,
        keys=[*BOOK_LABELS, "candidate"],
        sort=True,
    ).dropna()
    if len(joined) <= 100:
        raise RuntimeError("insufficient common history for the locked diversification checks")
    book = joined[list(BOOK_LABELS)].mean(axis=1)
    candidate = joined["candidate"]
    book_sharpe = _sharpe(book)
    candidate_join_sharpe = _sharpe(candidate)
    correlation = float(np.corrcoef(book, candidate)[0, 1])
    hurdle = correlation * book_sharpe
    zeroed_candidate = candidate - candidate.mean()
    allocation_rows = []
    best = {"book_sharpe_delta": -9.0, "zeroed_delta": 0.0, "mean_fraction_pct": 0.0}
    for allocation in ALLOCATION_GRID:
        book_delta = _sharpe((1 - allocation) * book + allocation * candidate) - book_sharpe
        zeroed_delta = (
            _sharpe((1 - allocation) * book + allocation * zeroed_candidate) - book_sharpe
        )
        mean_fraction = (
            (book_delta - zeroed_delta) / book_delta * 100 if abs(book_delta) > 1e-12 else 0.0
        )
        row = {
            "allocation": allocation,
            "book_sharpe": _sharpe((1 - allocation) * book + allocation * candidate),
            "book_sharpe_delta": book_delta,
            "zeroed_delta": zeroed_delta,
            "mean_fraction_pct": mean_fraction,
        }
        allocation_rows.append(row)
        if book_delta > best["book_sharpe_delta"]:
            best = row

    checks = {
        "a_clears_bar": bool(candidate_join_sharpe > hurdle),
        "b_nw_t_ge_1p5": bool(abs(_nw_t(portfolio)) >= 1.5),
        "c_benefit_is_the_mean": bool(
            best["mean_fraction_pct"] >= 50.0 and best["book_sharpe_delta"] > 0
        ),
        "d_placebo_dead": bool(abs(_nw_t(placebo)) < 1.5),
    }
    input_bindings = {
        "macro": {
            record["series"]: {
                "sha256": record["normalized_sha256"],
                "table_content_hash": record["normalized_table_content_hash"],
            }
            for record in macro_manifest["records"]
        },
        "market": {
            record["symbol"]: {
                "sha256": record["normalized_sha256"],
                "table_content_hash": record["normalized_table_content_hash"],
            }
            for record in market_manifest["records"]
        },
        "benchmark_equity_curves": {
            label: {
                "sha256": _sha256(book_curves[label]),
                "return_rows": len(benchmark_returns[label]),
                "return_content_hash": _curve_content_hash(benchmark_returns[label]),
            }
            for label in BOOK_LABELS
        },
    }
    document: dict[str, Any] = {
        "schema": "canli.alphac-alphavintage-full-decision-reproduction.v1",
        "spec": {
            "instruments": ["IWM", "SPY"],
            "placebo_instrument": "QQQ",
            "ar_lags": AR_LAGS,
            "clip": CLIP,
            "cost_oneway_bp": COST_ONEWAY * 1e4,
            "allocation_grid": list(ALLOCATION_GRID),
            "benchmark_curve_labels": list(BOOK_LABELS),
        },
        "input_bindings": input_bindings,
        "signal_vintages": len(signal),
        "net_sharpe": _sharpe(portfolio),
        "nw_t": _nw_t(portfolio),
        "active_day_net_sharpe_superseded": _sharpe(live),
        "portfolio_days": len(portfolio),
        "active_days": len(live),
        "gross_sharpe": _sharpe(gross[active]),
        "placebo_sharpe": _sharpe(placebo),
        "placebo_nw_t": _nw_t(placebo),
        "candidate_return_content_hash": _curve_content_hash(portfolio),
        "diversification": {
            "common_days": len(joined),
            "first_date": str(joined.index.min().date()),
            "last_date": str(joined.index.max().date()),
            "book_sharpe": book_sharpe,
            "candidate_join_sharpe": candidate_join_sharpe,
            "candidate_book_correlation": correlation,
            "candidate_sharpe_hurdle": hurdle,
            "allocation_results": allocation_rows,
            "best_allocation_result": best,
        },
        "checks": checks,
        "verdict": "ADD" if all(checks.values()) else "KILLED",
        "all_four_preregistered_decision_gates_replayed": True,
        "upstream_benchmark_strategies_regenerated_from_raw_inputs": False,
        "full_multi_sleeve_end_to_end_reproduction_completed": False,
        "independent_human_reproduction_completed": False,
        "claim_boundary": (
            "This standalone implementation regenerates AlphaVintage from freshly acquired CPI "
            "and ETF inputs and replays all four locked decision gates against three explicitly "
            "bound benchmark equity curves. It does not regenerate those upstream benchmark "
            "strategies from their raw inputs, grant redistribution rights, or constitute an "
            "independent human reproduction."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def _book_curve_arguments(values: list[str]) -> dict[str, Path]:
    curves: dict[str, Path] = {}
    for value in values:
        label, separator, path = value.partition("=")
        if not separator or label in curves:
            raise ValueError(f"book curve must be a unique LABEL=PATH: {value}")
        curves[label] = Path(path).resolve()
    return curves


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--market-dir", required=True, type=Path)
    parser.add_argument("--book-curve", action="append", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    document = build(
        arguments.macro_dir.resolve(),
        arguments.market_dir.resolve(),
        _book_curve_arguments(arguments.book_curve),
    )
    arguments.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
