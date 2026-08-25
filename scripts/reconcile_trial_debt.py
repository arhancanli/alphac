#!/usr/bin/env python3
"""Reconcile persisted historical return configurations that bypassed the experiment ledger.

The reconciliation is source-bound and deliberately conservative: every named parameter
configuration that produced a reported return stream is charged, even when two settings happened
to produce identical summary metrics. Rounded summaries and copied harnesses are not sufficient
evidence of economic identity. Re-running is unnecessary and could change historical evidence.

Default mode is read-only. ``--apply`` appends idempotent forensic records to the active ledger and
writes a reconciliation artifact. No record is deleted or rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alphaforge.analytics.metrics import daily_returns  # noqa: E402
from alphaforge.validation.experiments import (  # noqa: E402
    ExperimentLog,
    ExperimentUnion,
    config_hash,
)
from alphaforge.validation.probe_ledger import record_probe_trial  # noqa: E402

ACTIVE_LEDGER: Final[Path] = REPO / "var" / "experiments.jsonl"
CONSTRUCTION_ROOT: Final[Path] = REPO / "artifacts" / "sweep" / "alphamax_construction"
CONSTRUCTION_MANIFEST: Final[Path] = CONSTRUCTION_ROOT / "arms.json"
WEIGHTING_REPORT: Final[Path] = REPO / "artifacts" / "probe" / "alphamax_weighting" / "report.json"
VRP_REPORT: Final[Path] = REPO / "artifacts" / "exp2" / "20260625T094710Z" / "exp2_metrics.json"
HYST_REPORT: Final[Path] = REPO / "artifacts" / "probe" / "alphamax_hyst_live" / "report.json"
TURNOVER_REPORT: Final[Path] = REPO / "artifacts" / "probe" / "alphamax_turnover" / "report.json"
ARP_REPORT: Final[Path] = REPO / "artifacts" / "sweep" / "alphatrend_arp" / "report.json"
BREADTH_REPORT: Final[Path] = REPO / "artifacts" / "sweep" / "alphatrend_breadth" / "report.json"
OUT: Final[Path] = REPO / "artifacts" / "audit" / "trial_debt_reconciliation.json"
AUDIT_NOW_MS: Final[int] = 1_786_924_800_000  # 2026-08-17T00:00:00Z
EXPECTED_CONSTRUCTION_ARMS: Final[int] = 8
EXPECTED_WEIGHTING_CELLS: Final[int] = 48
EXPECTED_SUMMARY_IDENTITIES: Final[int] = 70
EXPECTED_TOTAL_IDENTITIES: Final[int] = 78


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _construction_candidates() -> list[dict[str, Any]]:
    manifest = json.loads(CONSTRUCTION_MANIFEST.read_text())
    candidates: list[dict[str, Any]] = []
    for arm, evidence in sorted(manifest.items()):
        run_dir = CONSTRUCTION_ROOT / f"wf_{arm}"
        metadata_path = run_dir / "walkforward.json"
        equity_path = run_dir / "equity.parquet"
        metadata = json.loads(metadata_path.read_text())
        trial_config = metadata.get("trial_config") or metadata["config"]
        frame = pd.read_parquet(equity_path)
        equity = pd.Series(
            frame["equity"].to_numpy(dtype="float64"),
            index=pd.Index(frame["ts"].to_numpy(dtype="int64"), name="ts"),
        )
        returns = daily_returns(equity)
        candidates.append(
            {
                "kind": "complete_walkforward",
                "probe": "forensic_alphamax_construction",
                "variant": arm,
                "config": {
                    "variant": arm,
                    "parameters": evidence["params"],
                    "source_trial_config_hash": config_hash(trial_config),
                    "source_artifact": str(metadata_path.relative_to(REPO)),
                    "source_artifact_sha256": _sha256(metadata_path),
                    "historical_accounting_correction": True,
                },
                "returns": returns,
                "source": metadata_path,
            }
        )
    if len(candidates) != EXPECTED_CONSTRUCTION_ARMS:
        raise RuntimeError(
            f"expected {EXPECTED_CONSTRUCTION_ARMS} construction arms, found {len(candidates)}"
        )
    return candidates


def _weighting_candidates() -> list[dict[str, Any]]:
    report = json.loads(WEIGHTING_REPORT.read_text())
    construction = report["construction"]
    window = report["window"]
    candidates: list[dict[str, Any]] = []
    sections: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("grid", "primary", {}),
        ("nodrift_grid", "no_drift", {"drift_between_reforms": False}),
        (
            "hygiene_grid",
            "volatility_guard",
            {"vol_guard_ann": float(report["hygiene_grid"]["vol_guard_ann"])},
        ),
    )
    for section, mode, construction_delta in sections:
        cells = report[section] if section == "grid" else report[section]["cells"]
        for cell, metrics in sorted(cells.items()):
            scheme, raw_k = cell.rsplit("_K", 1)
            variant = cell if mode == "primary" else f"{mode}_{cell}"
            cell_construction = dict(construction)
            cell_construction.update(construction_delta)
            config = {
                "variant": variant,
                "scheme": metrics.get("scheme", scheme),
                "rank_top_k": int(metrics.get("K", raw_k)),
                "construction": cell_construction,
                "window": window,
                "source_artifact": str(WEIGHTING_REPORT.relative_to(REPO)),
                "source_artifact_sha256": _sha256(WEIGHTING_REPORT),
                "historical_accounting_correction": True,
            }
            if mode != "primary":
                config["robustness_mode"] = mode
            candidates.append(
                {
                    "kind": "summary_only_screen",
                    "probe": "forensic_alphamax_weighting",
                    "variant": variant,
                    "config": config,
                    "metrics": metrics,
                    "source": WEIGHTING_REPORT,
                    "periods_per_year": 365,
                }
            )
    if len(candidates) != EXPECTED_WEIGHTING_CELLS:
        raise RuntimeError(
            f"expected {EXPECTED_WEIGHTING_CELLS} weighting cells, found {len(candidates)}"
        )
    return candidates


def _summary_candidate(
    *,
    probe: str,
    variant: str,
    config: dict[str, Any],
    source: Path,
    sharpe_ann: float,
    n_obs: int,
    periods_per_year: int,
    skew: float = math.nan,
    kurtosis: float = math.nan,
) -> dict[str, Any]:
    return {
        "kind": "summary_only_screen",
        "probe": probe,
        "variant": variant,
        "config": config,
        "metrics": {
            "sharpe_ann": sharpe_ann,
            "n_obs": n_obs,
            "skew": skew,
            "kurtosis": kurtosis,
        },
        "source": source,
        "periods_per_year": periods_per_year,
    }


def _vrp_candidates() -> list[dict[str, Any]]:
    report = json.loads(VRP_REPORT.read_text())
    standalone = report["standalone"]
    window = report["window"]
    return [
        _summary_candidate(
            probe="crypto_vrp_proxy",
            variant="crypto_vrp_proxy",
            config={
                "currencies": sorted(report["currencies"]),
                "signal": "dvol_minus_yang_zhang_168",
                "k_cost": 0.02,
                "cost_bps": 10.0,
                "warmup_days": 365,
                "normalizer": "expanding_std_shift_1",
                "start": window["start"],
                "end": window["end"],
            },
            source=VRP_REPORT,
            sharpe_ann=float(standalone["net_sharpe_oos"]),
            n_obs=int(report["oos_days"]),
            periods_per_year=365,
            skew=float(standalone["skew"]),
            kurtosis=float(standalone["kurtosis_raw"]),
        )
    ]


def _hyst_candidates() -> list[dict[str, Any]]:
    report = json.loads(HYST_REPORT.read_text())
    construction, window = report["construction"], report["window"]
    candidates = []
    for arm, metrics in report["results"].items():
        candidates.append(
            _summary_candidate(
                probe="alphamax_hyst_live",
                variant=arm,
                config={
                    "profile": "sharadar",
                    "sleeve": "k30_dn_63",
                    "arm": arm,
                    "signal": "eq_mom_252_21",
                    "rank_top_k": int(construction["K_per_side"]),
                    "reform_bars": int(construction["reform_bars"]),
                    "exit_frac": metrics["exit_frac"],
                    "min_hold_bars": int(metrics["min_hold_bars"]),
                    "vol_window": int(construction["vol_window"]),
                    "gross_leg": float(construction["gross_leg"]),
                    "cost_oneway": float(construction["cost_oneway_bps"]) / 1e4,
                    "borrow_ann": float(construction["borrow_ann_bps"]) / 1e4,
                    "warmup": window["warmup"],
                    "start": window["book_start"],
                    "end": window["end"],
                },
                source=HYST_REPORT,
                sharpe_ann=float(metrics["net_sharpe_ann365"]),
                n_obs=int(metrics["n_days"]),
                periods_per_year=365,
            )
        )
    return candidates


def _turnover_candidates() -> list[dict[str, Any]]:
    report = json.loads(TURNOVER_REPORT.read_text())
    construction, window = report["construction"], report["window"]
    candidates = []
    for cadence, arms in report["results"].items():
        reform_bars = int(cadence.rsplit("_", 1)[1])
        for arm, metrics in arms.items():
            variant = f"{cadence}/{arm}"
            candidates.append(
                _summary_candidate(
                    probe="alphamax_turnover",
                    variant=variant,
                    config={
                        "profile": "sharadar",
                        "cadence": cadence,
                        "reform_bars": reform_bars,
                        "arm": arm,
                        "signal": "eq_mom_252_21",
                        "enter_frac": float(metrics["enter"]),
                        "exit_frac": float(metrics["exit"]),
                        "min_hold_bars": int(metrics["min_hold_bars"]),
                        "vol_window": int(construction["vol_window"]),
                        "gross_leg": float(construction["gross_leg"]),
                        "cost_oneway": float(construction["cost_oneway_bps"]) / 1e4,
                        "borrow_ann": float(construction["borrow_ann_bps"]) / 1e4,
                        "start": window["start"],
                        "end": window["end"],
                    },
                    source=TURNOVER_REPORT,
                    sharpe_ann=float(metrics["net_sharpe_ann365"]),
                    n_obs=int(metrics["n_days"]),
                    periods_per_year=365,
                )
            )
    return candidates


def _arp_candidates() -> list[dict[str, Any]]:
    report = json.loads(ARP_REPORT.read_text())
    variants = {
        "baseline": ("baseline", "blend_63_126_252"),
        "T1_corr_whiten": ("t1", "blend_63_126_252"),
        "T2_single_110": ("baseline", "single_110"),
    }
    rows = {row["variant"]: row for row in report["table"]}
    candidates = []
    for variant, (allocator, signal) in variants.items():
        row = rows[variant]
        candidates.append(
            _summary_candidate(
                probe="alphatrend_arp",
                variant=variant,
                config={
                    "variant": variant,
                    "allocator": allocator,
                    "signal": signal,
                    "universe": "managed_futures_17_etfs",
                    "vol_span": 33,
                    "rebalance_bars": 21,
                    "gross_max": 1.0,
                    "cost_per_side": 6e-4,
                    "borrow_ann": 50e-4,
                },
                source=ARP_REPORT,
                sharpe_ann=float(row["net_sharpe"]),
                n_obs=int(report["n_sessions"]),
                periods_per_year=252,
                skew=float(row["skew"]),
            )
        )
    return candidates


def _breadth_candidates() -> list[dict[str, Any]]:
    report = json.loads(BREADTH_REPORT.read_text())
    rows = {row["basket"]: row for row in report["table"]}
    base = [
        "SPY", "QQQ", "IWM", "EFA", "EEM", "IEF", "TLT", "SHY", "GLD",
        "SLV", "USO", "DBC", "DBA", "UNG", "UUP", "FXE", "FXY",
    ]
    expanded = [*base, *report["added"]]
    configs = {
        "BASE_17": {
            "basket": "BASE_17",
            "tickers": base,
        },
        "EXPANDED_33": {
            "basket": "EXPANDED_33",
            "tickers": expanded,
        },
        "EXP_minus_SHY": {
            "basket": "EXPANDED_MINUS_LARGEST_CONTRIBUTOR",
            "candidate_tickers": expanded,
            "selection_rule": "drop_largest_full_sample_pnl_contributor",
        },
        "PRUNED_22": {
            "basket": "GREEDY_NEFF_PRUNED",
            "base_tickers": base,
            "candidate_additions": list(report["added"]),
            "selection_rule": "greedy_add_only_if_neff_gain_gt_0",
        },
    }
    candidates = []
    for basket, row in rows.items():
        candidates.append(
            _summary_candidate(
                probe="alphatrend_breadth",
                variant=basket,
                config={
                    **configs[basket],
                    "signal": "blend_63_126_252",
                    "vol_span": 33,
                    "rebalance_bars": 21,
                    "gross_max": 1.0,
                    "cost_per_side": 6e-4,
                    "borrow_ann": 50e-4,
                },
                source=BREADTH_REPORT,
                sharpe_ann=float(row["net_sharpe"]),
                n_obs=int(report["n_sessions"]),
                periods_per_year=252,
                skew=float(row["skew"]),
            )
        )
    return candidates


def _all_candidates() -> list[dict[str, Any]]:
    summary = (
        _weighting_candidates()
        + _vrp_candidates()
        + _hyst_candidates()
        + _turnover_candidates()
        + _arp_candidates()
        + _breadth_candidates()
    )
    if len(summary) != EXPECTED_SUMMARY_IDENTITIES:
        raise RuntimeError(
            f"expected {EXPECTED_SUMMARY_IDENTITIES} summary identities, found {len(summary)}"
        )
    candidates = _construction_candidates() + summary
    if len(candidates) != EXPECTED_TOTAL_IDENTITIES:
        raise RuntimeError(
            f"expected {EXPECTED_TOTAL_IDENTITIES} total identities, found {len(candidates)}"
        )
    hashes = [config_hash(_full_config(candidate)) for candidate in candidates]
    if len(set(hashes)) != len(hashes):
        raise RuntimeError("forensic candidate configs are not identity-unique")
    return candidates


def _full_config(candidate: dict[str, Any]) -> dict[str, Any]:
    return {"probe": candidate["probe"], **candidate["config"]}


def _record(candidate: dict[str, Any], ordinal: int) -> None:
    now_ms = AUDIT_NOW_MS + ordinal
    if candidate["kind"] == "complete_walkforward":
        record_probe_trial(
            candidate["probe"],
            candidate["config"],
            candidate["returns"],
            now_ms=now_ms,
            periods_per_year=252,
            ledger_path=ACTIVE_LEDGER,
        )
        return

    metrics = candidate["metrics"]
    periods_per_year = int(candidate.get("periods_per_year", 365))
    sharpe_ann = float(metrics.get("sharpe_ann", metrics.get("net_sharpe_ann365")))
    ExperimentLog(ACTIVE_LEDGER).record(
        _full_config(candidate),
        sharpe_ann=sharpe_ann,
        sharpe_per_period=sharpe_ann / math.sqrt(float(periods_per_year)),
        n_obs=int(metrics.get("n_obs", metrics.get("n_days"))),
        skew=float(metrics.get("skew", math.nan)),
        kurtosis=float(metrics.get("kurtosis", math.nan)),
        now_ms=now_ms,
    )


def reconcile(*, apply: bool) -> dict[str, Any]:
    candidates = _all_candidates()
    union_before = ExperimentUnion.discover(ACTIVE_LEDGER, REPO)
    existing_hashes = {record.config_hash for record in union_before.all()}
    pending = [
        candidate
        for candidate in candidates
        if config_hash(_full_config(candidate)) not in existing_hashes
    ]
    n_before = union_before.n_hypotheses()

    if apply:
        for ordinal, candidate in enumerate(candidates):
            _record(candidate, ordinal)

    union_after = ExperimentUnion.discover(ACTIVE_LEDGER, REPO)
    n_after = union_after.n_hypotheses()
    if apply and n_after - n_before != len(pending):
        raise RuntimeError(
            f"identity delta {n_after - n_before} did not match pending forensic records "
            f"{len(pending)}"
        )

    payload = {
        "schema": "alphac.trial-debt-reconciliation.v2",
        "applied": apply,
        "claim_boundary": (
            "Every persisted named parameter configuration is charged, including configurations "
            "with identical reported returns. Rounded summaries and copied harnesses are not used "
            "to assert duplicate economic identity. No unpersisted exploratory work is claimed."
        ),
        "selection_identities_before": n_before,
        "selection_identities_after": n_after,
        "candidate_records": len(candidates),
        "new_records_pending_before_run": len(pending),
        "sources": [
            {
                "path": str(path.relative_to(REPO)),
                "sha256": _sha256(path),
                "charged_identities": count,
                "evidence_grade": grade,
            }
            for path, count, grade in (
                (CONSTRUCTION_MANIFEST, 8, "complete_walkforward_curve_and_config"),
                (WEIGHTING_REPORT, 48, "persisted_summary_only_missing_higher_moments"),
                (VRP_REPORT, 1, "persisted_summary_with_higher_moments"),
                (HYST_REPORT, 6, "persisted_summary_only_missing_higher_moments"),
                (TURNOVER_REPORT, 8, "persisted_summary_only_missing_higher_moments"),
                (ARP_REPORT, 3, "persisted_summary_with_skew"),
                (BREADTH_REPORT, 4, "persisted_summary_with_skew"),
            )
        ],
        "records": [
            {
                "probe": candidate["probe"],
                "variant": candidate["variant"],
                "kind": candidate["kind"],
                "config_hash": config_hash(_full_config(candidate)),
                "source": str(candidate["source"].relative_to(REPO)),
            }
            for candidate in candidates
        ],
    }
    if apply:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="append idempotent forensic records")
    args = parser.parse_args()
    payload = reconcile(apply=args.apply)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
