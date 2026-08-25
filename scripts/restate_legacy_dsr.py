#!/usr/bin/env python3
"""Restate reproducible legacy DSR outputs against the current selection union.

Original artifacts are never edited. Return-complete families are recalculated from their
persisted series; summary-only families are retired because DSR cannot be reconstructed honestly
from annualized Sharpe alone. This script records no experiment and opens no holdout.
"""

from __future__ import annotations

import datetime as dt
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
from alphaforge.validation.dsr import dsr_from_returns  # noqa: E402
from alphaforge.validation.legacy_epoch import legacy_selection_context  # noqa: E402

OUT_JSON: Final[Path] = REPO / "artifacts" / "audit" / "legacy_dsr_restatement.json"
OUT_MD: Final[Path] = REPO / "docs" / "research" / "LEGACY_DSR_RESTATEMENT.md"
EXCEPTIONS: Final[Path] = REPO / "config" / "legacy_dsr_exceptions.json"
PERIODS_PER_YEAR: Final[float] = 252.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_float(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value)


def _equity_returns(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    equity = pd.Series(
        frame["equity"].to_numpy(dtype="float64"),
        index=pd.Index(frame["ts"].to_numpy(dtype="int64"), name="ts"),
    )
    return daily_returns(equity)


def _restated_row(
    *,
    family: str,
    variant: str,
    returns: pd.Series,
    returns_path: Path,
    historical_artifact: Path,
    historical_dsr: Any,
    n_trials: int,
    variance: float,
) -> dict[str, Any]:
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if len(values) < 2:
        raise ValueError(f"{family}/{variant}: fewer than two finite return observations")
    report = dsr_from_returns(
        values,
        n_trials=max(2, n_trials),
        sr_trials_variance=variance,
        periods_per_year=PERIODS_PER_YEAR,
    )
    historical_contexts = historical_dsr if isinstance(historical_dsr, dict) else None
    if historical_contexts is not None:
        preferred = historical_contexts.get("var") or next(iter(historical_contexts.values()))
        historical_scalar = preferred.get("dsr") if isinstance(preferred, dict) else None
    else:
        historical_scalar = historical_dsr
    return {
        "family": family,
        "variant": variant,
        "status": "RESTATED_CURRENT_UNION",
        "return_contract": "persisted_simple_daily_returns",
        "n_obs": report.n_obs,
        "historical_dsr": _json_float(historical_scalar),
        "historical_dsr_contexts": historical_contexts,
        "restated_dsr": _json_float(report.dsr),
        "restated_psr": _json_float(report.psr),
        "restated_sharpe_ann_252": _json_float(report.sr_ann),
        "restated_expected_max_sr_per_period": _json_float(report.expected_max_sr),
        "clears_dsr_0_95": bool(math.isfinite(report.dsr) and report.dsr >= 0.95),
        "returns_path": str(returns_path.relative_to(REPO)),
        "returns_sha256": _sha256(returns_path),
        "historical_artifact_path": str(historical_artifact.relative_to(REPO)),
        "historical_artifact_sha256": _sha256(historical_artifact),
    }


def _construction_rows(n_trials: int, variance: float) -> list[dict[str, Any]]:
    root = REPO / "artifacts" / "sweep" / "alphamax_construction"
    artifact = root / "arms.json"
    arms = json.loads(artifact.read_text())
    return [
        _restated_row(
            family="alphamax_construction",
            variant=arm,
            returns=_equity_returns(root / f"wf_{arm}" / "equity.parquet"),
            returns_path=root / f"wf_{arm}" / "equity.parquet",
            historical_artifact=artifact,
            historical_dsr=entry["metrics"].get("dsr"),
            n_trials=n_trials,
            variance=variance,
        )
        for arm, entry in sorted(arms.items())
    ]


def _gauntlet_rows(n_trials: int, variance: float) -> list[dict[str, Any]]:
    root = REPO / "artifacts" / "probe" / "alphamax_constructions"
    run = root / "gauntlet_eq_52whigh_252"
    artifact = run / "walkforward.json"
    metadata = json.loads(artifact.read_text())
    return [
        _restated_row(
            family="alphamax_constructions",
            variant="gauntlet_eq_52whigh_252",
            returns=_equity_returns(run / "equity.parquet"),
            returns_path=run / "equity.parquet",
            historical_artifact=artifact,
            historical_dsr=(metadata.get("validation") or {}).get("dsr"),
            n_trials=n_trials,
            variance=variance,
        )
    ]


def _csv_family_rows(
    *,
    family: str,
    csv_paths: list[Path],
    report_path: Path,
    metric_lookup: Any,
    n_trials: int,
    variance: float,
) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text())
    rows: list[dict[str, Any]] = []
    for csv_path in csv_paths:
        frame = pd.read_csv(csv_path, index_col=0)
        for column in frame.columns:
            rows.append(
                _restated_row(
                    family=family,
                    variant=metric_lookup(report, csv_path, str(column), "variant"),
                    returns=frame[column],
                    returns_path=csv_path,
                    historical_artifact=report_path,
                    historical_dsr=metric_lookup(report, csv_path, str(column), "dsr"),
                    n_trials=n_trials,
                    variance=variance,
                )
            )
    return rows


def _betaneutral_rows(n_trials: int, variance: float) -> list[dict[str, Any]]:
    root = REPO / "artifacts" / "probe" / "alphamax_betaneutral"
    paths = sorted(root.glob("net_returns_*.csv"))

    def lookup(report: dict[str, Any], path: Path, column: str, field: str) -> Any:
        panel = next(
            key
            for key in report["panels"]
            if path.stem.removeprefix("net_returns_").replace("_", " ").lower()
            == key.replace("-", " ").replace("=", " ").replace("_", " ").lower()
        )
        if field == "variant":
            return f"{panel}/{column}"
        return report["panels"][panel]["results"][column]["dsr"]

    return _csv_family_rows(
        family="alphamax_betaneutral",
        csv_paths=paths,
        report_path=root / "report.json",
        metric_lookup=lookup,
        n_trials=n_trials,
        variance=variance,
    )


def _shorttail_rows(n_trials: int, variance: float) -> list[dict[str, Any]]:
    root = REPO / "artifacts" / "probe" / "alphamax_shorttail"

    def lookup(report: dict[str, Any], path: Path, column: str, field: str) -> Any:
        del path
        return column if field == "variant" else report["results"][column]["dsr"]

    return _csv_family_rows(
        family="alphamax_shorttail",
        csv_paths=[root / "net_returns.csv"],
        report_path=root / "report.json",
        metric_lookup=lookup,
        n_trials=n_trials,
        variance=variance,
    )


def _econtrend_rows(n_trials: int, variance: float) -> list[dict[str, Any]]:
    root = REPO / "artifacts" / "sweep" / "econtrend_probe"
    returns_path = root / "oos_daily_returns.parquet"
    artifact = root / "econtrend_result.json"
    result = json.loads(artifact.read_text())
    frame = pd.read_parquet(returns_path)
    return [
        _restated_row(
            family="econtrend",
            variant="locked_primary_oos",
            returns=frame["ret"],
            returns_path=returns_path,
            historical_artifact=artifact,
            historical_dsr=result.get("dsr_ledger"),
            n_trials=n_trials,
            variance=variance,
        )
    ]


def _retired_families() -> list[dict[str, Any]]:
    specifications = [
        ("exp2_crypto_vrp", "artifacts/exp2/20260625T094710Z/exp2_metrics.json"),
        ("alphamax_hyst_live", "artifacts/probe/alphamax_hyst_live/report.json"),
        ("alphamax_turnover", "artifacts/probe/alphamax_turnover/report.json"),
        ("alphamax_volscale", "artifacts/probe_volscale/report.json"),
        ("alphamax_weighting", "artifacts/probe/alphamax_weighting/report.json"),
        ("alphatrend_arp", "artifacts/sweep/alphatrend_arp/report.json"),
        ("alphatrend_breadth", "artifacts/sweep/alphatrend_breadth/report.json"),
    ]
    return [
        {
            "family": family,
            "status": "RETIRED_MISSING_RETURN_SERIES",
            "reason": (
                "The persisted artifact contains summary statistics but no variant-level return "
                "series. DSR depends on observations, skew and kurtosis; it cannot be honestly "
                "reconstructed from annualized Sharpe."
            ),
            "required_to_restate": (
                "Reproduce the already-tested locked configuration and persist its exact net "
                "simple-return series; this does not authorize parameter changes or a new holdout."
            ),
            "historical_artifact_path": path,
            "historical_artifact_sha256": _sha256(REPO / path),
        }
        for family, path in specifications
    ]


def build() -> dict[str, Any]:
    n_trials, variance, ledger_paths = legacy_selection_context(REPO)
    rows = (
        _construction_rows(n_trials, variance)
        + _gauntlet_rows(n_trials, variance)
        + _betaneutral_rows(n_trials, variance)
        + _shorttail_rows(n_trials, variance)
        + _econtrend_rows(n_trials, variance)
    )
    rows.sort(key=lambda row: (row["family"], row["variant"]))
    retired = _retired_families()
    exception_policy = json.loads(EXCEPTIONS.read_text())
    historical_families = len(exception_policy["exceptions"]) + len(
        exception_policy.get("resolved_paths", {})
    )
    return {
        "schema": "alphac.legacy-dsr-restatement.v1",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "claim_boundary": (
            "This restates DSR only. It does not upgrade data quality, validation grade, sleeve "
            "admissibility or investment performance, and it does not alter original artifacts."
        ),
        "selection_context": {
            "n_hypotheses": n_trials,
            "sharpe_variance": variance,
            "unit": "first_immutable_record_per_hypothesis",
            "ledger_paths": ledger_paths,
        },
        "summary": {
            "historical_exception_families": historical_families,
            "restated_families": len({row["family"] for row in rows}),
            "restated_variants": len(rows),
            "retired_families": len(retired),
            "restated_variants_clearing_dsr_0_95": sum(row["clears_dsr_0_95"] for row in rows),
        },
        "code_status": {
            "resolved_paths": sorted(exception_policy.get("resolved_paths", {})),
            "executable_debt_paths": sorted(exception_policy["exceptions"]),
            "union_registration_paths": sorted(
                exception_policy.get("union_registration_paths", [])
            ),
            "enforcement": exception_policy["enforcement"],
        },
        "restated_variants": rows,
        "retired_families": retired,
    }


def _markdown(payload: dict[str, Any]) -> str:
    context = payload["selection_context"]
    summary = payload["summary"]
    lines = [
        "# Legacy DSR restatement",
        "",
        "This is a correction ledger, not a performance upgrade. Original artifacts remain intact.",
        "",
        f"Current selection context: **N={context['n_hypotheses']}**, "
        f"identity-aligned **V[SR]={context['sharpe_variance']:.10f}**.",
        "",
        f"- Restated: {summary['restated_variants']} variants across "
        f"{summary['restated_families']} families.",
        f"- Retired for missing return series: {summary['retired_families']} families.",
        f"- Current DSR ≥ 0.95: {summary['restated_variants_clearing_dsr_0_95']} variants.",
        "",
        "## Recomputed variants",
        "",
        "| Family | Variant | Historical DSR | Current DSR | Status |",
        "|---|---|---:|---:|---|",
    ]
    for row in payload["restated_variants"]:
        historical = "n/a" if row["historical_dsr"] is None else f"{row['historical_dsr']:.6f}"
        current = "n/a" if row["restated_dsr"] is None else f"{row['restated_dsr']:.6f}"
        lines.append(
            f"| {row['family']} | `{row['variant']}` | {historical} | {current} | "
            f"{'CLEAR' if row['clears_dsr_0_95'] else 'FAIL'} |"
        )
    lines.extend(["", "## Retired historical DSR claims", ""])
    for row in payload["retired_families"]:
        lines.append(f"- **{row['family']}** — {row['reason']}")
    lines.extend(
        [
            "",
            "## Executable-code status",
            "",
            f"All {len(payload['code_status']['resolved_paths'])} historical probe paths now use "
            "identity-aligned union accounting or fail closed at preflight. There are "
            f"{len(payload['code_status']['executable_debt_paths'])} executable raw-row DSR paths. "
            f"Separately, {summary['retired_families']} summary-only artifact families remain "
            "retired and cannot be treated as approved evidence.",
            "",
            "Resolved paths:",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in payload["code_status"]["resolved_paths"])
    if payload["code_status"]["executable_debt_paths"]:
        lines.extend(["", "Executable debt paths:", ""])
        lines.extend(f"- `{path}`" for path in payload["code_status"]["executable_debt_paths"])
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            payload["claim_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    payload = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    OUT_MD.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
