"""Canonical persistence for a candidate's return stream — the curve, not just the verdict.

THE DEFECT THIS EXISTS TO PREVENT (found 2026-08-07, three instances in one project):

    `crypto_lowvol_720`   killed on DSR 0.04  -> artifacts held ONLY summary.txt
    `infl_surprise_size`  verdict "ADD"       -> artifacts held ONLY result.json (476 bytes)
    every future probe    unless this is used -> the same

Each of those runs computed a full daily return series, wrote a SCALAR verdict, and threw the
series away. That is not a filing inconvenience. A sleeve's worth in a portfolio is its
*uncorrelated* return, and correlation cannot be recovered from a Sharpe number — you need the
series. So `crypto_lowvol_720` had to be re-executed months later purely to answer the question
that decides it, and `infl_surprise_size` — a candidate that PASSED all four of its
pre-registered gates — still cannot be measured against the real book, because its curve does
not exist anywhere. You cannot build a portfolio out of scalars.

THE FORMAT IS THE WALK-FORWARD RUNNER'S, DELIBERATELY. Two columns, ``ts`` (int64 epoch ms UTC,
strictly ascending) and ``equity`` (float64) — byte-compatible with
``artifacts/walkforward/<run>/equity.parquet``. Anything that reads a sleeve curve reads a
candidate curve with no special case, which is the whole point: if the two formats diverged, the
book arithmetic would need a branch, and a branch is where the next discrepancy hides.

Sign convention: :func:`write_curve` takes SIMPLE (arithmetic) per-period returns, because that
is what the probes compute (``net = gross - costs``). :func:`read_curve` returns LOG returns,
because that is what every existing consumer uses (``np.log(equity).diff()``). The round trip is
therefore ``read_curve(write_curve(r)) == log1p(r)``, which is asserted in
``tests/unit/test_curve_store.py`` rather than left as a comment.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

__all__ = ["CURVE_FILENAME", "CurveFormatError", "read_curve", "write_curve"]

CURVE_FILENAME = "equity.parquet"
DEFAULT_INITIAL_EQUITY = 100_000.0


class CurveFormatError(ValueError):
    """A return series or persisted curve violates the canonical contract."""


def _validate(returns: pd.Series) -> pd.Series:
    """Reject anything that would silently corrupt downstream book arithmetic."""
    if not isinstance(returns, pd.Series):
        raise CurveFormatError(f"returns must be a pandas Series, got {type(returns).__name__}")
    if returns.empty:
        raise CurveFormatError("returns is empty — a curve with no observations is not a curve")
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise CurveFormatError(
            f"returns must be indexed by DatetimeIndex, got {type(returns.index).__name__}. "
            "An integer or RangeIndex cannot be aligned against a sleeve curve."
        )
    if returns.isna().any():
        raise CurveFormatError(
            f"returns contains {int(returns.isna().sum())} NaN(s). Drop or fill them at the "
            "point they are created, where the reason is known — not here."
        )
    if returns.index.has_duplicates:
        dupes = int(returns.index.duplicated().sum())
        raise CurveFormatError(f"returns index has {dupes} duplicate timestamp(s)")
    if not returns.index.is_monotonic_increasing:
        raise CurveFormatError("returns index must be strictly ascending")
    if (returns <= -1.0).any():
        raise CurveFormatError(
            "returns contains a value <= -100%, which would make equity non-positive and its "
            "log undefined. If that is real, the run is a total loss and needs its own handling."
        )
    return returns


def write_curve(
    returns: pd.Series,
    out_dir: str | Path,
    *,
    initial_equity: float = DEFAULT_INITIAL_EQUITY,
    filename: str = CURVE_FILENAME,
) -> Path:
    """Persist SIMPLE per-period returns as a canonical equity curve; return the written path.

    ``out_dir`` is created if absent. The curve compounds from ``initial_equity``, so the file is
    directly comparable to a walk-forward artifact and can be dropped into any book computation.

    Call this in EVERY probe that produces a return stream, next to where ``result.json`` is
    written. A verdict without its curve is a measurement that has to be repeated.
    """
    r = _validate(returns.astype(float))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    equity = float(initial_equity) * (1.0 + r).cumprod()
    # UTC epoch ms. tz-aware indexes are converted, not localized — a naive index is assumed UTC,
    # which matches every other timestamp in this codebase.
    idx = pd.DatetimeIndex(r.index)
    idx_utc = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    # Cast to ms EXPLICITLY rather than reading the backing int64. pandas 3 defaults a
    # DatetimeIndex to MICROSECOND resolution, so `.view("int64") // 1_000_000` silently produced
    # 1970-01-21 timestamps for 2024 data — caught by the round-trip test, not by review.
    ts_ms = idx_utc.tz_localize(None).astype("datetime64[ms]").astype("int64")
    frame = pd.DataFrame(
        {
            "ts": np.asarray(ts_ms, dtype="int64"),
            "equity": equity.to_numpy(dtype="float64"),
        }
    )
    path = out / filename
    frame.to_parquet(path, index=False)
    return path


def read_curve(path: str | Path) -> pd.Series:
    """Read a canonical curve and return DAILY LOG returns — the form every consumer uses.

    Tolerates intraday curves (the crypto sleeves are hourly) by resampling to the daily close,
    matching ``scripts/analyze_sleeve_scaling.py::daily_logret`` exactly so that "a daily return"
    means one thing across the whole project.
    """
    frame = pd.read_parquet(path)
    missing = {"ts", "equity"} - set(frame.columns)
    if missing:
        raise CurveFormatError(f"{path}: missing required column(s) {sorted(missing)}")
    series = pd.Series(
        frame["equity"].astype(float).to_numpy(),
        index=pd.to_datetime(frame["ts"], unit="ms"),
    ).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    daily = series.resample("1D").last().dropna()
    log_equity = pd.Series(
        np.log(daily.to_numpy(dtype="float64")),
        index=daily.index,
        dtype="float64",
    )
    return log_equity.diff().dropna()
