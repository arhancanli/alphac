"""Measure the 2026-09-14 split-direction defect: pre-fix kernel and current one, side by side.

WHY. The kernel fix in #37 recorded its before-fix counts only in the merge message, and the
tracked audit (`artifacts/audit/split_adjustment_direction.json`) was regenerated after the fix,
so the size of the defect was not in any published artifact. This runs the SAME audit
(`scripts/audit_split_adjustment_direction.py`, same classes, same stored splits) twice on the
same lakes in one process: once with `adjusted_close` exactly as it was at the commit before the
fix (loaded from git by path and hashed, not re-typed), once with the current kernel. It also
records Apple's 2020-08-31 four-for-one through both.

It reads stored splits and raw bars only. It changes no lake, engine or result, opens no return
path and spends no identity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from alphaforge.core.time import Timeframe  # noqa: E402
from alphaforge.data.store.lake import LakePaths  # noqa: E402
from alphaforge.data.store.reader import PITDataReader  # noqa: E402

OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "split_direction_before_after.json"
KERNEL_PATH: Final[str] = "src/alphaforge/features/library/equity_price.py"
# The fix is 4395e24 (#37); its first parent is the last commit with the multiplying kernel.
PRE_FIX_COMMIT: Final[str] = "4395e24~1"
AAPL: Final[str] = "XUSE:CASH:AAPLUSD"
AAPL_EX_DATE: Final[dt.date] = dt.date(2020, 8, 31)
DAY_MS: Final[int] = Timeframe.D1.ms


def _load_audit() -> types.ModuleType:
    path = REPO / "scripts" / "audit_split_adjustment_direction.py"
    spec = importlib.util.spec_from_file_location("split_direction_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kernel_at(commit: str) -> tuple[types.ModuleType, str, str]:
    """The kernel module exactly as committed at ``commit``, its resolved sha and source hash."""
    sha = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", commit], check=True, capture_output=True, text=True
    ).stdout.strip()
    source = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{sha}:{KERNEL_PATH}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    module = types.ModuleType(f"equity_price_at_{sha[:12]}")
    module.__file__ = f"{sha}:{KERNEL_PATH}"
    # The historical file declares the same features as the current one; the registry rightly
    # refuses duplicate names, so registration is a no-op while the old kernel loads. Only its
    # adjusted_close is used.
    from alphaforge.features import registry

    original = registry.feature
    registry.feature = lambda spec_factory: spec_factory
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    finally:
        registry.feature = original
    return module, sha, "sha256:" + hashlib.sha256(source.encode()).hexdigest()


def summarize(lake_result: dict[str, Any]) -> dict[str, Any]:
    counts = lake_result["counts"]
    determined = sum(v for k, v in counts.items() if k != "UNDETERMINED")
    return {
        "splits": lake_result["splits"],
        "instruments_with_splits": lake_result["instruments_with_splits"],
        "counts": counts,
        "determined": determined,
        "storage_conventions": lake_result["storage_conventions"],
    }


def apple_example(lake: Path, kernels: dict[str, Any]) -> dict[str, Any] | None:
    reader = PITDataReader(LakePaths(lake))
    ex_ms = int(dt.datetime.combine(AAPL_EX_DATE, dt.time(), dt.UTC).timestamp() * 1000)
    start, end = ex_ms - 10 * DAY_MS, ex_ms + 10 * DAY_MS
    bars = reader.ohlcv([AAPL], start=start, end=end, as_of=end, tf=Timeframe.D1).to_pandas()
    actions = reader.corporate_actions([AAPL], start=start, end=end, as_of=end).to_pandas()
    splits = actions[actions["action_type"] == "split"]
    if bars.empty or splits.empty:
        return None
    bars["ts"] = (
        pd.to_datetime(bars["ts_open"], utc=True) - pd.Timestamp(0, tz="UTC")
    ) // pd.Timedelta(milliseconds=1)
    raw = bars.set_index("ts")["close"].astype("float64").to_frame(AAPL)
    frame = pd.DataFrame(
        {
            "instrument_id": [AAPL] * len(splits),
            "ex_date": (
                (pd.to_datetime(splits["ex_date"], utc=True) - pd.Timestamp(0, tz="UTC"))
                // pd.Timedelta(milliseconds=1)
            ).to_list(),
            "available_at": (
                (pd.to_datetime(splits["available_at"], utc=True) - pd.Timestamp(0, tz="UTC"))
                // pd.Timedelta(milliseconds=1)
            ).to_list(),
            "action_type": ["split"] * len(splits),
            "ratio": splits["ratio"].astype("float64").to_list(),
            "cash_amount": [float("nan")] * len(splits),
        }
    )
    before = raw[raw.index < ex_ms][AAPL].dropna()
    after = raw[raw.index >= ex_ms][AAPL].dropna()
    result: dict[str, Any] = {
        "instrument_id": AAPL,
        "ex_date": AAPL_EX_DATE.isoformat(),
        "stored_ratio": float(splits["ratio"].iloc[0]),
        "raw_close_before": round(float(before.iloc[-1]), 2),
        "raw_close_ex_date": round(float(after.iloc[0]), 2),
    }
    for name, kernel in kernels.items():
        adjusted = kernel.adjusted_close(raw, frame, tf_ms=DAY_MS, include_dividends=False)[AAPL]
        result[f"{name}_adjusted_close_before"] = round(
            float(adjusted[adjusted.index < ex_ms].dropna().iloc[-1]), 2
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lake", action="append", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args(argv)
    lakes = args.lake or [REPO / "data" / "lake", REPO / "data" / "lake_sharadar"]

    audit = _load_audit()
    pre_fix, pre_sha, pre_hash = kernel_at(PRE_FIX_COMMIT)
    from alphaforge.features.library import equity_price as current

    kernels = {"pre_fix": pre_fix, "current": current}
    results: list[dict[str, Any]] = []
    for lake in lakes:
        # Named as the repository names it (data/<lake>) wherever the lake is mounted.
        entry: dict[str, Any] = {"lake": f"data/{lake.name}"}
        for name, kernel in kernels.items():
            setattr(audit, "adjusted_close", kernel.adjusted_close)  # noqa: B010
            entry[name] = summarize(audit.audit_lake(lake, limit=None))
        entry["apple_2020"] = apple_example(lake, kernels)
        results.append(entry)

    document: dict[str, Any] = {
        "schema": "canli.alphac-split-direction-before-after.v1",
        "author": "Arhan Canli",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "audit": "scripts/audit_split_adjustment_direction.py (same classes and stored splits)",
        "classes": audit.classify.__doc__ or "see the audit script",
        "pre_fix_kernel": {
            "path": KERNEL_PATH,
            "commit": pre_sha,
            "source_sha256": pre_hash,
            "why": "first parent of 4395e24 (#37), the last commit whose kernel multiplied by the "
            "stored split factor",
        },
        "lakes": results,
        "claim_boundary": (
            "Counts what each kernel produces from what the lakes store today; splits ingested "
            "after 2026-09-14 are included, so these are not the merge message's figures. It "
            "changes no lake, engine or result, opens no return path and spends no identity."
        ),
    }
    document["content_hash"] = audit._content_hash(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for lake in results:
        print(
            lake["lake"], "pre_fix", lake["pre_fix"]["counts"], "current", lake["current"]["counts"]
        )
        print("  apple", lake["apple_2020"])
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
