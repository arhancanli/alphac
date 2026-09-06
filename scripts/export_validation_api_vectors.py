#!/usr/bin/env python3
"""Parity vectors for the canlicapital validation API.

The JavaScript ports of _per_period_moments / dsr_from_returns and pbo_cscv are pinned
to THIS output. Deterministic: fixed seeds, fixed shapes, canonical JSON with default
escaping (see the 2026-08-27 canonicalisation incident: never ensure_ascii=False).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.validation.dsr import _per_period_moments, dsr_from_returns, expected_max_sharpe
from alphaforge.validation.pbo import pbo_cscv

REPO = Path(__file__).resolve().parent.parent
OUT = Path.home() / "meridian" / "standards" / "validation-api" / "vectors.json"


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _moment_vector(vid: str, seed: int, n: int, drift: float, ppy: float, trials: int, sd_ann: float) -> dict:
    rng = np.random.default_rng(seed)
    returns = rng.standard_t(df=5, size=n) * 0.01 + drift  # fat tails so skew/kurtosis matter
    sr, g3, g4, count = _per_period_moments(returns)
    variance_per_period = (sd_ann / math.sqrt(ppy)) ** 2
    report = dsr_from_returns(
        pd.Series(returns), n_trials=trials, sr_trials_variance=variance_per_period, periods_per_year=ppy
    )
    return {
        "id": vid,
        "returns": [float(x) for x in returns],
        "periods_per_year": ppy,
        "effective_independent_trials": trials,
        "cross_trial_sharpe_sd_annualized": sd_ann,
        "expected": {
            "sharpe_per_period": sr,
            "skew": g3,
            "non_excess_kurtosis": g4,
            "observations": count,
            "psr": float(report.psr),
            "dsr": float(report.dsr),
            "expected_max_sharpe_per_period": float(expected_max_sharpe(trials, variance_per_period)),
        },
    }


def _pbo_vector(vid: str, seed: int, rows: int, cols: int, n_splits: int, max_combinations: int) -> dict:
    rng = np.random.default_rng(seed)
    matrix = rng.normal(0.0, 0.01, size=(rows, cols))
    matrix[:, 0] += 0.002  # one variant with a small real edge
    result = pbo_cscv(matrix, n_splits=n_splits, max_combinations=max_combinations, seed=42)
    exhaustive = math.comb(n_splits, n_splits // 2) <= max_combinations
    return {
        "id": vid,
        "matrix": [[float(x) for x in row] for row in matrix],
        "n_splits": n_splits,
        "max_combinations": max_combinations,
        "seed": 42,
        "exhaustive": exhaustive,
        "expected": {
            "pbo": float(result.pbo),
            "n_combinations": int(result.n_combinations),
            "lambdas": [float(x) for x in result.lambdas] if exhaustive else None,
        },
    }


def main() -> None:
    payload = {
        "schema": "canli.validation-api-parity-vectors.v1",
        "generated_by": "scripts/export_validation_api_vectors.py",
        "python_bindings": {
            "dsr.py": _sha(REPO / "src/alphaforge/validation/dsr.py"),
            "pbo.py": _sha(REPO / "src/alphaforge/validation/pbo.py"),
        },
        "moments": [
            _moment_vector("daily_252_flat", 1, 252, 0.0, 252.0, 30, 0.5),
            _moment_vector("hourly_800_drift", 2, 800, 0.0002, 8760.0, 120, 0.3),
            _moment_vector("daily_1500_negative", 3, 1500, -0.0001, 365.0, 12, 0.8),
        ],
        "pbo": [
            _pbo_vector("exhaustive_4x2_6combos", 11, 64, 6, 4, 2000),
            _pbo_vector("exhaustive_8x4_70combos", 12, 160, 8, 8, 2000),
            _pbo_vector("sampled_16x8_2000of12870", 13, 256, 12, 16, 2000),
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
