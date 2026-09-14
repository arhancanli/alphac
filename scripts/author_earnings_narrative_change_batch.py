#!/usr/bin/env python3
"""Author, validate and audit the earnings-narrative-change identity batch, before any return.

WHY. The v2 protocol's acceptance test is that every gate can be answered from pre-result bytes.
This script writes those bytes for the family's two pre-registered identities (10-K Item 1A,
10-K Item 7) as one atomic batch: the sealed batch registry, the frozen evidence files (the
existing book's daily returns and its bottom-decile stress mask, the drawdown simulation
specification, the overlay configuration, the execution scenario manifest), the two
reservations with every supplemental scenario declared, and then it runs the in-force validator
and the filled-reservation audit on each and refuses to leave anything on disk that fails.

It reads the existing sleeves' curves (to snapshot the book the candidate will be measured
against) and no candidate return. It spends no identity: reserving is what the validator
records; spending happens only when the batch runner writes the ledger rows after the run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from alphaforge.portfolio.book import combine_book  # noqa: E402
from alphaforge.research.narrative_change.scenarios import canonical_sha256  # noqa: E402
from alphaforge.validation.experiments import hypothesis_hash  # noqa: E402
from alphaforge.validation.trial_reservation import (  # noqa: E402
    IDENTITY_BATCH_DIR,
    IDENTITY_BATCH_SCHEMA,
    RESERVATION_DIR,
    RESERVATION_FILENAME,
    _observed_content_hash,
    batch_content_hash,
    validate_reservation,
)

BATCH_ID: Final[str] = "earnings_narrative_change_batch_1"
FAMILY: Final[str] = "earnings_narrative_change"
EVIDENCE_DIR: Final[Path] = REPO / IDENTITY_BATCH_DIR / BATCH_ID
TEMPLATE: Final[str] = "config/forward_full_evidence_reservation_v2_template.json"
RECEIPT: Final[str] = "config/forward_full_evidence_reservation_v2_promotion.json"
CONTRACT: Final[str] = "config/sleeve_admission_contract.json"
TRIAL_POLICY: Final[str] = "config/trial_accounting.json"
V7_RECEIPT: Final[str] = "config/admission_v7_promotion.json"
RUNNER: Final[str] = "scripts/run_earnings_narrative_change_v1.py"
PAPER_STATE: Final[Path] = REPO / "scripts" / "paper_trading_state.py"
VINTAGE_PROBE: Final[str] = "artifacts/probe/cpi_surprise_size/equity.parquet"
CANDIDATE_WEIGHT: Final[float] = 0.10
CAPITAL_POINTS: Final[tuple[float, ...]] = (500_000.0, 5_000_000.0, 25_000_000.0)
PBO: Final[dict[str, int]] = {"n_splits": 16, "maximum_combinations": 12870, "seed": 20260914}
EXCUSE_EVIDENCE: Final[dict[str, tuple[str, str]]] = {
    "queue_position": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "Every fill is the XNYS opening auction print; there is no continuous-book queue to "
        "model. The partial-fill and rejected-order dimensions carry the fill risk.",
    ),
    "stale_quotes": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "Daily bars from the point-in-time lake, one open per session; a stale intraday quote "
        "cannot enter a decision. The missing-opens dimension carries the absent-print case.",
    ),
    "holidays": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "The session calendar is derived from SPY's observed bars, so every exchange holiday is "
        "a non-session by construction; entry is the second session open after month-end.",
    ),
    "corporate_actions": (
        "artifacts/audit/split_adjustment_direction.json",
        "Splits and dividends are applied by the point-in-time adjustment engine whose "
        "direction was audited lake by lake on 2026-09-14; the input manifest binds the "
        "adjustment basis. No separate execution scenario can vary a corporate action.",
    ),
    "futures_rolls_and_limits": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "Listed US equities and one ETF hedge only; no futures contract is traded.",
    ),
    "option_surfaces_assignment_and_gaps": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "No option is traded or written.",
    ),
    "venue_and_counterparty_risk": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "Listed equities on the primary exchange in a paper account; there is no bilateral "
        "counterparty and no venue choice to stress. The exchange-outage dimension carries the "
        "venue-unavailable case.",
    ),
    "crowding": (
        "docs/design/PREREG_EARNINGS_NARRATIVE_CHANGE.md",
        "No crowding data source is part of the pre-registration; the liquidity and impact "
        "dimensions carry the capacity consequence of crowded names at each capital point.",
    ),
    "operational_kill_switches": (
        "docs/design/DRAWDOWN_CONTROL_V1_PROTOCOL.md",
        "The kill switch is the declared book-level drawdown ladder, measured and declared at "
        "the book, not per sleeve; a research replay cannot exercise it.",
    ),
}
# Every applicable dimension carries three scenarios in the vocabulary of
# alphaforge.research.narrative_change.scenarios; every set differs from the baseline on a
# measurable number, so each can fail (the filled-reservation audit checks exactly that).
EXECUTION_SCENARIOS: Final[dict[str, list[dict[str, Any]]]] = {
    "commissions": [{"stock_bps": 20.0}, {"stock_bps": 30.0}, {"stock_bps": 45.0}],
    "bid_ask_spread": [
        {"stock_bps": 25.0, "spy_bps": 2.0},
        {"stock_bps": 35.0, "spy_bps": 3.0},
        {"stock_bps": 55.0, "spy_bps": 5.0},
    ],
    "slippage": [{"latency_bps": 5.0}, {"latency_bps": 10.0}, {"latency_bps": 25.0}],
    "nonlinear_market_impact": [
        {"impact_bps_per_sqrt_participation": 10.0, "capital_usd": 5_000_000.0},
        {"impact_bps_per_sqrt_participation": 25.0, "capital_usd": 5_000_000.0},
        {"impact_bps_per_sqrt_participation": 50.0, "capital_usd": 5_000_000.0},
    ],
    "latency": [
        {"latency_bps": 2.0, "label": "one_minute"},
        {"latency_bps": 5.0, "label": "five_minutes"},
        {"latency_bps": 15.0, "label": "open_missed_to_first_print"},
    ],
    "partial_fills": [{"fill_ratio": 0.9}, {"fill_ratio": 0.75}, {"fill_ratio": 0.5}],
    "rejected_orders": [
        {"reject_fraction": 0.02, "seed": 101},
        {"reject_fraction": 0.05, "seed": 102},
        {"reject_fraction": 0.10, "seed": 103},
    ],
    "cancelled_orders": [
        {"reject_fraction": 0.01, "seed": 201, "label": "cancelled_at_open"},
        {"reject_fraction": 0.03, "seed": 202, "label": "cancelled_at_open"},
        {"reject_fraction": 0.06, "seed": 203, "label": "cancelled_at_open"},
    ],
    "missing_opens": [
        {"missing_open_fraction": 0.01, "seed": 301},
        {"missing_open_fraction": 0.03, "seed": 302},
        {"missing_open_fraction": 0.05, "seed": 303},
    ],
    "exchange_outages": [
        {"outage_fraction": 0.004, "seed": 401},
        {"outage_fraction": 0.01, "seed": 402},
        {"outage_fraction": 0.02, "seed": 403},
    ],
    "borrow_availability": [
        {"borrow_unavailable_fraction": 0.10, "seed": 501},
        {"borrow_unavailable_fraction": 0.25, "seed": 502},
        {"borrow_unavailable_fraction": 0.50, "seed": 503},
    ],
    "borrow_fees": [{"borrow_annual": 0.06}, {"borrow_annual": 0.10}, {"borrow_annual": 0.20}],
    "borrow_recalls": [
        {"borrow_recall_sessions": 21, "borrow_recall_fraction": 0.25, "seed": 601},
        {"borrow_recall_sessions": 10, "borrow_recall_fraction": 0.25, "seed": 602},
        {"borrow_recall_sessions": 5, "borrow_recall_fraction": 0.50, "seed": 603},
    ],
    "financing": [
        {"financing_annual": 0.02},
        {"financing_annual": 0.04},
        {"financing_annual": 0.06},
    ],
    "delistings": [
        {"delisting_haircut": 0.10},
        {"delisting_haircut": 0.25},
        {"delisting_haircut": 0.50},
    ],
    "turnover": [
        {"stock_bps": 25.0, "label": "turnover_cost_sensitivity"},
        {"stock_bps": 40.0, "label": "turnover_cost_sensitivity"},
        {"stock_bps": 60.0, "label": "turnover_cost_sensitivity"},
    ],
    "liquidity": [
        {"adv_participation_cap_bps": 10.0, "capital_usd": 5_000_000.0},
        {"adv_participation_cap_bps": 5.0, "capital_usd": 5_000_000.0},
        {"adv_participation_cap_bps": 1.0, "capital_usd": 5_000_000.0},
    ],
}
BASELINE: Final[dict[str, Any]] = {"stock_bps": 15.0, "spy_bps": 1.0, "borrow_annual": 0.03}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _scenario(scenario_id: str, assumptions: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "assumptions": assumptions,
        "assumptions_sha256": canonical_sha256(assumptions),
    }


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot_existing_book() -> tuple[Path, Path, list[str]]:
    """The four current sleeves' daily returns and the book they form, frozen to a file.

    Exactly the aggregation the published paper composite declares (scripts/paper_trading_state.py:
    fixed equal weights, no book-level volatility target, the strategic tilt), so the
    diversification evidence is measured against the book that actually trades.
    """
    paper = _load_module(PAPER_STATE, "narrative_batch_paper_state")
    sleeves = [
        paper.load_wf(paper.EQUITY_WF),
        paper.load_wf(paper.CRYPTO_WF),
        paper.load_wf(paper.MF_WF),
        paper.load_probe_curve(paper.VINTAGE_WF, VINTAGE_PROBE),
    ]
    book = combine_book(
        sleeves,
        scheme=paper.BOOK_AGGREGATION_SCHEME,
        fixed_weights=paper.BOOK_WEIGHTS,
        vol_target_ann=paper.BOOK_LEVEL_VOL_TARGET_ANN,
        trading_days=365,
        strategic_tilt_pct=paper.STRATEGIC_TILT_PCT,
        strategic_tilt_market=paper.market_factor_by_epochday(),
    )
    dates = [dt.date(1970, 1, 1) + dt.timedelta(days=int(d)) for d in book.days]
    frame = pd.DataFrame(
        {name: np.asarray(book.sleeve_returns[name], dtype="float64") for name in book.names},
        index=pd.Index(dates, name="date"),
    )
    frame["book"] = np.asarray(book.book_returns, dtype="float64")
    snapshot = EVIDENCE_DIR / "existing_book_snapshot.parquet"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(snapshot, index=True)
    threshold = float(np.quantile(frame["book"].to_numpy(dtype="float64"), 0.10))
    mask_dates = [
        d.isoformat() for d, v in zip(frame.index, frame["book"], strict=True) if v <= threshold
    ]
    mask = _write_json(
        EVIDENCE_DIR / "diversification_stress_mask.json",
        {
            "rule": (
                "bottom decile of the existing equal-weight ALPHAC book's daily returns on the "
                "frozen snapshot (the pre-registration's predeclared stress mask)"
            ),
            "threshold_daily_return": threshold,
            "dates": mask_dates,
            "snapshot_sha256": _sha256(snapshot),
        },
    )
    return snapshot, mask, list(book.names)


def frozen_evidence_files() -> dict[str, Path]:
    """The specification files a reservation binds by hash, written once for the batch."""
    paper = _load_module(PAPER_STATE, "narrative_batch_paper_state_meta")
    files: dict[str, Path] = {}
    files["drawdown_spec"] = _write_json(
        EVIDENCE_DIR / "book_drawdown_simulation_specification.json",
        {
            "protocol": "docs/design/CURRENT_BOOK_DRAWDOWN_STUDY_PROTOCOL.md",
            "generator": "scripts/analyze_current_book_drawdown.py",
            "paths": 10000,
            "horizon_calendar_days": 730,
            "models": ["circular_moving_block_bootstrap_63", "correlation_regime_stress_0.50"],
            "seeds": {"bootstrap": 20260823, "correlation_regime": 20260824},
            "candidate_weight": CANDIDATE_WEIGHT,
            "candidate_funding": "pro rata from the four current equal-quarter sleeves",
            "statistics": ["expected_maximum_drawdown", "p95_maximum_drawdown"],
            "candidate_series": (
                "the identity's out-of-sample net daily returns, aligned to the snapshot"
            ),
        },
    )
    files["overlay"] = _write_json(
        EVIDENCE_DIR / "overlay_configuration.json",
        {"source": "scripts/paper_trading_state.py", **paper.book_aggregation_metadata()},
    )
    manifest: dict[str, list[dict[str, Any]]] = {}
    for dimension, sets in EXECUTION_SCENARIOS.items():
        manifest[dimension] = [
            _scenario(f"{dimension}_{index}", dict(assumptions))
            for index, assumptions in enumerate(sets, start=1)
        ]
    files["execution_manifest"] = _write_json(
        EVIDENCE_DIR / "execution_scenario_manifest.json", manifest
    )
    return files


def diagnostic_scenarios() -> dict[str, list[dict[str, Any]]]:
    return {
        "cost_stress_scenarios": [
            _scenario("cost_baseline", dict(BASELINE)),
            _scenario(
                "cost_prereg_stress", {"stock_bps": 30.0, "spy_bps": 2.0, "borrow_annual": 0.06}
            ),
            _scenario("cost_triple", {"stock_bps": 45.0, "spy_bps": 3.0, "borrow_annual": 0.09}),
        ],
        "execution_stress_scenarios": [
            _scenario("adverse_open", {"latency_bps": 10.0, "fill_ratio": 0.75, "seed": 701}),
            _scenario(
                "thin_market",
                {"missing_open_fraction": 0.03, "reject_fraction": 0.05, "seed": 702},
            ),
            _scenario(
                "hard_to_borrow",
                {
                    "borrow_unavailable_fraction": 0.25,
                    "borrow_recall_sessions": 10,
                    "borrow_recall_fraction": 0.25,
                    "borrow_annual": 0.10,
                    "seed": 703,
                },
            ),
        ],
        "capacity_scenarios": [
            _scenario(
                f"capacity_{int(capital):d}",
                {
                    "capital_usd": capital,
                    "impact_bps_per_sqrt_participation": 25.0,
                    "adv_participation_cap_bps": 100.0,
                },
            )
            for capital in CAPITAL_POINTS
        ],
    }


def governance_epoch(ordinal: int) -> dict[str, Any]:
    contract = json.loads((REPO / CONTRACT).read_text(encoding="utf-8"))
    return {
        "admission_contract_path": CONTRACT,
        "admission_contract_sha256": _sha256(REPO / CONTRACT),
        "trial_policy_path": TRIAL_POLICY,
        "trial_policy_sha256": _sha256(REPO / TRIAL_POLICY),
        "promotion_receipt_path": V7_RECEIPT,
        "promotion_receipt_sha256": _sha256(REPO / V7_RECEIPT),
        "effective_contract_hash": contract["prospective_scope"]["effective_contract_content_hash"],
        "reservation_ordinal": ordinal,
    }


def build(*, reserved_at: str) -> dict[str, Any]:
    runner = _load_module(REPO / RUNNER, "narrative_runner_for_authoring")
    template = json.loads((REPO / TEMPLATE).read_text(encoding="utf-8"))
    contract = json.loads((REPO / CONTRACT).read_text(encoding="utf-8"))
    thresholds = contract["thresholds"]
    policy = contract["diversification_evidence_policy"]
    promote = _load_module(
        REPO / "scripts" / "promote_forward_full_evidence_reservation_v2.py",
        "narrative_batch_promotion",
    )
    first_ordinal = int(promote.next_governed_ordinal(REPO))

    snapshot, mask, series_ids = snapshot_existing_book()
    files = frozen_evidence_files()
    sections = list(runner.SECTIONS)
    configs = [runner.trial_config(section) for section in sections]
    hashes = [hypothesis_hash(config) for config in configs]
    registry: dict[str, Any] = {
        "schema": IDENTITY_BATCH_SCHEMA,
        "batch_id": BATCH_ID,
        "family_trial_account": FAMILY,
        "identity_configs": configs,
        "identity_hashes": hashes,
        "batch_content_hash": batch_content_hash(BATCH_ID, FAMILY, hashes),
        "pbo_columns": len(hashes),
        "all_identities_reserved_before_first_return": True,
        "interim_result_access_forbidden": True,
        "sealed_at": reserved_at,
    }
    registry["content_hash"] = _observed_content_hash(registry)
    registry_path = _write_json(REPO / IDENTITY_BATCH_DIR / f"{BATCH_ID}.json", registry)

    dimensions = list(contract["execution_dimensions"])
    applicable = [d for d in dimensions if d in EXECUTION_SCENARIOS]
    excused = {
        d: {
            "reason": EXCUSE_EVIDENCE[d][1],
            "evidence_path": EXCUSE_EVIDENCE[d][0],
            "evidence_sha256": _sha256(REPO / EXCUSE_EVIDENCE[d][0]),
        }
        for d in dimensions
        if d not in EXECUTION_SCENARIOS
    }
    missing = set(dimensions) - set(applicable) - set(excused)
    if missing:
        raise SystemExit(
            "execution dimensions neither applicable nor excused: " + ", ".join(sorted(missing))
        )

    written: dict[str, Any] = {"registry": str(registry_path.relative_to(REPO)), "identities": {}}
    for position, section in enumerate(sections):
        spec = runner.SECTIONS[section]
        profile = spec["profile"]
        pairs_result = spec["pairs"].with_name(spec["pairs"].stem + "_result.json")
        if section == "item1a":
            pairs_result = spec["pairs"].parent / "pairs_result.json"
        reservation: dict[str, Any] = {
            "schema": "canli.alphac-forward-trial-reservation.v1",
            "status": "RETURN_IDENTITY_RESERVED",
            "family_trial_account": FAMILY,
            "return_identity_id": profile,
            "hypotheses_spent": 1,
            "reserved_at": reserved_at,
            "trial_config": configs[position],
            "hypothesis_identity": hashes[position],
            "packet_public_path": f"/glassbox/trial-packets/{profile}.json",
            "paper_public_path": "/research/" + profile.replace("_", "-"),
            "governance_epoch": governance_epoch(first_ordinal + position),
            "evidence": {
                "preregistration": {
                    "path": str(spec["prereg"].relative_to(REPO)),
                    "sha256": _sha256(spec["prereg"]),
                },
                "input_data_manifest": {
                    "path": str(pairs_result.relative_to(REPO)),
                    "sha256": _sha256(pairs_result),
                },
                "runner": {"path": RUNNER, "sha256": _sha256(REPO / RUNNER)},
                "python_project": {
                    "path": "pyproject.toml",
                    "sha256": _sha256(REPO / "pyproject.toml"),
                },
                "locked_environment": {"path": "uv.lock", "sha256": _sha256(REPO / "uv.lock")},
            },
            "identity_batch": {
                "batch_id": BATCH_ID,
                "family_trial_account": FAMILY,
                "identity_configs": configs,
                "identity_hashes": hashes,
                "batch_content_hash": registry["batch_content_hash"],
                "registry_path": str(registry_path.relative_to(REPO)),
                "all_identities_reserved_before_first_return": True,
                "interim_result_access_forbidden": True,
                "pbo_columns": len(hashes),
            },
            "diagnostic_scenarios": diagnostic_scenarios(),
            "full_evidence": {
                "template_path": TEMPLATE,
                "template_sha256": _sha256(REPO / TEMPLATE),
                "promotion_receipt_path": RECEIPT,
                "promotion_receipt_sha256": _sha256(REPO / RECEIPT),
                "primary_estimator": template["primary_estimator"],
                "pbo_matrix": {
                    "identity_columns": hashes,
                    "return_alignment": template["pbo_matrix"]["return_alignment"],
                    "n_splits": PBO["n_splits"],
                    "maximum_combinations": PBO["maximum_combinations"],
                    "seed": PBO["seed"],
                    "undefined_policy": template["pbo_matrix"]["undefined_policy"],
                },
                "diagnostic_policy": {
                    "selection_permitted": False,
                    "all_scenarios_must_publish": True,
                    "baseline_scenario_id": "cost_baseline",
                    "minimum_capacity_points": thresholds["capacity_curve_min_points"],
                    "required_capacity_usd": thresholds["capacity_usd_min"],
                    "scenario_hashes_frozen_before_returns": True,
                },
                "book_evidence": {
                    "book_return_snapshot_path": str(snapshot.relative_to(REPO)),
                    "book_return_snapshot_sha256": _sha256(snapshot),
                    "book_series_ids": series_ids,
                    "candidate_weight": CANDIDATE_WEIGHT,
                    "alignment_rule": template["book_evidence"]["alignment_rule"],
                    "stress_mask_path": str(mask.relative_to(REPO)),
                    "stress_mask_sha256": _sha256(mask),
                    "bootstrap": {
                        "samples": policy["default_bootstrap_samples"],
                        "block_size": policy["default_block_size"],
                        "seed": policy["default_seed"],
                        "one_sided_confidence": policy["confidence_level_one_sided"],
                    },
                    "leave_one_period_definition": "calendar year of the out-of-sample interval",
                },
                "book_drawdown": {
                    "simulation_specification_path": str(files["drawdown_spec"].relative_to(REPO)),
                    "simulation_specification_sha256": _sha256(files["drawdown_spec"]),
                    "expected_maximum_drawdown_required": True,
                    "p95_maximum_drawdown_required": True,
                    "overlay_configuration_path": str(files["overlay"].relative_to(REPO)),
                    "overlay_configuration_sha256": _sha256(files["overlay"]),
                },
                "execution_evidence": {
                    "applicable_dimensions": applicable,
                    "not_applicable_dimensions": excused,
                    "minimum_scenarios_per_applicable_dimension": thresholds[
                        "minimum_execution_scenarios_per_dimension"
                    ],
                    "scenario_manifest_path": str(files["execution_manifest"].relative_to(REPO)),
                    "scenario_manifest_sha256": _sha256(files["execution_manifest"]),
                },
                "data_and_environment": {
                    "point_in_time_data_manifest_path": str(pairs_result.relative_to(REPO)),
                    "point_in_time_data_manifest_sha256": _sha256(pairs_result),
                    "runner_path": RUNNER,
                    "runner_sha256": _sha256(REPO / RUNNER),
                    "project_sha256": _sha256(REPO / "pyproject.toml"),
                    "lockfile_sha256": _sha256(REPO / "uv.lock"),
                    "input_snapshot_required_before_first_execution_leg": True,
                    "public_redistribution_rights_established": False,
                },
            },
        }
        path = REPO / RESERVATION_DIR / profile / RESERVATION_FILENAME
        # Validate BEFORE writing, so a failing reservation never sits on disk where a later
        # sibling could count it; the validator requires earlier siblings on disk, so the
        # order is the batch order.
        validation = validate_reservation(reservation, trial_config=configs[position], repo=REPO)
        _write_json(path, reservation)
        written["identities"][profile] = {
            "reservation": str(path.relative_to(REPO)),
            "ordinal": validation["governance_epoch"]["reservation_ordinal"],
            "validation_status": validation["status"],
            "batch_position": validation["identity_batch"]["position"],
        }
    audit_module = _load_module(
        REPO / "scripts" / "audit_forward_full_evidence_reservation.py", "narrative_batch_audit"
    )
    for profile, entry in written["identities"].items():
        document = audit_module.audit(REPO / entry["reservation"], REPO)
        receipt = _write_json(EVIDENCE_DIR / f"{profile}_filled_reservation_audit.json", document)
        entry["audit_status"] = document["status"]
        entry["disposition_ceiling"] = document["disposition_ceiling"]
        entry["audit_receipt"] = str(receipt.relative_to(REPO))
        if document["status"] != "SATISFIABLE_RETURN_BLIND":
            raise SystemExit(
                f"{profile}: reservation not satisfiable as written: "
                + "; ".join(document["failures"])
            )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reserved-at", default=dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    )
    args = parser.parse_args(argv)
    written = build(reserved_at=args.reserved_at)
    print(json.dumps(written, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
