#!/usr/bin/env python3
"""Build the deterministic evidence packet for every crypto-momentum hypothesis.

The script opens no holdout and records no experiment. It joins the first immutable union
measurement for each known momentum identity to its persisted walk-forward artifact, fails on any
missing or inconsistent row, and publishes only artifact-derived measurements and provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
OUT: Final[Path] = REPO / "artifacts" / "research" / "crypto_momentum_family.json"
EXP1_METRICS: Final[Path] = REPO / "artifacts" / "exp1" / "20260625T075446Z" / "exp1_metrics.json"

ARTIFACT_BY_HYPOTHESIS: Final[dict[str, str]] = {
    "fb1358c08d36d128": "artifacts/walkforward/crypto_mom_base/walkforward.json",
    "bee03ca77096bf76": "artifacts/cpanel/L4_xs168_d/walkforward.json",
    "f781fc9dac3d783d": "artifacts/cpanel/L4_xs504_d/walkforward.json",
    "757781cf1d69e68f": "artifacts/cpanel/L4_ts504_d/walkforward.json",
    "54b0a73551057e63": "artifacts/cpanel/L4_ts168_d/walkforward.json",
    "b08b7841ef8beb6e": "artifacts/cpanel/L9_tsmom/walkforward.json",
    "73aa637baa2b554d": "artifacts/cpanel/ts504_long_d/walkforward.json",
    "94a8bafd2d6af076": "artifacts/cpanel/ts504_long_w/walkforward.json",
    "5b5a71b086289f8d": "artifacts/cpanel/ts2160_long_d/walkforward.json",
    "abc2f98882a8cb5d": "artifacts/cpanel/L4_xs504_w/walkforward.json",
    "131745bc21f41d5f": "artifacts/cpanel/L4_ts2160_w/walkforward.json",
    "63812ba59fb509bd": "artifacts/cpanel/L4_ts504_w/walkforward.json",
    "3854903ae853daf8": "artifacts/cpanel/L4_ts504_3d/walkforward.json",
    "581babb3419fc331": "artifacts/cpanel/L4_ts504_2w/walkforward.json",
    "29233f5e0132b584": "artifacts/cpanel/L4_blend21_w/walkforward.json",
    "949d33468f11327a": "artifacts/cpanel/L4_ts504_h1/walkforward.json",
    "5d3e879373e9a0b8": "artifacts/cpanel/L4_ts504_h2/walkforward.json",
    "827861e57050f162": "artifacts/exp1/20260625T075446Z/momentum/walkforward.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_momentum(config: dict[str, Any]) -> bool:
    raw = config.get("alpha_names")
    alphas = [str(value) for value in raw] if isinstance(raw, list) else []
    return any(alpha.startswith(("mom_ts_", "mom_xs_")) for alpha in alphas) and not any(
        alpha.startswith("carry_") for alpha in alphas
    )


def _first_momentum_records() -> dict[str, tuple[Any, Path]]:
    union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            if not _is_momentum(record.config):
                continue
            key = ledger._hypothesis_key(record.config)
            current = first.get(key)
            if current is None or (record.now_ms, record.config_hash) < (
                current[0].now_ms,
                current[0].config_hash,
            ):
                first[key] = (record, path)
    return first


def build() -> dict[str, Any]:
    records = _first_momentum_records()
    expected = set(ARTIFACT_BY_HYPOTHESIS)
    if set(records) != expected:
        missing = sorted(set(records) - expected)
        stale = sorted(expected - set(records))
        raise ValueError(f"momentum artifact map mismatch: missing={missing}, stale={stale}")

    identities: list[dict[str, Any]] = []
    for key, relative in sorted(ARTIFACT_BY_HYPOTHESIS.items()):
        record, ledger_path = records[key]
        artifact_path = REPO / relative
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        summary = artifact["summary"]
        config = artifact["config"]
        validation = artifact["validation"]
        observed_sharpe = float(summary["sharpe"])
        if not math.isclose(observed_sharpe, record.sharpe_ann, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"{key}: artifact Sharpe {observed_sharpe} != ledger {record.sharpe_ann}"
            )
        if validation.get("clears_dsr_gate") is not False:
            raise ValueError(f"{key}: expected persisted DSR failure")
        ledger_alphas = record.config.get("alpha_names")
        if config.get("alpha_names") != ledger_alphas:
            raise ValueError(f"{key}: artifact alpha names do not match immutable ledger")
        instrument_ids = [str(value) for value in config.get("instrument_ids", [])]
        identities.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "alpha_names": ledger_alphas,
                "ledger_source_path": str(ledger_path.relative_to(REPO)),
                "artifact_path": relative,
                "artifact_sha256": _sha256(artifact_path),
                "configuration": {
                    "allocator": config.get("allocator"),
                    "rebalance_bars": config.get("rebalance_bars"),
                    "train_bars": config.get("train_bars"),
                    "test_bars": config.get("test_bars"),
                    "purge_bars": config.get("purge_bars"),
                    "embargo_bars": config.get("embargo_bars"),
                    "n_legs": config.get("n_legs"),
                    "instrument_count": len(instrument_ids),
                    "instrument_namespaces": sorted(
                        {value.split(":", 1)[0] for value in instrument_ids}
                    ),
                },
                "result": {
                    "start_ts": summary.get("start_ts"),
                    "end_ts": summary.get("end_ts"),
                    "n_days": summary.get("n_days"),
                    "initial_equity": summary.get("initial_equity"),
                    "final_equity": summary.get("final_equity"),
                    "total_return": summary.get("total_return"),
                    "cagr": summary.get("cagr"),
                    "annualized_sharpe": observed_sharpe,
                    "annualized_volatility": summary.get("vol_ann"),
                    "maximum_drawdown": summary.get("max_dd"),
                    "annual_turnover": summary.get("turnover_ann"),
                    "fees_paid": summary.get("fees_paid"),
                    "funding_net": summary.get("funding_net"),
                    "artifact_era_dsr": validation.get("dsr"),
                    "artifact_era_n_trials": validation.get("n_trials_used"),
                    "clears_artifact_era_dsr_gate": False,
                },
            }
        )

    exp1 = json.loads(EXP1_METRICS.read_text(encoding="utf-8"))
    sharpes = [float(row["result"]["annualized_sharpe"]) for row in identities]
    drawdowns = [float(row["result"]["maximum_drawdown"]) for row in identities]
    return {
        "schema": "canli.alphac-crypto-momentum-family.v1",
        "evidence_date": "2026-08-22",
        "author": "Arhan Canli",
        "family_key": "crypto_momentum",
        "claim_boundary": (
            "This packet reconciles persisted historical simulations and their original DSR "
            "verdicts. It is not a forward return, capacity study, sleeve admission, or promise."
        ),
        "implementation": {
            "cross_sectional_long_horizon_bars": [168, 504, 2160],
            "cross_sectional_skip_bars": [24, 48, 168],
            "time_series_horizon_bars": [168, 504, 2160],
            "volatility_normalization_bars": 168,
        },
        "summary": {
            "distinct_hypothesis_identities": len(identities),
            "minimum_annualized_sharpe": min(sharpes),
            "maximum_annualized_sharpe": max(sharpes),
            "minimum_maximum_drawdown": min(drawdowns),
            "maximum_maximum_drawdown": max(drawdowns),
            "artifact_era_dsr_gate_passes": sum(
                bool(row["result"]["clears_artifact_era_dsr_gate"]) for row in identities
            ),
            "capacity_status": "UNMEASURED_NO_PERSISTED_MOMENTUM_CAPACITY_SWEEP",
            "admission_status": "FAIL_RESEARCH_ONLY",
        },
        "related_diversification_diagnostic": {
            "source_path": str(EXP1_METRICS.relative_to(REPO)),
            "source_sha256": _sha256(EXP1_METRICS),
            "momentum_sharpe": exp1["momentum"]["sharpe"],
            "momentum_artifact_era_dsr": exp1["momentum"]["dsr"],
            "combined_sharpe": exp1["combined"]["sharpe"],
            "combined_maximum_drawdown": abs(float(exp1["combined"]["maxdd"])),
            "full_sample_correlation": exp1["combined"]["corr_full_sample"],
            "stress_correlation_book_worst_2_5pct": exp1["combined"][
                "corr_stress_book_worst2.5pct"
            ],
            "stress_correlation_either_sleeve_worst_2_5pct": exp1["combined"][
                "corr_stress_either_sleeve_worst2.5pct"
            ],
            "decorrelated_sharpe_ceiling": exp1["combined"]["sharpe_decorrelated_ceiling"],
            "interpretation": (
                "Low or negative correlation did not compensate for weak standalone edge; this "
                "diagnostic does not earn an independent sleeve slot."
            ),
        },
        "identities": identities,
    }


def main() -> int:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
