"""Recover and validate existing per-leg references without measuring a new strategy."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/alphamax-reference-recovery-20260912"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def check_stitch(reference, legs):
    if not legs:
        raise ValueError("No leg equity references")
    stitched = pd.concat(legs, ignore_index=True)
    if list(stitched.columns) != ["ts", "equity"] or list(reference.columns) != ["ts", "equity"]:
        raise ValueError("Expected canonical equity schema")
    if not stitched.ts.is_monotonic_increasing or stitched.ts.duplicated().any():
        raise ValueError("Leg timestamps must be unique and strictly ordered")
    if not np.isfinite(stitched.equity).all() or not (stitched.equity > 0).all():
        raise ValueError("Invalid leg equity")
    if not reference.reset_index(drop=True).equals(stitched):
        raise ValueError("Per-leg equity does not reproduce the preserved reference")
    return {"leg_count": len(legs), "equity_rows": len(stitched), "frame_exact": True}


def main():
    OUT.mkdir(exist_ok=False)
    sources = OUT / "sources"
    sources.mkdir()
    bindings = {}
    for name in [
        "alphamax_upstream_replay_manifest.json",
        "alphamax_upstream_clean_workspace.json",
    ]:
        source = PROD / "artifacts/publication" / name
        shutil.copy2(source, sources / name)
        bindings[name] = sha(sources / name)
    shutil.copy2(Path(__file__), sources / Path(__file__).name)
    bindings[Path(__file__).name] = sha(sources / Path(__file__).name)
    manifest = json.loads((sources / "alphamax_upstream_replay_manifest.json").read_text())
    receipt = json.loads((sources / "alphamax_upstream_clean_workspace.json").read_text())
    for document in [manifest, receipt]:
        content = {k: v for k, v in document.items() if k != "content_hash"}
        assert (
            document["content_hash"]
            == "sha256:"
            + hashlib.sha256(
                json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
    reference = PROD / manifest["private_reference_output"]["path"]
    write(
        OUT / "protocol.json",
        {
            "scope": "EXISTING_REFERENCE_RECOVERY_NO_REPLAY",
            "source": str(reference),
            "bindings": bindings,
            "checks": [
                "Validate all five originally sealed root files",
                "Freeze every currently available reference output file",
                "Require 12 leg equity files to concatenate exactly to reference",
                "Require leg boundaries and cash continuity to match root metadata",
            ],
            "new_return_trials": 0,
            "production_mutations": False,
        },
    )
    for row in manifest["private_reference_output"]["records"]:
        source = reference / row["path"]
        assert source.stat().st_size == row["bytes"] and sha(source) == row["sha256"]
    destination = OUT / "reference_output"
    inventory = []
    for source in sorted(reference.rglob("*")):
        if source.is_symlink():
            raise ValueError("Reference symlink is not immutable input evidence")
        if not source.is_file():
            continue
        relative = source.relative_to(reference)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(source)
        shutil.copy2(source, target)
        assert before == sha(target) == sha(source)
        inventory.append({"path": str(relative), "sha256": before, "bytes": target.stat().st_size})
    write(OUT / "inventory.json", inventory)
    wf = json.loads((destination / "walkforward.json").read_text())
    legs = sorted(destination.glob("legs/leg_*"))
    assert len(legs) == len(wf["legs"]) == 12
    frames = [pd.read_parquet(leg / "equity.parquet") for leg in legs]
    result = check_stitch(pd.read_parquet(destination / "equity.parquet"), frames)
    checks = []
    for i, (leg, frame, stored) in enumerate(zip(legs, frames, wf["legs"], strict=True)):
        metadata = json.loads((leg / "run_meta.json").read_text())
        assert metadata["config"]["start"] == stored["test_start"]
        assert metadata["config"]["end"] == stored["test_end"]
        assert stored["leg"] == i
        assert frame.equity.iloc[-1] == stored["summary"]["final_equity"]
        if i:
            assert frames[i - 1].equity.iloc[-1] == frame.equity.iloc[0]
        fills = pd.read_parquet(leg / "fills.parquet")
        orders = pd.read_parquet(leg / "orders.parquet")
        positions = pd.read_parquet(leg / "positions.parquet")
        checks.append(
            {
                "leg": i,
                "rows": len(frame),
                "fills": len(fills),
                "orders": len(orders),
                "position_rows": len(positions),
                "final_equity": float(frame.equity.iloc[-1]),
                "boundary_and_initial_cash_match": True,
            }
        )
    acquisition = PROD / manifest["private_input_snapshot"]["private_inventory_receipt"]["path"]
    receipt_hash = manifest["private_input_snapshot"]["private_inventory_receipt"]["sha256"]
    assert sha(acquisition) == receipt_hash
    # The older replay script deliberately destroyed its temporary output tree.
    result.update(
        {
            "files_frozen": len(inventory),
            "legs": checks,
            "original_root_manifest_verified": True,
            "acquisition_inventory_hash_verified": True,
            "all_79915_raw_input_files_rehashed_this_turn": False,
            "legacy_claim_superseded": "Per-leg references are available and reproduce the root curve",
            "historical_capture_time_proven": False,
            "fresh_replay_output_retained": False,
            "replay_equity_search": {
                "scope": "634 non-leg equity artifacts under production artifacts",
                "hash": receipt["comparison"]["equity_curve"]["replay_sha256"],
                "matches": 0,
                "limit": "Files under 100KB checked; not a filesystem-wide absence proof",
            },
            "exact_strategy_reproduction": False,
            "cause_of_replay_mismatch": "UNDETERMINED: vendor, membership and dirty-source gaps remain",
            "next_replay_requirement": "Retain full replay outputs before cleanup; "
            "Bind code, inputs and reference; locate the first differing session/order/fill. "
            "A rerun requires accounting preflight; do not alter the reference to match it.",
            "new_return_trials": 0,
            "union_hypotheses": 238,
        }
    )
    write(OUT / "result.json", result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "leg_count",
                    "equity_rows",
                    "frame_exact",
                    "files_frozen",
                    "exact_strategy_reproduction",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
