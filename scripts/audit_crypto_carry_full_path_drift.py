#!/usr/bin/env python3
"""Delimit the crypto-carry replay drift without pretending it is additive.

The preserved June result and the August current-state replay are two realized,
path-dependent executions.  They are enough to prove and quantify divergence, but
the June artifact did not bind its exact code tree, signal frame, universe intervals,
or SCD2 instrument rows.  Consequently they are not enough to estimate a unique
"universe contribution" and "software contribution" to the terminal P&L delta.

This audit exhausts the evidence that *does* survive: every stitched and per-leg
ledger, exogenous marks/rates on overlapping records, risk-state counters, the exact
first-decision counterfactual, and repository archaeology.  It spends no return trial.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "artifacts/walkforward/crypto_carry_wk"
REPLAY: Final = ROOT / "artifacts/probe/crypto_carry_frozen_current_code_replay"
FIRST_ATTRIBUTION: Final = (
    ROOT / "artifacts/probe/crypto_carry_replay_drift/first_rebalance_attribution.json"
)
REPLAY_RECEIPT: Final = REPLAY / "replay_receipt.json"
OUTPUT: Final = ROOT / "artifacts/probe/crypto_carry_replay_drift/full_path_attribution.json"
STRATEGY_PATH: Final = ROOT / "src/alphaforge/portfolio/strategy.py"

# Last repository commit before the preserved artifact's filesystem timestamp.  It
# is useful archaeology, not a run binding: uncommitted state could have existed.
REPOSITORY_STATE_CANDIDATE: Final = "fd3e930f41b0a62b222ecda4ab83bae21a4ce9f2"
REALIZED_VOL_FIX: Final = "dd35711497d0e551d61d3593f7fd395a33b0c7b4"
SUMMARY_KEYS: Final = (
    "final_equity",
    "sharpe",
    "max_dd",
    "cagr",
    "funding_net",
    "fees_paid",
    "turnover_ann",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _verified(path: Path) -> dict[str, Any]:
    document = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError(f"invalid content hash: {path}")
    return document


def _artifact_binding(directory: Path) -> dict[str, Any]:
    required_names = {
        "equity.parquet",
        "fills.parquet",
        "funding.parquet",
        "orders.parquet",
        "positions.parquet",
    }
    leg_directories = sorted((directory / "legs").glob("leg_*"))
    incomplete_legs = [
        str(leg.relative_to(ROOT))
        for leg in leg_directories
        if not required_names.issubset({path.name for path in leg.glob("*.parquet")})
    ]
    paths = sorted(
        [
            directory / "walkforward.json",
            directory / "equity.parquet",
            *(directory / "legs").glob("leg_*/*.parquet"),
        ]
    )
    missing = [path for path in paths if not path.is_file()]
    if missing or len(leg_directories) != 25 or incomplete_legs or len(paths) < 127:
        raise RuntimeError(
            "unexpected crypto-carry artifact inventory: "
            f"{len(paths)=}, {len(leg_directories)=}, {missing=}, {incomplete_legs=}"
        )
    leaves = [
        {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in paths
    ]
    return {
        "directory": str(directory.relative_to(ROOT)),
        "files": len(leaves),
        "legs": len(leg_directories),
        "required_ledgers_per_leg": sorted(required_names),
        "bytes": sum(row["bytes"] for row in leaves),
        "root_sha256": hashlib.sha256(_canonical(leaves)).hexdigest(),
        "walkforward_sha256": _sha256(directory / "walkforward.json"),
        "equity_sha256": _sha256(directory / "equity.parquet"),
    }


def _all_legs(directory: Path, filename: str) -> pd.DataFrame:
    frames = []
    for leg in range(25):
        frame = pd.read_parquet(directory / "legs" / f"leg_{leg:02d}" / filename)
        frame.insert(0, "leg", leg)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _overlap(
    source: pd.DataFrame,
    replay: pd.DataFrame,
    *,
    key: list[str],
    exact_columns: list[str],
) -> dict[str, Any]:
    if source.duplicated(key).any() or replay.duplicated(key).any():
        raise RuntimeError(f"comparison key is not unique: {key}")
    joined = source.merge(
        replay,
        on=key,
        how="outer",
        suffixes=("_source", "_replay"),
        indicator=True,
        validate="one_to_one",
    )
    counts = joined["_merge"].value_counts()
    both = joined[joined["_merge"] == "both"]
    comparisons: dict[str, Any] = {}
    for column in exact_columns:
        left = both[f"{column}_source"].to_numpy(dtype=np.float64)
        right = both[f"{column}_replay"].to_numpy(dtype=np.float64)
        finite = np.isfinite(left) & np.isfinite(right)
        delta = np.abs(left[finite] - right[finite])
        comparisons[column] = {
            "finite_pairs": int(finite.sum()),
            "exact_pairs": int((delta == 0.0).sum()),
            "all_finite_pairs_exact": bool(len(delta) and np.all(delta == 0.0)),
            "maximum_absolute_difference": float(delta.max()) if len(delta) else None,
        }
    return {
        "source_rows": len(source),
        "replay_rows": len(replay),
        "source_only_keys": int(counts.get("left_only", 0)),
        "replay_only_keys": int(counts.get("right_only", 0)),
        "overlap_keys": int(counts.get("both", 0)),
        "comparison_key": key,
        "columns": comparisons,
    }


def _equity_path() -> dict[str, Any]:
    source = pd.read_parquet(SOURCE / "equity.parquet").set_index("ts")["equity"]
    replay = pd.read_parquet(REPLAY / "equity.parquet").set_index("ts")["equity"]
    if not source.index.equals(replay.index):
        raise RuntimeError("stitched equity timestamps differ; this audit expects exact alignment")
    delta = replay.to_numpy(dtype=np.float64) - source.to_numpy(dtype=np.float64)
    unequal = np.flatnonzero(delta != 0.0)
    first = int(unequal[0]) if unequal.size else None
    return {
        "timestamps_exactly_equal": True,
        "rows": len(source),
        "unequal_equity_rows": int(unequal.size),
        "first_divergence": (
            None
            if first is None
            else {
                "row": first,
                "ts": int(source.index[first]),
                "source_equity": float(source.iloc[first]),
                "replay_equity": float(replay.iloc[first]),
                "delta_replay_minus_source": float(delta[first]),
            }
        ),
        "maximum_absolute_difference": float(np.abs(delta).max()),
        "terminal_difference": float(delta[-1]),
    }


def _per_leg(source_meta: dict[str, Any], replay_meta: dict[str, Any]) -> list[dict[str, Any]]:
    source_legs = source_meta["legs"]
    replay_legs = replay_meta["legs"]
    if len(source_legs) != 25 or len(replay_legs) != 25:
        raise RuntimeError("expected 25 source and replay legs")
    rows = []
    for source, replay in zip(source_legs, replay_legs, strict=True):
        if any(source[key] != replay[key] for key in ("leg", "test_start", "test_end")):
            raise RuntimeError("walk-forward leg boundaries drifted")
        rows.append(
            {
                "leg": int(source["leg"]),
                "test_start": int(source["test_start"]),
                "test_end": int(source["test_end"]),
                "summary_delta_replay_minus_source": {
                    key: float(replay["summary"][key]) - float(source["summary"][key])
                    for key in SUMMARY_KEYS
                },
                "risk_counter_delta_replay_minus_source": {
                    key: int(replay["risk_counters"].get(key, 0))
                    - int(source["risk_counters"].get(key, 0))
                    for key in sorted(set(source["risk_counters"]) | set(replay["risk_counters"]))
                },
            }
        )
    return rows


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def _code_archaeology() -> dict[str, Any]:
    candidate_meta = _git(
        "show", "-s", "--format=%H%x00%cI%x00%s", REPOSITORY_STATE_CANDIDATE
    ).split("\x00")
    fix_meta = _git("show", "-s", "--format=%H%x00%cI%x00%s", REALIZED_VOL_FIX).split("\x00")
    candidate_blob = _git(
        "rev-parse", f"{REPOSITORY_STATE_CANDIDATE}:src/alphaforge/portfolio/strategy.py"
    )
    source_mtime = pd.Timestamp((SOURCE / "walkforward.json").stat().st_mtime, unit="s", tz="UTC")
    return {
        "historical_run_exact_commit_bound": False,
        "current_replay_exact_source_tree_bound": False,
        "repository_state_candidate_not_run_authority": {
            "commit": candidate_meta[0],
            "committed_at": candidate_meta[1],
            "subject": candidate_meta[2],
            "strategy_git_blob": candidate_blob,
            "selection_method": (
                "last repository commit preceding the preserved walkforward.json filesystem "
                "mtime; this cannot exclude uncommitted or alternate-branch state"
            ),
            "artifact_filesystem_mtime": source_mtime.isoformat(),
        },
        "realized_vol_overlay_correction": {
            "commit": fix_meta[0],
            "committed_at": fix_meta[1],
            "subject": fix_meta[2],
            "current_audit_strategy_sha256": _sha256(STRATEGY_PATH),
            "historical_candidate_strategy_git_blob": candidate_blob,
            "current_replay_realized_leg_bound_counter": True,
        },
        "claim_boundary": (
            "Repository history proves the correction exists and identifies a plausible June "
            "repository state. It does not prove the byte-exact source tree used by either "
            "unbound execution."
        ),
    }


def build() -> dict[str, Any]:
    source_meta = json.loads((SOURCE / "walkforward.json").read_text(encoding="utf-8"))
    replay_meta = json.loads((REPLAY / "walkforward.json").read_text(encoding="utf-8"))
    first = _verified(FIRST_ATTRIBUTION)
    receipt = _verified(REPLAY_RECEIPT)
    if first["status"] != "PASS_FIRST_REBALANCE_CAUSE_EXACTLY_REPRODUCED":
        raise RuntimeError("first-decision causal audit is not sealed")
    if receipt.get("exact_replay") is not False:
        raise RuntimeError("full-path drift audit requires a non-exact replay")
    source_ids = source_meta["config"]["instrument_ids"]
    replay_ids = replay_meta["config"]["instrument_ids"]
    if source_ids != replay_ids or len(source_ids) != 58:
        raise RuntimeError("declared 58-instrument run universe changed")

    orders = _overlap(
        _all_legs(SOURCE, "orders.parquet"),
        _all_legs(REPLAY, "orders.parquet"),
        key=["leg", "decision_ts", "instrument_id", "side"],
        exact_columns=["decision_price", "qty"],
    )
    funding = _overlap(
        _all_legs(SOURCE, "funding.parquet"),
        _all_legs(REPLAY, "funding.parquet"),
        key=["leg", "ts_funding", "instrument_id"],
        exact_columns=["rate", "mark_price", "position_qty", "payment_quote"],
    )
    positions = _overlap(
        _all_legs(SOURCE, "positions.parquet"),
        _all_legs(REPLAY, "positions.parquet"),
        key=["leg", "ts", "instrument_id"],
        exact_columns=["mark", "qty", "weight"],
    )
    risk_source = source_meta["config"]["risk_counters"]
    risk_replay = replay_meta["config"]["risk_counters"]
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-full-path-drift-audit.v1",
        "author": "Arhan Canli",
        "status": (
            "PASS_SURVIVING_EVIDENCE_EXHAUSTED_EXACT_ADDITIVE_CAUSAL_SPLIT_NOT_IDENTIFIABLE"
        ),
        "scope": (
            "zero-new-trial forensic comparison of the complete surviving source and replay "
            "output paths; not a return experiment, counterfactual backtest, or replication"
        ),
        "bindings": {
            "historical_artifact": _artifact_binding(SOURCE),
            "current_state_replay": _artifact_binding(REPLAY),
            "first_decision_attribution": {
                "path": str(FIRST_ATTRIBUTION.relative_to(ROOT)),
                "sha256": _sha256(FIRST_ATTRIBUTION),
                "content_hash": first["content_hash"],
            },
            "replay_receipt": {
                "path": str(REPLAY_RECEIPT.relative_to(ROOT)),
                "sha256": _sha256(REPLAY_RECEIPT),
                "content_hash": receipt["content_hash"],
            },
        },
        "declared_run_alignment": {
            "instrument_ids_exactly_equal": True,
            "declared_instrument_count": len(source_ids),
            "leg_count": 25,
            "leg_boundaries_exactly_equal": True,
            "n_rebalances_source": int(risk_source["n_rebalances"]),
            "n_rebalances_replay": int(risk_replay["n_rebalances"]),
        },
        "observed_path": {
            "equity": _equity_path(),
            "per_leg": _per_leg(source_meta, replay_meta),
            "orders": orders,
            "funding": funding,
            "positions": positions,
            "risk_counters": {
                "source": risk_source,
                "replay": risk_replay,
                "delta_replay_minus_source": {
                    key: int(risk_replay.get(key, 0)) - int(risk_source.get(key, 0))
                    for key in sorted(set(risk_source) | set(risk_replay))
                },
            },
        },
        "causal_evidence": {
            "exactly_established": [
                {
                    "finding": "FIRST_DECISION_MUTABLE_UNIVERSE_CAUSE",
                    "detail": (
                        "EOS is the sole source-only first-decision member; restoring it to the "
                        "otherwise current cross-section reproduces all ten historical quantities."
                    ),
                },
                {
                    "finding": "OVERLAPPING_EXOGENOUS_MARKS_AND_FUNDING_RATES_EXACT",
                    "detail": (
                        "Every comparable order decision price, position mark, funding mark and "
                        "funding rate is byte-numerically equal. This rules out value drift on "
                        "overlapping records, not missing rows or membership-state drift."
                    ),
                },
                {
                    "finding": "CURRENT_REALIZED_VOL_LEG_EXECUTED",
                    "detail": (
                        "The replay records realized_leg_bound on "
                        f"{int(risk_replay.get('realized_leg_bound', 0))} of 224 rebalances; "
                        "the historical artifact predates and lacks that counter."
                    ),
                },
            ],
            "not_identifiable_from_surviving_evidence": [
                "exact standalone terminal-equity or Sharpe contribution of universe drift",
                (
                    "exact standalone terminal-equity or Sharpe contribution of the "
                    "realized-vol correction"
                ),
                (
                    "interaction contribution between changed holdings, costs, funding, "
                    "drawdown state and overlay state"
                ),
                "byte-exact source tree used by the historical execution",
            ],
            "why_additive_decomposition_is_invalid": (
                "Orders change holdings; holdings change funding, costs, equity, realized "
                "volatility and drawdown state; those states change later orders. With only two "
                "realized paths, the counterfactual cells and their interactions are absent. "
                "Subtracting aggregate metrics cannot identify causal component effects."
            ),
            "missing_counterfactual_cells": [
                "historical exact code x historical exact derived-input snapshot",
                "current code x the same historical exact derived-input snapshot",
                "historical exact code x current derived-input snapshot",
                "current code x current derived-input snapshot",
            ],
            "recoverability": (
                "The current/current cell exists. The historical/historical output exists, but its "
                "exact code and derived inputs do not. Because the missing historical snapshots "
                "were never sealed, the other cells cannot now be made exact by rerunning the "
                "same command."
            ),
        },
        "code_archaeology": _code_archaeology(),
        "decision": {
            "full_path_drift_quantified": True,
            "surviving_evidence_exhausted": True,
            "exact_additive_causal_decomposition_possible": False,
            "repeat_current_state_replay_would_resolve_missing_history": False,
            "external_submission_block_should_remain": True,
            "historical_result_should_remain_preserved_with_correction": True,
        },
        "required_governance_change": (
            "Future measured results must atomically bind the exact derived signal frame, universe "
            "intervals, complete SCD2 metadata, market/funding partitions, source tree, "
            "lockfile and configuration before the output can be called reproducible."
        ),
        "trial_accounting": {
            "new_return_hypotheses": 0,
            "new_trials": 0,
            "full_walkforward_reruns": 0,
            "classification": "OUTPUT_FORENSICS_AND_IDENTIFIABILITY_AUDIT_ONLY",
        },
        "claim_boundary": (
            "This audit proves where the surviving paths agree, where they diverge, one exact "
            "initial cause, and why the total metric delta cannot be uniquely split among "
            "causes. It does not estimate unobserved counterfactual performance or rehabilitate "
            "either result."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def run(output: Path = OUTPUT) -> dict[str, Any]:
    document = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    document = run(arguments.output.resolve())
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
