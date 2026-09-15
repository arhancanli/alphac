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
from alphaforge.research.narrative_change import (  # noqa: E402
    evaluation,
    inputs,
    portfolio,
    scenarios,
    signal,
)
from alphaforge.validation.probe_ledger import selection_context  # noqa: E402

INGEST = REPO / "artifacts" / "ingest" / "earnings_narrative_change"
MANIFEST = INGEST / "filings_manifest.parquet"
TICKER_HISTORY = INGEST / "issuer_ticker_history.parquet"
# One family, two pre-registered identities, one atomic batch (the v2 protocol needs two
# counted columns for a PBO matrix). Every difference between the two is listed here and
# nowhere else: the section parsed, the corpus and pairs files that carry it, the
# pre-registration that locked it, and the alpha name that spends the identity.
SECTIONS: dict[str, dict[str, Any]] = {
    "item1a": {
        "profile": "earnings_narrative_change_v1",
        "alpha": "sec_10k_item1a_stability_jaccard5",
        "label": "10-K Item 1A",
        "corpus_result": INGEST / "corpus_result.json",
        "pairs": INGEST / "item1a_pairs.parquet",
        "prereg": REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "out_root": REPO / "artifacts" / "research" / "earnings_narrative_change_v1",
    },
    "item7": {
        "profile": "earnings_narrative_change_mdna_v1",
        "alpha": "sec_10k_item7_stability_jaccard5",
        "label": "10-K Item 7",
        "corpus_result": INGEST / "item7_corpus_result.json",
        "pairs": INGEST / "item7_pairs.parquet",
        "prereg": REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE_MDNA.md",
        "out_root": REPO / "artifacts" / "research" / "earnings_narrative_change_mdna_v1",
    },
}
BATCH_ID = "earnings_narrative_change_batch_1"
BATCH_MATRIX_DIR = REPO / "artifacts" / "research" / "identity_batches"
#: The matrix receipt lives INSIDE the batch's own directory, beside the filled-reservation
#: audits, never at the registry's top level: the reservation validator reads every top-level
#: JSON there as a batch registry and fails closed on any other schema, which is exactly what
#: stopped the second batch attempt at its first ledger record (2026-09-15 02:32Z).
BATCH_MATRIX_PATH = BATCH_MATRIX_DIR / BATCH_ID / "matrix_receipt.json"
LEDGER = REPO / "var" / "experiments.jsonl"
PBO_N_SPLITS = 16
PBO_MAX_COMBINATIONS = 12870
PBO_SEED = 20260914
V2_TEMPLATE = REPO / "config" / "forward_full_evidence_reservation_v2_template.json"
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


def trial_config(section: str) -> dict[str, Any]:
    """The hypothesis identity, transcribed from the pre-registration's ``prereg`` block.

    ``start`` and ``end`` are the out-of-sample window and are the only keys the trial policy
    exempts from the identity; every other key spends the identity, so the two sections are two
    counted hypotheses.
    """
    spec = SECTIONS[section]
    start, end = WINDOWS["oos"]
    return {
        "profile": spec["profile"],
        "lake_dir": "data/lake_sharadar_full",
        "alpha_names": [spec["alpha"]],
        "allocator": "monthly_residual_quintile_beta_hedged",
        "section": spec["label"],
        "parser_version": "sec-filing-sections-v2",
        "direction": "long_stable_short_changed",
        "hold_sessions": 63,
        "start": _ms(start),
        "end": _ms(end),
    }


def lineage_seal(section: str) -> dict[str, Any]:
    """Refuse a stale, replaced or partially rebuilt corpus before any return is loaded."""
    spec = SECTIONS[section]
    corpus_result: Path = spec["corpus_result"]
    pairs_path: Path = spec["pairs"]
    prereg: Path = spec["prereg"]
    corpus = json.loads(corpus_result.read_text(encoding="utf-8"))
    if corpus.get("complete") is not True:
        raise SystemExit("corpus result is not complete; refusing to load any return")
    manifest_sha = _sha256(MANIFEST)
    if corpus["source_manifest"]["sha256"] != manifest_sha:
        raise SystemExit("the filings manifest on disk is not the one the corpus result bound")
    return {
        "section": section,
        "corpus_result": {
            "path": str(corpus_result.relative_to(REPO)),
            "sha256": _sha256(corpus_result),
        },
        "filings_manifest": {"path": str(MANIFEST.relative_to(REPO)), "sha256": manifest_sha},
        "pairs": {"path": str(pairs_path.relative_to(REPO)), "sha256": _sha256(pairs_path)},
        "ticker_history": {
            "path": str(TICKER_HISTORY.relative_to(REPO)),
            "sha256": _sha256(TICKER_HISTORY),
        },
        "preregistration": {"path": str(prereg.relative_to(REPO)), "sha256": _sha256(prereg)},
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


def authorize_oos(section: str, reservation: Path | None) -> dict[str, Any]:
    """Three refusals before a single price is read, each with its receipt.

    The template must be in force; the reservation must validate against THIS section's trial
    config under the in-force guard (batch, seriality, ordinal, governance epoch, evidence
    hashes, which include this very file); and the filled-reservation audit must find the
    evidence conjunction satisfiable. Nothing here is an outcome.
    """
    refuse_oos_without_authorization(reservation)
    assert reservation is not None
    from alphaforge.validation.trial_reservation import validate_reservation

    payload = json.loads(reservation.read_text(encoding="utf-8"))
    validation = validate_reservation(payload, trial_config=trial_config(section), repo=REPO)
    if validation["status"] != "VALIDATED_BEFORE_RETURN_COMPUTE":
        raise SystemExit(f"reservation not validated: {validation['status']}")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "filled_reservation_audit", REPO / "scripts" / "audit_forward_full_evidence_reservation.py"
    )
    assert spec is not None and spec.loader is not None
    audit_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_module)
    audit = audit_module.audit(reservation, REPO)
    if audit["status"] != "SATISFIABLE_RETURN_BLIND":
        raise SystemExit(
            "the filled reservation is not satisfiable as written: " + "; ".join(audit["failures"])
        )
    return {
        "reservation_path": str(reservation.resolve().relative_to(REPO)),
        "reservation_sha256": _sha256(reservation),
        "validation": validation,
        "audit_status": audit["status"],
        "audit_content_hash": audit["content_hash"],
        "disposition_ceiling": audit["disposition_ceiling"],
    }


def rerun_authorization(
    section: str, reservation: Path | None, rerun_of: Path, *, out_root: Path | None
) -> dict[str, Any]:
    """The deterministic re-run of an identity already sealed: read-only against the record.

    The out-of-sample window opened once, behind the validated reservation, and that identity is
    now logged, so the validator would (rightly) refuse the same reservation a second time. The
    re-run is not a second measurement: it recomputes the same section from the same sealed
    inputs so the seal can compare the net series by hash. It is allowed only against a sealed
    result whose authorization bound the very reservation file passed here (unchanged since),
    only for that result's section, and only into a fresh out_root away from the sealed
    directory, because run() writes the curve, cohorts, events and manifest beside the result.
    """
    if reservation is None:
        raise SystemExit("a re-run needs the reservation the sealed run was authorized by")
    if out_root is None or out_root.resolve() == rerun_of.resolve().parent.parent:
        raise SystemExit("a re-run must write into a fresh out_root, never the sealed directory")
    sealed = json.loads(rerun_of.read_text(encoding="utf-8"))
    if sealed.get("content_hash") != _content_hash(sealed):
        raise SystemExit("the sealed result's content hash does not verify; nothing to re-run")
    if sealed.get("section") != section:
        raise SystemExit(f"the sealed result is {sealed.get('section')!r}, not {section!r}")
    authorization = dict(sealed["authorization"])
    if authorization.get("reservation_sha256") != _sha256(reservation):
        raise SystemExit("the reservation moved since the sealed run bound it; re-run refused")
    resolved = rerun_of.resolve()
    authorization["rerun_of"] = (
        str(resolved.relative_to(REPO)) if resolved.is_relative_to(REPO) else str(resolved)
    )
    authorization["rerun_of_content_hash"] = sealed["content_hash"]
    return authorization


def run(
    window: str,
    *,
    section: str = "item1a",
    max_cohorts: int | None,
    out_root: Path | None = None,
    reservation: Path | None,
    lake: Path | None = None,
    defer_result: bool = False,
    rerun_of: Path | None = None,
) -> dict[str, Any]:
    """One window of one section. Returns the run's out dir, result document and net returns.

    With ``defer_result`` the result document is returned but NOT written and the ledger is
    untouched; the batch runner writes both members together after the matrix exists, so no
    member's evaluation is on disk before the other's curve is. With ``rerun_of`` (the sealed
    result of an identity already logged) the window is not re-authorized: the run is the
    seal's deterministic re-run, deferred, into a fresh out_root (see rerun_authorization).
    """
    t0 = time.time()
    spec = SECTIONS[section]
    if rerun_of is not None and not defer_result:
        raise SystemExit("a re-run is always deferred: it must not write a result or a ledger row")
    authorization: dict[str, Any] | None = None
    if window == "oos" and rerun_of is not None:
        authorization = rerun_authorization(section, reservation, rerun_of, out_root=out_root)
    elif window == "oos":
        authorization = authorize_oos(section, reservation)
    out_root = out_root if out_root is not None else spec["out_root"]
    start, end = WINDOWS[window]
    seal = lineage_seal(section)
    pairs = signal.eligible_pairs(pd.read_parquet(spec["pairs"]))
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
        "section": section,
        "profile": spec["profile"],
        "trial_config": trial_config(section),
        "authorization": authorization,
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
    net_returns = book.frame()["net_return"].astype("float64")
    # The sealed primary decision path: every cohort's entry, exit and signed weights. A
    # diagnostic binds to this hash; a scenario computed on any other set of decisions is a new
    # identity, not a diagnostic of this one.
    decision_path = [
        {
            "year": c.year,
            "month": c.month,
            "entry_pos": c.entry_pos,
            "exit_pos": c.exit_pos,
            "weights": {k: float(v) for k, v in sorted(c.weights.items())},
        }
        for c in active
    ]
    primary_decision_path_sha256 = scenarios.canonical_sha256(decision_path)
    result["primary_decision_path_sha256"] = primary_decision_path_sha256
    if authorization is not None:
        assert reservation is not None
        result["book_evidence"] = _book_evidence(reservation, net_returns)
        result["diagnostics"] = _evaluate_declared_diagnostics(
            reservation,
            primary_decision_path_sha256=primary_decision_path_sha256,
            active=active,
            panel=panel,
            spy=spy_panel,
            calendar=calendar,
            start_pos=start_pos,
            end_pos=end_pos,
        )
    if not defer_result:
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
    return {"out": out, "result": result, "net_returns": net_returns}


def _book_evidence(reservation: Path, net_returns: pd.Series) -> dict[str, Any]:
    """The candidate against the frozen existing book: correlations, book deltas, drawdown.

    The reservation binds the snapshot of the four current sleeves' daily returns and the book
    they form (UTC calendar days, 0.0 where a sleeve is flat, exactly as the published composite
    treats its own equity sleeve). The candidate is placed on that calendar with 0.0 on
    non-sessions, the same convention, so no internal date is missing on the common window.
    Correlations and the fixed-weight deltas go through the shared diversification engine; the
    drawdown block bootstraps the zero-drift book with and without the candidate at the frozen
    weight, with the current-composition study's generator, seed and block, and reports the
    expected and 95th-percentile maximum drawdown of each.
    """
    import importlib.util

    payload = json.loads(reservation.read_text(encoding="utf-8"))
    book_spec = payload["full_evidence"]["book_evidence"]
    drawdown_spec_path = (
        REPO / payload["full_evidence"]["book_drawdown"]["simulation_specification_path"]
    )
    snapshot_path = REPO / book_spec["book_return_snapshot_path"]
    if _sha256(snapshot_path) != book_spec["book_return_snapshot_sha256"]:
        raise SystemExit("the existing-book snapshot moved since the reservation bound it")
    snapshot = pd.read_parquet(snapshot_path)
    snapshot.index = pd.Index([pd.Timestamp(d).date() for d in snapshot.index])
    sleeves = {name: snapshot[name].astype("float64") for name in book_spec["book_series_ids"]}
    book = snapshot["book"].astype("float64")
    candidate_days = pd.Series(
        net_returns.to_numpy(dtype="float64"),
        index=pd.Index([pd.Timestamp(d).date() for d in net_returns.index]),
    )
    first, last = candidate_days.index.min(), candidate_days.index.max()
    calendar = snapshot.index[(snapshot.index >= first) & (snapshot.index <= last)]
    candidate = candidate_days.reindex(calendar).fillna(0.0)
    diversification = evaluation.diversification_evidence(candidate, sleeves, book=book)

    spec = json.loads(drawdown_spec_path.read_text(encoding="utf-8"))
    weight = float(book_spec["candidate_weight"])
    aligned = pd.concat([candidate.rename("candidate"), book.rename("book")], axis=1).dropna()
    study_spec = importlib.util.spec_from_file_location(
        "narrative_book_drawdown", REPO / "scripts" / "analyze_current_book_drawdown.py"
    )
    assert study_spec is not None and study_spec.loader is not None
    study = importlib.util.module_from_spec(study_spec)
    study_spec.loader.exec_module(study)
    without = aligned["book"].to_numpy(dtype="float64")
    with_candidate = (1.0 - weight) * without + weight * aligned["candidate"].to_numpy(
        dtype="float64"
    )
    drawdown: dict[str, Any] = {
        "specification": str(drawdown_spec_path.relative_to(REPO)),
        "aligned_days": len(aligned),
        "candidate_weight": weight,
        "drift_convention": "zero_drift_as_published",
        "generator": "circular_block_bootstrap",
        "paths": int(spec["paths"]),
        "horizon_calendar_days": int(spec["horizon_calendar_days"]),
        "block_days": int(study.PRIMARY_BLOCK_DAYS),
        "seed": int(spec["seeds"]["bootstrap"]),
    }
    for label, series in (("without_candidate", without), ("with_candidate", with_candidate)):
        centered = series - float(np.mean(series))
        drawdown[label] = study.circular_block_bootstrap(
            centered,
            paths=int(spec["paths"]),
            horizon_days=int(spec["horizon_calendar_days"]),
            block_days=int(study.PRIMARY_BLOCK_DAYS),
            seed=int(spec["seeds"]["bootstrap"]),
        )
    drawdown["expected_max_drawdown_delta"] = (
        drawdown["with_candidate"]["expected_max_drawdown"]
        - drawdown["without_candidate"]["expected_max_drawdown"]
    )
    drawdown["p95_max_drawdown_delta"] = (
        drawdown["with_candidate"]["p95_max_drawdown"]
        - drawdown["without_candidate"]["p95_max_drawdown"]
    )
    return {
        "snapshot": {
            "path": book_spec["book_return_snapshot_path"],
            "sha256": book_spec["book_return_snapshot_sha256"],
            "calendar": "UTC calendar days; the candidate is 0.0 on non-sessions",
        },
        "diversification": diversification,
        "drawdown": drawdown,
    }


def _evaluate_declared_diagnostics(
    reservation: Path,
    *,
    primary_decision_path_sha256: str,
    active: list[portfolio.ActiveCohort],
    panel: inputs.DailyPanel,
    spy: inputs.DailyPanel,
    calendar: inputs.SessionCalendar,
    start_pos: int,
    end_pos: int,
) -> dict[str, Any]:
    """Every scenario the reservation declared, re-simulated on the sealed decisions.

    The declared assumptions are read back from the reservation and the execution scenario
    manifest it binds; each result is hashed and bound to the primary decision path, in the
    exact sealed shape ``_validate_diagnostic_scenarios`` checks. Nothing is selected: every
    declared scenario is evaluated and every one is published.
    """
    payload = json.loads(reservation.read_text(encoding="utf-8"))

    def _evaluate(scenario: dict[str, Any]) -> dict[str, Any]:
        assumptions = dict(scenario["assumptions"])
        if scenarios.canonical_sha256(assumptions) != scenario["assumptions_sha256"]:
            raise SystemExit(f"declared scenario {scenario['scenario_id']} hash mismatch")
        evaluated = scenarios.evaluate_scenario(
            assumptions,
            active=active,
            panel=panel,
            spy=spy,
            calendar=calendar,
            start_pos=start_pos,
            end_pos=end_pos,
        )
        outcome = {
            "net": evaluated["net"],
            "turnover_total": evaluated["turnover_total"],
            "cost_drag_bps_per_turnover": evaluated["cost_drag_bps_per_turnover"],
            "mean_stock_gross": evaluated["mean_stock_gross"],
            "mean_hedge_abs_weight": evaluated["mean_hedge_abs_weight"],
            "events": evaluated["events"],
            "series_sha256": evaluated["series_sha256"],
        }
        return {
            "scenario_id": scenario["scenario_id"],
            "assumptions": assumptions,
            "assumptions_sha256": scenario["assumptions_sha256"],
            "result": outcome,
            "result_sha256": scenarios.canonical_sha256(outcome),
            "primary_decision_path_sha256": primary_decision_path_sha256,
        }

    declared = payload.get("diagnostic_scenarios") or {}
    out: dict[str, Any] = {
        "diagnostic_scenarios": {
            scenario_class: [_evaluate(s) for s in declared.get(scenario_class, [])]
            for scenario_class in (
                "cost_stress_scenarios",
                "execution_stress_scenarios",
                "capacity_scenarios",
            )
        },
        "execution_dimensions": {},
    }
    execution = payload["full_evidence"]["execution_evidence"]
    manifest = json.loads((REPO / execution["scenario_manifest_path"]).read_text(encoding="utf-8"))
    for dimension in execution["applicable_dimensions"]:
        out["execution_dimensions"][dimension] = [_evaluate(s) for s in manifest[dimension]]
    out["scenarios_evaluated"] = sum(len(v) for v in out["diagnostic_scenarios"].values()) + sum(
        len(v) for v in out["execution_dimensions"].values()
    )
    return out


def _record_identity(section: str, net_returns: pd.Series, reservation: Path) -> dict[str, Any]:
    """Spend the identity: one append-only ledger record bound to its reservation.

    The per-period statistics are recomputed from the daily net returns the evaluation used
    (sample moments, non-excess kurtosis), the same convention the forward-evidence evaluator
    records, so the ledger row and the packet describe one series.
    """
    from scipy.stats import kurtosis as scipy_kurtosis
    from scipy.stats import skew as scipy_skew

    from alphaforge.validation.experiments import ExperimentLog

    values = net_returns.to_numpy(dtype="float64")
    values = values[np.isfinite(values)]
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    per_period = float(np.mean(values) / std) if std > 0 else 0.0
    ledger = ExperimentLog(LEDGER)
    record = ledger.record(
        trial_config(section),
        sharpe_ann=per_period * (252.0**0.5),
        sharpe_per_period=per_period,
        n_obs=int(values.size),
        skew=float(scipy_skew(values, bias=True)) if values.size > 2 else 0.0,
        kurtosis=float(scipy_kurtosis(values, fisher=False, bias=True)) if values.size > 3 else 3.0,
        now_ms=int(time.time() * 1000),
        reservation_path=reservation,
    )
    return {"ledger": str(LEDGER.relative_to(REPO)), "config_hash": record.config_hash}


def run_batch(
    reservations: dict[str, Path],
    *,
    max_cohorts: int | None = None,
    lake: Path | None = None,
) -> Path:
    """The atomic batch: both identities run, PBO on both, then both results and both ledger rows.

    Order of writes is the protocol's interim-result rule made concrete: every member's curve is
    computed and the PBO matrix is sealed before any member's result document or ledger record
    exists. Each member is charged to the family and the union; the matrix receipt binds both.
    """
    from alphaforge.validation.pbo import pbo_cscv

    if set(reservations) != set(SECTIONS):
        raise SystemExit("a batch run needs one reservation per section: " + ", ".join(SECTIONS))
    runs: dict[str, dict[str, Any]] = {}
    for section in SECTIONS:
        runs[section] = run(
            "oos",
            section=section,
            max_cohorts=max_cohorts,
            reservation=reservations[section],
            lake=lake,
            defer_result=True,
        )
    frame = pd.concat(
        {section: runs[section]["net_returns"] for section in SECTIONS}, axis=1
    ).dropna(how="any")
    columns = [
        runs[s]["result"]["authorization"]["validation"]["hypothesis_identity"] for s in SECTIONS
    ]
    pbo = pbo_cscv(
        frame.to_numpy(dtype="float64"),
        n_splits=PBO_N_SPLITS,
        max_combinations=PBO_MAX_COMBINATIONS,
        seed=PBO_SEED,
    )
    matrix: dict[str, Any] = {
        "schema": "canli.alphac-identity-batch-matrix-receipt.v1",
        "author": "Arhan Canli",
        "batch_id": BATCH_ID,
        "identity_columns": columns,
        "sections": list(SECTIONS),
        "aligned_observations": len(frame),
        "return_alignment": "intersection_without_internal_missing_rows",
        "n_splits": PBO_N_SPLITS,
        "maximum_combinations": PBO_MAX_COMBINATIONS,
        "seed": PBO_SEED,
        "pbo": float(pbo.pbo),
        "combinations_evaluated": pbo.n_combinations,
        "claim_boundary": (
            "Probability of backtest overfitting over the batch's two counted columns, computed "
            "exactly as frozen in the reservations. Two columns make a coarse matrix; the figure "
            "is reported as computed and never rounded to zero."
        ),
    }
    matrix["content_hash"] = _content_hash(matrix)
    matrix_path = BATCH_MATRIX_PATH
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(json.dumps(matrix, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for section in SECTIONS:
        result = runs[section]["result"]
        result["batch"] = {
            "batch_id": BATCH_ID,
            "matrix_receipt": str(matrix_path.relative_to(REPO)),
            "matrix_content_hash": matrix["content_hash"],
            "pbo": matrix["pbo"],
        }
        result["ledger_recorded"] = True
        result["ledger_record"] = _record_identity(
            section, runs[section]["net_returns"], reservations[section]
        )
        result["content_hash"] = _content_hash(result)
        (runs[section]["out"] / "result.json").write_text(
            json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"[batch] PBO {matrix['pbo']:.4f} over {len(frame)} aligned days -> {matrix_path}")
    return matrix_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--window", choices=sorted(WINDOWS), default=None)
    ap.add_argument("--section", choices=sorted(SECTIONS), default="item1a")
    ap.add_argument("--max-cohorts", type=int, default=None, help="smoke runs only")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--reservation", type=Path, default=None)
    ap.add_argument("--lake", type=Path, default=None, help="price lake (default: the full one)")
    ap.add_argument(
        "--batch",
        action="store_true",
        help="run BOTH sections out of sample as one atomic batch (reservations per section)",
    )
    ap.add_argument("--reservation-item1a", type=Path, default=None)
    ap.add_argument("--reservation-item7", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.batch:
        if args.reservation_item1a is None or args.reservation_item7 is None:
            ap.error("--batch needs --reservation-item1a and --reservation-item7")
        run_batch(
            {"item1a": args.reservation_item1a, "item7": args.reservation_item7},
            max_cohorts=args.max_cohorts,
            lake=args.lake,
        )
        return 0
    if args.window is None:
        ap.error("--window is required unless --batch")
    if args.window == "oos" and args.reservation is not None:
        # A single out-of-sample member cannot exist outside its batch: the reservation's batch
        # block names both, and the ledger row is written only by the batch runner.
        ap.error("the out-of-sample window runs only as --batch; single-member runs are refused")
    run(
        args.window,
        section=args.section,
        max_cohorts=args.max_cohorts,
        out_root=args.out,
        reservation=args.reservation,
        lake=args.lake,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
