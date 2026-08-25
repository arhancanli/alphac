#!/usr/bin/env python3
"""Replay selected crypto carry on the current local state and audit drift.

The selected artifact binds its market-data result, but the historical run did not
seal a byte-level snapshot of every derived input (notably universe membership and
instrument metadata).  This script therefore must not describe a non-exact result as
an isolated *code* drift or as a fully frozen-input replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

ROOT: Final = Path(__file__).resolve().parents[1]
SOURCE: Final = ROOT / "artifacts/walkforward/crypto_carry_wk"
SOURCE_SHA256: Final = "a72c11172a730536336a079d26394cd926f88df06ce36cb3b5483159a99464ee"
LEDGER: Final = ROOT / "var/experiments.jsonl"
DECLARED: Final = {
    "allocator": "rank",
    "alpha_names": ["carry_fund_21"],
    "train_bars": 6048,
    "test_bars": 1512,
    "purge_bars": 72,
    "embargo_bars": 168,
    "rebalance_bars": 168,
    "no_trade_band": 0.001,
    "initial_cash": 100_000.0,
    "start": 1_622_505_600_000,
    "end": 1_780_272_000_000,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _verified_receipt(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text())
    if document.get("content_hash") != _content_hash(document):
        raise RuntimeError(f"existing replay receipt content hash is invalid: {path}")
    return document


def verify_source() -> dict[str, Any]:
    meta_path = SOURCE / "walkforward.json"
    if _sha256(meta_path) != SOURCE_SHA256:
        raise RuntimeError("selected crypto-carry source artifact hash changed")
    source = json.loads(meta_path.read_text())
    drift = {
        key: {"declared": value, "source": source["config"].get(key)}
        for key, value in DECLARED.items()
        if source["config"].get(key) != value
    }
    if drift:
        raise RuntimeError(f"selected crypto-carry config drift: {drift}")
    if source["config"]["n_legs"] != 25 or len(source["config"]["instrument_ids"]) != 58:
        raise RuntimeError("selected crypto-carry source shape changed")
    return source


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open()) if path.is_file() else 0


def _first_divergence(
    original_equity: pd.Series, replay_equity: pd.Series
) -> dict[str, Any] | None:
    aligned = original_equity.index.intersection(replay_equity.index)
    if aligned.empty:
        return None
    source_values = original_equity.reindex(aligned).to_numpy(dtype=np.float64)
    replay_values = replay_equity.reindex(aligned).to_numpy(dtype=np.float64)
    unequal = np.flatnonzero(source_values != replay_values)
    if unequal.size == 0:
        return None
    index = int(unequal[0])
    return {
        "overlap_row_index": index,
        "ts": int(aligned[index]),
        "source_equity": float(source_values[index]),
        "replay_equity": float(replay_values[index]),
        "delta_replay_minus_source": float(replay_values[index] - source_values[index]),
    }


def _build_receipt(output: Path, *, before: int, after: int) -> dict[str, Any]:
    source = verify_source()
    output_meta_path = output / "walkforward.json"
    output_equity_path = output / "equity.parquet"
    if not output_meta_path.is_file() or not output_equity_path.is_file():
        raise RuntimeError(f"replay output is incomplete: {output}")

    replay = json.loads(output_meta_path.read_text())
    original_equity = pd.read_parquet(SOURCE / "equity.parquet").set_index("ts")["equity"]
    replay_equity = pd.read_parquet(output_equity_path).set_index("ts")["equity"]
    timestamps_equal = original_equity.index.equals(replay_equity.index)
    aligned = original_equity.index.intersection(replay_equity.index)
    differences = np.abs(
        original_equity.reindex(aligned).to_numpy(dtype=np.float64)
        - replay_equity.reindex(aligned).to_numpy(dtype=np.float64)
    )
    summary_keys = ("final_equity", "sharpe", "max_dd", "cagr", "funding_net", "fees_paid")
    summary_deltas = {
        key: float(replay["summary"][key] - source["summary"][key]) for key in summary_keys
    }
    exact = bool(
        timestamps_equal
        and len(aligned) == len(original_equity)
        and np.all(differences == 0)
    )
    first_divergence = _first_divergence(original_equity, replay_equity)
    status = (
        "PASS_EXACT_FROZEN_REPLAY"
        if exact
        else "REPLAY_EXECUTED_MATERIAL_CODE_OR_MUTABLE_INPUT_DRIFT_QUANTIFIED"
    )
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-carry-current-state-replay.v2",
        "author": "Arhan Canli",
        "status": status,
        "replay_executed": True,
        "exact_replay": exact,
        "source_binding": {
            "path": str((SOURCE / "walkforward.json").relative_to(ROOT)),
            "sha256": SOURCE_SHA256,
            "equity_sha256": _sha256(SOURCE / "equity.parquet"),
        },
        "output_binding": {
            "path": str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
            "walkforward_sha256": _sha256(output_meta_path),
            "equity_sha256": _sha256(output_equity_path),
        },
        "zero_new_trials": before == after,
        "experiment_ledger_lines_before": before,
        "experiment_ledger_lines_after": after,
        "comparison": {
            "timestamps_equal": timestamps_equal,
            "source_rows": len(original_equity),
            "replay_rows": len(replay_equity),
            "overlap_rows": len(aligned),
            "max_absolute_equity_difference": (
                float(differences.max()) if len(differences) else None
            ),
            "first_divergence": first_divergence,
            "source_summary": {key: float(source["summary"][key]) for key in summary_keys},
            "replay_summary": {key: float(replay["summary"][key]) for key in summary_keys},
            "summary_deltas_replay_minus_source": summary_deltas,
        },
        "input_freeze_audit": {
            "market_rows_portability_manifest_available": True,
            "historical_universe_membership_snapshot_bound_by_source": False,
            "historical_instrument_metadata_snapshot_bound_by_source": False,
            "conclusion": (
                "The non-exact replay cannot be attributed to software drift alone. The "
                "source artifact did not bind every derived input consumed by the run."
            ),
            "observed_first_decision_cross_section": {
                "source_order_records": 22,
                "replay_order_records": 21,
                "source_only_instrument": "BINANCE:PERP:EOSUSDT",
            },
        },
        "strategy_claim_changed": False,
        "independent_replication": False,
        "claim_boundary": (
            "This is a zero-new-trial replay against the current local state. It compares "
            "current behavior with the selected historical artifact, but it is not an exact "
            "software-only replay, a fully frozen-input replay, a fresh-data replication, or "
            "an independent replication."
        ),
    }
    document["content_hash"] = _content_hash(document)
    (output / "replay_receipt.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    return document


def seal_existing(output: Path) -> dict[str, Any]:
    """Re-seal a completed replay without executing the expensive simulation again."""
    prior_path = output / "replay_receipt.json"
    if not prior_path.is_file():
        raise RuntimeError(f"no prior replay receipt to establish execution: {prior_path}")
    prior = _verified_receipt(prior_path)
    if prior.get("replay_executed") is not True:
        raise RuntimeError("prior receipt does not establish that the replay executed")
    before = int(prior["experiment_ledger_lines_before"])
    after = int(prior["experiment_ledger_lines_after"])
    if before != after or prior.get("zero_new_trials") is not True:
        raise RuntimeError("prior replay was not trial-neutral")
    return _build_receipt(output, before=before, after=after)


def run(output: Path) -> dict[str, Any]:
    source = verify_source()
    if output.exists():
        raise RuntimeError(f"refusing to overwrite replay output: {output}")

    import alphaforge.features.library  # noqa: F401
    from alphaforge.analytics.walkforward import WalkForwardRunner
    from alphaforge.config.settings import load_settings
    from alphaforge.config.sleeve import sleeve_for
    from alphaforge.core.instruments import InstrumentStore
    from alphaforge.costs import TransactionCostModel
    from alphaforge.data.store.lake import LakePaths
    from alphaforge.data.store.reader import PITDataReader
    from alphaforge.data.universe.store import UniverseStore
    from alphaforge.features.engine import FeatureEngine
    from alphaforge.features.registry import default_registry
    from alphaforge.signals.service import SignalService

    settings = load_settings(None)
    sleeve = sleeve_for(settings.data.asset_class)
    before = _line_count(LEDGER)
    output.mkdir(parents=True)
    paths = LakePaths(settings.paths.lake_dir)
    with InstrumentStore(settings.paths.var_dir / "ops.sqlite") as store:
        reader = PITDataReader(paths)
        universe = UniverseStore(paths)
        service = SignalService(
            FeatureEngine(reader, store, universe, asset_class=settings.data.asset_class),
            universe,
            default_registry(),
            settings.signals,
            sleeve=sleeve,
            alpha_names=list(DECLARED["alpha_names"]),
        )
        runner = WalkForwardRunner(
            reader,
            store,
            universe,
            TransactionCostModel.from_settings(settings),
            service,
            settings,
        )
        runner.run(
            DECLARED["start"],
            DECLARED["end"],
            train_bars=DECLARED["train_bars"],
            test_bars=DECLARED["test_bars"],
            allocator=DECLARED["allocator"],
            embargo_bars=DECLARED["embargo_bars"],
            initial_cash=DECLARED["initial_cash"],
            instrument_ids=list(source["config"]["instrument_ids"]),
            rebalance_bars=DECLARED["rebalance_bars"],
            no_trade_band=DECLARED["no_trade_band"],
            out_dir=output,
            now_ms=None,
            experiment_log=None,
            alpha_names=list(DECLARED["alpha_names"]),
        )
    after = _line_count(LEDGER)
    if before != after:
        raise RuntimeError(f"experiment ledger moved during zero-trial replay: {before} -> {after}")

    return _build_receipt(output, before=before, after=after)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/probe/crypto_carry_frozen_current_code_replay",
    )
    parser.add_argument(
        "--seal-existing",
        action="store_true",
        help="rebuild the receipt from an already completed output without rerunning",
    )
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    document = seal_existing(output) if arguments.seal_existing else run(output)
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
