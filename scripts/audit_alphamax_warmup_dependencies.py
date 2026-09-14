"""Resolve baseline feature windows and metadata without computing signals or returns."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

from alphaforge.core.calendar import calendar_for
from alphaforge.core.time import Timeframe
from alphaforge.core.types import AssetClass
from alphaforge.features.library.equity_price import eq_mom_252_21
from alphaforge.signals.service import _OPEN_SPEC, _SIGMA_SPEC

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/alphamax-warmup-dependencies-20260913"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    calendar = calendar_for(AssetClass.EQUITY)
    tf = Timeframe.D1
    first = int(pd.Timestamp("2021-12-30", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
    grid = calendar.expected_bar_opens(946684800000, end, tf)
    train = grid[grid.index(first) - 252]
    specs = [eq_mom_252_21(), _SIGMA_SPEC, _OPEN_SPEC]
    lookback = max(s.lookback_bars for s in specs)
    warm = calendar.expected_bar_opens(train - (2 * lookback + 8) * tf.ms, train + tf.ms, tf)
    context = warm[-(lookback + 1)]
    momentum_grid = calendar.expected_bar_opens(train - (2 * 253 + 8) * tf.ms, train + tf.ms, tf)
    momentum_start = momentum_grid[-254]
    membership_path = ROOT / "evidence/historical-extension-inputs-20260913/membership_rows.parquet"
    membership = pd.read_parquet(membership_path)
    m = membership[membership.sleeve == "k30_dn_63"]
    active = m[
        (m.effective_from < pd.to_datetime(end, unit="ms", utc=True))
        & (m.effective_to.isna() | (m.effective_to > pd.to_datetime(train, unit="ms", utc=True)))
    ]
    ids = sorted(set(active.instrument_id))
    failure_path = (
        ROOT
        / "evidence/alphamax-corporate-action-route-20260913/all_date_split_failures_active_names.csv"
    )
    failures = pd.read_csv(failure_path)
    failures["date"] = pd.to_datetime(failures.date_utc, utc=True)
    involved = failures[
        (failures.instrument_id.isin(ids))
        & (failures.date >= pd.to_datetime(context, unit="ms", utc=True))
        & (failures.date < pd.to_datetime(end, unit="ms", utc=True))
    ]
    momentum_involved = involved[
        involved.date >= pd.to_datetime(momentum_start, unit="ms", utc=True)
    ]
    involved.to_csv(OUT / "shared_context_split_failures.csv", index=False)
    fields = (
        "instrument_id asset_class market_type base quote tick_size lot_size min_qty min_notional "
        "contract_multiplier can_short maker_fee_bps taker_fee_bps funding_interval_hours listed_ts "
        "delisted_ts valid_from_ms valid_to_ms"
    ).split()
    with sqlite3.connect(f"file:{PROD / 'var/ops.sqlite'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in ids)
        sql = f"SELECT {','.join(fields)} FROM instruments_v WHERE instrument_id IN ({placeholders}) ORDER BY instrument_id,valid_from_ms"
        metadata = [dict(row) for row in db.execute(sql, ids)]
    (OUT / "instrument_versions.json").write_text(json.dumps(metadata, indent=2) + "\n")
    unresolved = sorted(set(ids) - {r["instrument_id"] for r in metadata})
    known_at_train = {
        r["instrument_id"]
        for r in metadata
        if r["valid_from_ms"] <= train and (r["valid_to_ms"] is None or r["valid_to_ms"] > train)
    }
    source_files = [
        Path(__file__),
        membership_path,
        failure_path,
        ROOT / "src/alphaforge/signals/service.py",
        ROOT / "src/alphaforge/features/engine.py",
        ROOT / "src/alphaforge/features/library/equity_price.py",
        ROOT / "src/alphaforge/features/library/vol.py",
    ]
    report = {
        "scope": "Proposed full2022 baseline layout, not a frozen return experiment",
        "first_test_session": str(pd.to_datetime(first, unit="ms")),
        "train_start": str(pd.to_datetime(train, unit="ms")),
        "shared_context_start": str(pd.to_datetime(context, unit="ms")),
        "momentum_local_warmup_start": str(pd.to_datetime(momentum_start, unit="ms")),
        "specs": [
            {"name": s.name, "lookback_bars": s.lookback_bars, "params": dict(s.params)}
            for s in specs
        ],
        "run_window_member_ids": len(ids),
        "metadata_rows": len(metadata),
        "missing_metadata_ids": unresolved,
        "metadata_known_at_train_ids": len(known_at_train),
        "shared_context_split_failures": len(involved),
        "momentum_warmup_split_failures": len(momentum_involved),
        "baseline_sigma_input": "Raw close; corporate-action-adjusted prices are not passed to _sigma_fn.",
        "price_grid_window_2010_2022_verified": False,
        "no_warmup_shortening": True,
        "momentum_dependency_claim": "Local253-session dependency only; shared loader uses2520. No blanket corporate-action clearance.",
        "source_sha256": {str(p): sha(p) for p in source_files},
        "metadata_snapshot_sha256": sha(OUT / "instrument_versions.json"),
        "new_strategy_returns": 0,
        "replay_ready": False,
    }
    (OUT / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ["source_sha256", "specs"]}))
    print(involved[["instrument_id", "date_utc", "classification"]].to_string(index=False))


if __name__ == "__main__":
    main()
