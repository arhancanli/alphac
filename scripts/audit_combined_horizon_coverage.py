"""Inspect retained source coverage; no longer-window return fabrication."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.validation.research_horizon import audit_horizon

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/combined-horizon-coverage-20260913"
FROZEN = ROOT / "evidence/combined-baseline-audit-20260912/sources"


def main():
    OUT.mkdir(exist_ok=False)
    record = FROZEN / "artifacts/analysis/current_book_diversification/result.json"
    prior = json.loads(record.read_text())
    sources = dict(prior["source_bindings"]["sleeve_equity_inputs"])
    paths = [(FROZEN / p, h) for p, h in sources.items()]
    candidate = (
        ROOT
        / "artifacts/analysis/alphatrend_positive_targets_20260913/candidate/run/equity.parquet"
    )
    paths.append((candidate, hashlib.sha256(candidate.read_bytes()).hexdigest()))
    cal = XNYSCalendar()
    results = []
    for path, expected_hash in paths:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
        frame = pd.read_parquet(path)
        assert not frame.ts.duplicated().any() and frame.ts.is_monotonic_increasing
        days = sorted({int(t) // 86400000 * 86400000 for t in frame.ts})
        crypto = "crypto_carry_wk" in str(path)
        for name, start, end in [
            ("covid_Q1", "2020-01-01", "2020-04-01"),
            ("year2022", "2022-01-01", "2023-01-01"),
            ("existing_window", "2023-07-07", "2026-06-02"),
        ]:
            lo, hi = [int(pd.Timestamp(d).timestamp() * 1000) for d in (start, end)]
            expected = (
                list(range(lo, hi, 86400000))
                if crypto
                else list(cal.expected_bar_opens(lo, hi, Timeframe.D1))
            )
            predecessor = (
                expected[0] - 86400000 if crypto else cal.floor_bar(expected[0] - 1, Timeframe.D1)
            )
            coverage = audit_horizon(days, expected, predecessor=int(predecessor))
            row = {
                "source": str(path),
                "sha256": expected_hash,
                "horizon": name,
                "calendar": "UTC_daily_last_available_mark" if crypto else "XNYS_session_labels",
                "first_mark": str(pd.to_datetime(frame.ts.min(), unit="ms")),
                "last_mark": str(pd.to_datetime(frame.ts.max(), unit="ms")),
                "coverage_complete": coverage.complete,
                **asdict(coverage),
            }
            results.append(row)
    (OUT / "coverage.json").write_text(json.dumps(results, indent=2) + "\n")
    for row in results:
        print(
            Path(row["source"]).parent.name,
            row["horizon"],
            "missing",
            len(row["missing_observations"]),
            "prior",
            row["predecessor_available"],
        )
    bindings = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__),
            record,
            ROOT / "src/alphaforge/validation/research_horizon.py",
            ROOT / "tests/unit/test_research_horizon.py",
        ]
    }
    (OUT / "verification.json").write_text(
        json.dumps(
            {
                "source_sha256": bindings,
                "new_return_identities": 0,
                "scope": "Daily observation coverage only; "
                "not complete intraday crypto grid or qualified strategy provenance",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
