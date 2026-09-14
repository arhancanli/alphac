"""Prepare an isolated candidate lake. Never publish, promote, or mutate the source.

The scheduled tick uses this staging-only workflow. A successful candidate is only
ready for review; historical value changes or incomplete acquisition quarantine it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

SERIES = ("PCPI", "PCPIX", "EMPLOY", "IPT", "RUC", "HSTARTS", "RCONM")
BUILDER = Path(__file__).with_name("probe_econtrend_data.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builder():
    spec = importlib.util.spec_from_file_location("isolated_macro_builder", BUILDER)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def required_files() -> set[str]:
    builder = load_builder()
    return (
        {f"tier1_daily/{name}.parquet" for name in builder.TIER1}
        | {
            f"tier2_vintage/{name}_{suffix}.parquet"
            for name in SERIES
            for suffix in ("vintage_long", "first_release")
        }
        | {f"revised_reference/{name}_current.parquet" for name in builder.REVISED_REF}
        | {f"raw/rtdsm/{entry[1]}" for entry in builder.TIER2.values()}
    )


def inventory(lake: Path) -> dict[str, str]:
    return {str(p.relative_to(lake)): digest(p) for p in sorted(lake.rglob("*")) if p.is_file()}


def compare_series(old: pd.DataFrame, new: pd.DataFrame) -> dict:
    keys = ["obs_period", "vintage_date"]
    for frame in (old, new):
        if frame[keys].isna().any().any() or frame.duplicated(keys).any():
            raise ValueError("Missing or duplicate observation/vintage identity")
        if frame["value"].isin([float("inf"), -float("inf")]).any():
            raise ValueError("Infinite macro value")
    joined = old.merge(new, on=keys, how="outer", suffixes=("_old", "_new"), indicator=True)
    both = joined["_merge"] == "both"
    equal = (joined.value_old == joined.value_new) | (
        joined.value_old.isna() & joined.value_new.isna()
    )
    historical_additions = (
        (joined["_merge"] == "right_only")
        & (joined.vintage_date <= old.vintage_date.max())
        & joined.value_new.notna()
    )
    result = {
        "changed_existing_cells": int((both & ~equal).sum()),
        "removed_existing_cells": int((joined["_merge"] == "left_only").sum()),
        "new_populated_historical_cells": int(historical_additions.sum()),
        "new_blank_cells": int(
            ((joined["_merge"] == "right_only") & joined.value_new.isna()).sum()
        ),
        "new_vintages": sorted(
            str(v.date()) for v in set(new.vintage_date) - set(old.vintage_date)
        ),
    }
    result["passes"] = not any(
        result[key]
        for key in (
            "changed_existing_cells",
            "removed_existing_cells",
            "new_populated_historical_cells",
        )
    )
    return result


def build_into(lake: Path) -> int:
    # Subprocess-only builder context: all writes are redirected before build().
    if not lake.is_dir() or any(lake.iterdir()) or lake.is_symlink():
        raise ValueError("Candidate must be an empty, real directory")
    builder = load_builder()
    from macro_refresh_transport import get

    builder._get = get
    builder.LAKE = lake
    builder.T1_DIR = lake / "tier1_daily"
    builder.T2_DIR = lake / "tier2_vintage"
    builder.RAW_DIR = lake / "raw/rtdsm"
    builder.REF_DIR = lake / "revised_reference"
    return builder.build()


def stage(source: Path, output_parent: Path, timeout: int = 900, runner=subprocess.run) -> dict:
    source, output_parent = source.resolve(), output_parent.resolve()
    if (
        not source.is_dir()
        or output_parent == source
        or output_parent.is_relative_to(source)
        or source.is_relative_to(output_parent)
    ):
        raise ValueError("Output must be separate from the source lake and its ancestors")
    before = inventory(source)
    output_parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="macro-candidate-", dir=output_parent))
    candidate = run / "lake"
    candidate.mkdir()
    report = {
        "schema": "alphac.macro-refresh-candidate.v1",
        "source": str(source),
        "candidate": str(candidate),
        "source_hashes_before": before,
        "status": "QUARANTINED",
        "production_promoted": False,
        "series": {},
        "builder_sha256": digest(BUILDER),
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        result = runner(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--build-into", str(candidate)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        (run / "build.stdout.log").write_text(result.stdout or "")
        (run / "build.stderr.log").write_text(result.stderr or "")
        if result.returncode:
            raise RuntimeError(f"Builder exited {result.returncode}; candidate not promoted")
        meta = json.loads((candidate / "meta.json").read_text())
        required = required_files()
        for relative in required:
            file = candidate / relative
            if not file.is_file() or file.is_symlink() or file.stat().st_size == 0:
                raise ValueError(f"Missing/invalid required candidate file: {relative}")
            if relative.endswith(".parquet") and relative not in meta["files"]:
                raise ValueError(f"Candidate file absent from metadata: {relative}")
        for relative, expected in meta["files"].items():
            file = (candidate / relative).resolve()
            if (
                not file.is_relative_to(candidate)
                or not file.is_file()
                or digest(file)[:16] != expected
            ):
                raise ValueError("Candidate metadata/file hash mismatch")
        observed = datetime.now(UTC).isoformat()
        arrivals = []
        for name in SERIES:
            path = f"tier2_vintage/{name}_vintage_long.parquet"
            old, new = pd.read_parquet(source / path), pd.read_parquet(candidate / path)
            if new.empty or not new.value.notna().any():
                raise ValueError(f"Empty candidate series: {name}")
            comparison = compare_series(old, new)
            report["series"][name] = comparison
            for vintage in comparison["new_vintages"]:
                arrivals.append(
                    {
                        "series": name,
                        "vintage_date": vintage,
                        "observed_in_candidate_at": observed,
                        "production_arrival_recorded": False,
                    }
                )
        report["candidate_observations"] = arrivals
        if all(row["passes"] for row in report["series"].values()):
            report["status"] = "READY_FOR_REVIEW_NOT_PROMOTED"
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["failure"] = f"{type(error).__name__}: {error}"
    try:
        report["source_unchanged"] = source.is_dir() and inventory(source) == before
    except OSError as error:
        report["source_unchanged"] = False
        report["source_inventory_error"] = f"{type(error).__name__}: {error}"
    if not report["source_unchanged"]:
        report["status"] = "QUARANTINED"
        report["failure"] = "Source changed concurrently; rebase on a stable snapshot before review"
    report["candidate_hashes"] = inventory(candidate)
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["report_path"] = str(run / "report.json")
    (run / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lake", type=Path)
    parser.add_argument("--output-parent", type=Path)
    parser.add_argument("--build-into", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.build_into:
        raise SystemExit(build_into(args.build_into))
    if not args.source_lake or not args.output_parent:
        parser.error("--source-lake and --output-parent are required")
    outcome = stage(args.source_lake, args.output_parent)
    print(json.dumps({"status": outcome["status"], "report_path": outcome["report_path"]}))
    raise SystemExit(0 if outcome["status"] == "READY_FOR_REVIEW_NOT_PROMOTED" else 1)
