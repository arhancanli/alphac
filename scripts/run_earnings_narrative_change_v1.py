#!/usr/bin/env python3
"""Earnings narrative change v1: the pre-registered return runner (calibration now, OOS gated).

Specification: docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md (declared 2026-08-15, one
hypothesis identity, direction locked long stable / short changed).

Two windows, two very different permissions:

- ``--window calibration`` (2006-01 through 2015-12): the prereg allows this interval to expose
  broken mappings, impossible timestamps, missing delistings or unstable extraction. It cannot
  change a parameter and cannot promote the sleeve. It spends no hypothesis identity and records
  nothing in any experiment ledger. Its artifact is plumbing evidence.
- ``--window oos`` (2016-01 through 2025-12): opened ONCE, only behind a v2 full-evidence
  reservation validated by the in-force guard, and only once that template is promoted. Until
  then this runner refuses, by construction, and says so.

Lineage seal, checked before any price is read: the corpus result must be complete and its
recorded manifest hash must equal the manifest on disk; the pairs file, the ticker history and
every module of the runner are hash-bound into the result.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from alphaforge.config.settings import load_settings  # noqa: E402
from alphaforge.core.time import Timeframe  # noqa: E402
from alphaforge.data.store.lake import LakePaths  # noqa: E402
from alphaforge.data.store.reader import PITDataReader  # noqa: E402
from alphaforge.research.narrative_change import evaluation, inputs, portfolio, signal  # noqa: E402
from alphaforge.validation.probe_ledger import selection_context  # noqa: E402

INGEST = REPO / "artifacts" / "ingest" / "earnings_narrative_change"
CORPUS_RESULT = INGEST / "corpus_result.json"
MANIFEST = INGEST / "filings_manifest.parquet"
PAIRS = INGEST / "item1a_pairs.parquet"
TICKER_HISTORY = INGEST / "issuer_ticker_history.parquet"
PREREG = REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE.md"
V2_TEMPLATE = REPO / "config" / "forward_full_evidence_reservation_v2_template.json"
OUT_ROOT = REPO / "artifacts" / "research" / "earnings_narrative_change_v1"
SPY_LAKE = REPO / "data" / "lake_mf"
FULL_LAKE = REPO / "data" / "lake_sharadar_full"
PACKAGE = REPO / "src" / "alphaforge" / "research" / "narrative_change"

WINDOWS = {
    "calibration": (dt.date(2006, 1, 1), dt.date(2015, 12, 31)),
    "oos": (dt.date(2016, 1, 1), dt.date(2025, 12, 31)),
}
WARMUP_SESSIONS = 300


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k != "content_hash"}
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _ms(day: dt.date) -> int:
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() * 1000)


def lineage_seal() -> dict[str, Any]:
    """Refuse a stale, replaced or partially rebuilt corpus before any return is loaded."""
    corpus = json.loads(CORPUS_RESULT.read_text(encoding="utf-8"))
    if corpus.get("complete") is not True:
        raise SystemExit("corpus result is not complete; refusing to load any return")
    manifest_sha = _sha256(MANIFEST)
    if corpus["source_manifest"]["sha256"] != manifest_sha:
        raise SystemExit("the filings manifest on disk is not the one the corpus result bound")
    return {
        "corpus_result": {
            "path": str(CORPUS_RESULT.relative_to(REPO)),
            "sha256": _sha256(CORPUS_RESULT),
        },
        "filings_manifest": {"path": str(MANIFEST.relative_to(REPO)), "sha256": manifest_sha},
        "pairs": {"path": str(PAIRS.relative_to(REPO)), "sha256": _sha256(PAIRS)},
        "ticker_history": {
            "path": str(TICKER_HISTORY.relative_to(REPO)),
            "sha256": _sha256(TICKER_HISTORY),
        },
        "preregistration": {"path": str(PREREG.relative_to(REPO)), "sha256": _sha256(PREREG)},
        "runner": {
            "script": _sha256(Path(__file__).resolve()),
            **{p.name: _sha256(p) for p in sorted(PACKAGE.glob("*.py"))},
        },
        "parts_sha256_recorded": corpus.get("parts_sha256"),
        "manifest_rows": corpus.get("manifest_rows"),
        "pairs_rows_recorded": None,
    }


def refuse_oos_without_authorization(reservation: Path | None) -> None:
    template = json.loads(V2_TEMPLATE.read_text(encoding="utf-8"))
    if template.get("status") != "IN_FORCE":
        raise SystemExit(
            "the out-of-sample interval opens only behind the v2 full-evidence reservation, and "
            f"that template's status is {template.get('status')!r}; nothing was loaded"
        )
    if reservation is None:
        raise SystemExit("--reservation is required for the out-of-sample window")


def run(
    window: str,
    *,
    max_cohorts: int | None,
    out_root: Path,
    reservation: Path | None,
    lake: Path | None = None,
) -> Path:
    t0 = time.time()
    if window == "oos":
        refuse_oos_without_authorization(reservation)
    start, end = WINDOWS[window]
    seal = lineage_seal()
    pairs = signal.eligible_pairs(pd.read_parquet(PAIRS))
    seal["pairs_rows_recorded"] = len(pairs)
    in_window = pairs[
        (pairs["current_acceptance"].dt.date >= start)
        & (pairs["current_acceptance"].dt.date <= end)
    ]
    history = inputs.IssuerTickerHistory.load(TICKER_HISTORY)

    spy_reader = PITDataReader(LakePaths(SPY_LAKE))
    cal_start, cal_end = _ms(dt.date(2004, 1, 1)), _ms(dt.date(2026, 1, 1))
    spy_bars = spy_reader.ohlcv(
        [inputs.SPY_INSTRUMENT_ID], start=cal_start, end=cal_end, as_of=cal_end, tf=Timeframe.D1
    ).to_pandas()
    calendar = inputs.SessionCalendar.from_spy_bars(spy_bars)
    spy_panel = inputs.load_daily_panel(
        spy_reader,
        [inputs.SPY_INSTRUMENT_ID],
        start_ms=cal_start,
        end_ms=cal_end,
        calendar=calendar,
    )

    months = sorted(
        {
            (int(y), int(m))
            for y, m in zip(in_window["cohort_year"], in_window["cohort_month"], strict=True)
        }
    )
    if max_cohorts is not None:
        months = months[:max_cohorts]
    # every issuer any cohort could enter, mapped at that cohort's entry date
    ids: set[str] = set()
    mapping_attrition: dict[str, int] = {}
    for year, month in months:
        entry = calendar.second_session_open_after_month_end(year, month)
        if entry is None:
            continue
        members = in_window[
            (in_window["cohort_year"] == year) & (in_window["cohort_month"] == month)
        ]
        for cik in members["cik"].to_numpy(dtype="int64").tolist():
            mapping = history.map(cik, entry)
            if mapping.status == "MAPPED" and mapping.ticker:
                ids.add(inputs.instrument_id_for(mapping.ticker))
            else:
                mapping_attrition[mapping.status] = mapping_attrition.get(mapping.status, 0) + 1
    first_entry = calendar.second_session_open_after_month_end(*months[0]) if months else start
    panel_start_pos = max(0, calendar.position(first_entry) - WARMUP_SESSIONS) if first_entry else 0
    panel_start = int(calendar.opens[panel_start_pos])
    exit_bound = min(end, calendar.dates[-1])
    panel_end = _ms(exit_bound) + inputs.DAY_MS
    settings = load_settings("sharadar")
    # The survivorship-inclusive lake (scripts/build_sharadar_full_history_lake.py) is the
    # default when it exists; the base lake is survivor-only (43 percent of a 2007 cohort had no
    # partition there) and is accepted only when named explicitly.
    lake_dir = (
        lake
        if lake is not None
        else (FULL_LAKE if FULL_LAKE.exists() else Path(settings.paths.lake_dir))
    )
    reader = PITDataReader(LakePaths(lake_dir))
    print(
        f"[{window}] {len(months)} cohorts, {len(ids)} instruments, loading panel ...", flush=True
    )
    panel = inputs.load_daily_panel(
        reader, sorted(ids), start_ms=panel_start, end_ms=panel_end, calendar=calendar
    )
    manifest = inputs.build_input_manifest(
        panel=panel,
        calendar=calendar,
        ticker_history_sha256=history.source_sha256,
        spy_source=str(SPY_LAKE.relative_to(REPO)),
        lake_dir=lake_dir,
    )
    spy_id = inputs.SPY_INSTRUMENT_ID
    spy_adjusted = spy_panel.adjusted_close[spy_id]
    print(
        f"[{window}] panel {panel.close.shape} in {time.time() - t0:.0f}s; building cohorts ...",
        flush=True,
    )

    cohorts: list[signal.CohortResult] = []
    for year, month in months:
        cohorts.append(
            signal.build_cohort(
                year=year,
                month=month,
                pairs=in_window,
                history=history,
                panel=panel,
                spy_adjusted=spy_adjusted,
                calendar=calendar,
            )
        )
    active, excluded = portfolio.schedule_cohorts(
        cohorts, panel, spy_panel, calendar, last_admissible_exit=exit_bound
    )
    start_pos = calendar.position(first_entry) if first_entry is not None else 0
    end_pos = int(np.searchsorted(calendar.opens, _ms(exit_bound), side="right"))
    book = portfolio.simulate_book(
        active, panel, spy_panel, calendar, start_pos=start_pos, end_pos=end_pos
    )
    book.capacity = portfolio.capacity_report(active, panel, calendar)
    spy_returns = spy_adjusted.pct_change()
    spy_returns.index = pd.Index(calendar.dates)
    n_union, sr_var = selection_context(root=REPO)
    report = evaluation.evaluate_book(
        book,
        spy_returns=spy_returns,
        union_identities=n_union,
        union_sharpe_variance=sr_var,
        window_label=window,
    )
    out = out_root / window
    out.mkdir(parents=True, exist_ok=True)
    book.frame().reset_index().to_parquet(out / "curve.parquet", index=False)
    cohort_rows = [
        {
            "year": c.year,
            "month": c.month,
            "entry_session": (c.entry_session.isoformat() if c.entry_session else None),
            "status": c.status,
            "attrition": c.attrition,
            "longs": int((c.rows["side"] == "LONG").sum()) if not c.rows.empty else 0,
            "shorts": int((c.rows["side"] == "SHORT").sum()) if not c.rows.empty else 0,
        }
        for c in cohorts
    ]
    (out / "cohorts.json").write_text(json.dumps(cohort_rows, indent=1) + "\n", encoding="utf-8")
    (out / "events.json").write_text(
        json.dumps(
            [
                {
                    "session": e.session.isoformat(),
                    "instrument_id": e.instrument_id,
                    "kind": e.kind,
                    "detail": e.detail,
                }
                for e in book.events
            ],
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "input_manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    result: dict[str, Any] = {
        "schema": "canli.alphac-earnings-narrative-change-v1-run.v1",
        "author": "Arhan Canli",
        "generated_at": evaluation.evaluation_date(),
        "window": window,
        "window_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "hypothesis_identities_spent": 0 if window == "calibration" else 1,
        "ledger_recorded": False,
        "claim_boundary": (
            "Calibration exposes plumbing only: it cannot change a parameter or promote the "
            "sleeve. "
            "Nothing here is an out-of-sample result. The locked direction is long stable, short "
            "changed; a failed result is never inverted."
            if window == "calibration"
            else "The single pre-registered out-of-sample run behind a validated v2 reservation."
        ),
        "lineage": seal,
        "input_manifest_content_hash": manifest["content_hash"],
        "cohorts": {
            "months": len(months),
            "ranked": sum(1 for c in cohorts if not c.is_flat),
            "flat_by_reason": {
                s: sum(1 for c in cohorts if c.status == s)
                for s in sorted({c.status for c in cohorts})
            },
            "excluded_exit_after_window": excluded,
            "issuer_mapping_attrition": mapping_attrition,
        },
        "evaluation": report,
        "union_context": {"identities": n_union, "hypothesis_sharpe_variance": sr_var},
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    result["content_hash"] = _content_hash(result)
    (out / "result.json").write_text(
        json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    net = report["net"]
    print(
        f"[{window}] cohorts ranked {result['cohorts']['ranked']}/{len(months)}; net Sharpe "
        f"{net['annualized_sharpe']}; NW t {net['newey_west_t']}; "
        f"max DD {net['max_drawdown']:.4f}; "
        f"force-flats {report['events']['force_flat']}; {result['elapsed_seconds']}s -> {out}"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--window", choices=sorted(WINDOWS), required=True)
    ap.add_argument("--max-cohorts", type=int, default=None, help="smoke runs only")
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--reservation", type=Path, default=None)
    ap.add_argument("--lake", type=Path, default=None, help="price lake (default: the full one)")
    args = ap.parse_args(argv)
    run(
        args.window,
        max_cohorts=args.max_cohorts,
        out_root=args.out,
        reservation=args.reservation,
        lake=args.lake,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
