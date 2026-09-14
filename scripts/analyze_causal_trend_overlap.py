"""Frozen descriptive overlap; no new strategy, allocation or return trial."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.analytics.session_overlap import session_intervals

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
BASE = ROOT / "artifacts/analysis/alphatrend_causal_continuous_20260912"
OUT = ROOT / "evidence/alphatrend-causal-overlap-20260912_completed"
SOURCES = {
    "trend": BASE / "candidate/run/equity.parquet",
    "trend_reservation": BASE / "candidate/reservation.json",
    "trend_correction": BASE / "metric_correction.json",
    "max": PROD / "artifacts/walkforward/k30_dn_63/equity.parquet",
    "max_config": PROD / "artifacts/walkforward/k30_dn_63/walkforward.json",
    "max_provenance": PROD / "artifacts/publication/alphamax_upstream_clean_workspace.json",
    "vintage": PROD / "artifacts/probe/cpi_surprise_size/equity.parquet",
    "vintage_result": PROD / "artifacts/probe/cpi_surprise_size/result.json",
    "vintage_writer": PROD / "scripts/probe_cpi_surprise_size.py",
    "curve_writer": PROD / "src/alphaforge/analytics/curve_store.py",
    "engine": ROOT / "src/alphaforge/backtest/engine.py",
    "alignment": ROOT / "src/alphaforge/analytics/session_overlap.py",
    "runner": Path(__file__),
}


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    (OUT / "sources").mkdir()
    bindings = {}
    for key, path in SOURCES.items():
        target = OUT / "sources" / (key + path.suffix)
        shutil.copy2(path, target)
        assert sha(path) == sha(target)
        bindings[key] = {
            "original": str(path),
            "sha256": sha(target),
            "snapshot": str(target.relative_to(OUT)),
        }
    write(
        OUT / "protocol.json",
        {
            "frozen_at": datetime.now(UTC).isoformat(),
            "sources": bindings,
            "scope": "DESCRIPTIVE_ARCHIVED_OVERLAP_NO_PORTFOLIO_CONSTRUCTION",
            "selection": "Base-cost candidate versus fixed AlphaMax and AlphaVintage curves",
            "alignment": "Engine labels map to preceding session close; CPI timestamps already "
            "label closes. Compute own-curve simple returns first; require identical start "
            "and end close and consecutive sessions. No filling or activity filtering.",
            "window": "Crop vintage to the first candidate economic close before returns; "
            "earlier dates cannot match candidate intervals and precede the core calendar.",
            "statistics": "Pairwise Pearson/Spearman and common-window Pearson; no fitted weights",
            "uncertainty": "2000 paired circular block bootstrap draws, block 63, seed 20260912; "
            "descriptive percentile 95% interval; missing intervals break calendar continuity",
            "new_return_trials": 0,
            "includes_disputed_alphaforge": False,
        },
    )
    provenance = json.loads((OUT / "sources/max_provenance.json").read_text())
    expected = provenance["comparison"]["equity_curve"]["reference_sha256"]
    assert expected == bindings["max"]["sha256"], "AlphaMax reference curve changed"
    from alphaforge.core.calendar import calendar_for
    from alphaforge.core.time import Timeframe
    from alphaforge.core.types import AssetClass

    first_trend = int(pd.read_parquet(OUT / "sources/trend.parquet").ts.min())
    first_close = calendar_for(AssetClass.EQUITY).floor_bar(first_trend - 1, Timeframe.D1)
    curves, coverage = {}, {}
    for name in ["trend", "max", "vintage"]:
        frame = pd.read_parquet(OUT / f"sources/{name}.parquet")
        series = frame.set_index("ts").equity
        if name == "vintage":
            series = series.loc[series.index >= first_close]
        curves[name], coverage[name] = session_intervals(
            series, convention="session_close" if name == "vintage" else "engine_next_session"
        )
    pair_results = {}
    for other in ["max", "vintage"]:
        joined = pd.concat(
            [curves["trend"].rename("trend"), curves[other].rename(other)], axis=1
        ).dropna()
        joined.to_parquet(OUT / f"aligned_trend_{other}.parquet")
        values = joined.to_numpy()
        n = len(values)
        rng = np.random.default_rng(20260912)
        boot = []
        for _ in range(2000):
            starts = rng.integers(0, n, int(np.ceil(n / 63)))
            indices = ((starts[:, None] + np.arange(63)) % n).ravel()[:n]
            sample = values[indices]
            if np.std(sample[:, 0]) > 0 and np.std(sample[:, 1]) > 0:
                boot.append(float(np.corrcoef(sample.T)[0, 1]))
        pair_results[other] = {
            "n_intervals": n,
            "first_end_close": str(pd.to_datetime(joined.index[0][1], unit="ms").date()),
            "last_end_close": str(pd.to_datetime(joined.index[-1][1], unit="ms").date()),
            "pearson": float(joined.corr().iloc[0, 1]),
            "spearman": float(joined.corr(method="spearman").iloc[0, 1]),
            "pearson_descriptive_95pct": np.quantile(boot, [0.025, 0.975]).tolist(),
            "bootstrap_valid_draws": len(boot),
        }
    common = pd.concat(curves, axis=1).dropna()
    common.to_parquet(OUT / "aligned_common.parquet")
    write(
        OUT / "result.json",
        {
            "coverage": coverage,
            "pairs": pair_results,
            "common_intervals": len(common),
            "common_pearson": common.corr().to_dict(),
            "max_reference_hash_matches": True,
            "max_exact_reproduction": provenance["comparison"]["equity_curve"]["frame_exact"],
            "vintage_verdict": json.loads((OUT / "sources/vintage_result.json").read_text())[
                "verdict"
            ],
            "disposition": "DESCRIPTIVE_ONLY_QUALIFIED_DIVERSIFICATION_UNESTABLISHED",
            "limitations": "Archived returns, inherited leg-reset and provenance limits in "
            "AlphaMax; killed CPI hypothesis, approximate log-spread PnL in vintage probe. "
            "Correlations do not establish incremental alpha, capacity or independent sleeves.",
            "new_return_trials": 0,
        },
    )
    print(json.dumps(pair_results, indent=2))


if __name__ == "__main__":
    main()
