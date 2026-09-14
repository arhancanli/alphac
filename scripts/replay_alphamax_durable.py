"""Replay an already-counted AlphaMax identity; retain workspace and every output."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from alphaforge.validation.experiments import ExperimentUnion, hypothesis_hash

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "artifacts/analysis/alphamax_durable_replay_20260912"


def write(path, obj):
    with path.open("x") as f:
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def main():
    spec = importlib.util.spec_from_file_location(
        "legacy_max", PROD / "scripts/run_alphamax_upstream_clean_workspace.py"
    )
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    manifest = json.loads(legacy.MANIFEST.read_text())
    ref = PROD / manifest["private_reference_output"]["path"]
    ref_config = json.loads((ref / "walkforward.json").read_text())["config"]
    keys = [
        "allocator",
        "alpha_names",
        "end",
        "instrument_ids",
        "no_trade_band",
        "rebalance_bars",
        "start",
        "test_bars",
        "train_bars",
    ]
    config = {k: ref_config[k] for k in keys}
    OUT.mkdir(exist_ok=False)
    union = ExperimentUnion.discover(OUT / "experiments.jsonl", ROOT)
    assert any(hypothesis_hash(r.config) == hypothesis_hash(config) for r in union.all())
    union.preflight_registration(config)
    write(
        OUT / "protocol.json",
        {
            "scope": "EXISTING_IDENTITY_REPRODUCTION_NOT_OPTIMIZATION",
            "created_at": datetime.now(UTC).isoformat(),
            "hypothesis": hypothesis_hash(config),
            "config": config,
            "union_before": union.n_hypotheses(),
            "new_hypotheses": 0,
            "source_commit": legacy.SOURCE_COMMIT,
            "manifest_sha256": legacy._sha256(legacy.MANIFEST),
            "runner_sha256": legacy._sha256(Path(__file__)),
            "legacy_runner_sha256": legacy._sha256(
                PROD / "scripts/run_alphamax_upstream_clean_workspace.py"
            ),
            "retention": "Retain all workspace outputs and logs, including failures",
            "validation": "Historical validation is not a current admission test",
            "reference_recovery": "evidence/alphamax-reference-recovery-20260912/inventory.json",
        },
    )
    print("Preflight passed; validating 79,915 sealed input files.", flush=True)
    snapshot, reference, _ = legacy._validate_manifest(manifest)
    write(
        OUT / "input_validation.json",
        {"all_input_files_verified": True, "manifest": manifest["content_hash"]},
    )
    workspace = OUT / "workspace"
    workspace.mkdir()
    source = legacy._safe_extract_git_archive(workspace)
    assert source["git_archive_sha256"] == manifest["source_reconstruction"]["git_archive_sha256"]
    write(OUT / "source.json", source)
    os.symlink(snapshot / "data", workspace / "data", target_is_directory=True)
    shutil.copytree(snapshot / "var", workspace / "var")
    for name, command in [
        ("environment", ["uv", "sync", "--frozen"]),
        ("replay", list(legacy.REPLAY_COMMAND)),
    ]:
        print(f"Starting {name}; logs and workspace are durable.", flush=True)
        with (
            (OUT / f"{name}.stdout.log").open("x") as stdout,
            (OUT / f"{name}.stderr.log").open("x") as stderr,
        ):
            result = subprocess.run(
                command, cwd=workspace, stdout=stdout, stderr=stderr, check=False
            )
        write(OUT / f"{name}.json", {"command": command, "returncode": result.returncode})
        if result.returncode:
            raise RuntimeError(f"{name} failed; workspace retained")
    output = workspace / "outputs/k30_dn_63"
    comparison = {
        "equity": legacy._equity_comparison(
            reference / "equity.parquet", output / "equity.parquet"
        ),
        "metadata": legacy._json_comparison(
            reference / "walkforward.json", output / "walkforward.json"
        ),
    }
    write(OUT / "comparison.json", comparison)
    write(OUT / "output_inventory.json", legacy._file_index(output))
    assert json.loads((output / "walkforward.json").read_text())["config"] == ref_config
    assert union.n_hypotheses() == 238
    print(json.dumps(comparison["equity"], indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        if OUT.exists() and not (OUT / "failure.json").exists():
            write(
                OUT / "failure.json",
                {
                    "error_type": type(error).__name__,
                    "workspace_retained": (OUT / "workspace").exists(),
                },
            )
        raise
