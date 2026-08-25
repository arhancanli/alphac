#!/usr/bin/env python3
"""Intersect unresolved split events with the sealed operating-margin execution path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq

REPO: Final[Path] = Path(__file__).resolve().parents[1]
CONTEXT: Final[Path] = REPO / "artifacts" / "audit" / "unresolved_split_event_context.json"
LIFECYCLE: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_split_lifecycle_scope.json"
REPLAY: Final[Path] = (
    REPO / "artifacts" / "probe" / "fundamental_single_replays" / "e5f48adc25065ce9"
)
OUTPUT: Final[Path] = (
    REPO / "artifacts" / "audit" / "operating_margin_unresolved_split_exposure.json"
)
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
DAY_MS: Final[int] = 86_400_000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(REPO)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def classify_exposure(*, held: bool, queued: bool, in_window: bool) -> str:
    if not in_window:
        return "EVENT_OUTSIDE_SEALED_REPLAY_WINDOW"
    if held:
        return "OBSERVED_HELD_PRE_BOUNDARY"
    if queued:
        return "OBSERVED_QUEUED_PRE_BOUNDARY"
    return "NO_OBSERVED_PRE_BOUNDARY_EXPOSURE"


def _read_nonempty(path: Path, columns: list[str]) -> pd.DataFrame:
    table = pq.read_table(path)
    if table.num_rows == 0:
        return pd.DataFrame(columns=columns)
    return table.select(columns).to_pandas()


def build() -> dict[str, Any]:
    context = json.loads(CONTEXT.read_text(encoding="utf-8"))
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
    context_by_key = {
        (row["instrument_id"], row["ex_date"]): row["context_classification"]
        for row in context["events"]
    }
    events = [
        row
        for row in lifecycle["events"]
        if row["lifecycle_classification"] == "WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION"
        and str(row["ex_date"])[:10] >= "2005-01-03"
    ]
    legs: list[dict[str, Any]] = []
    lineage_paths: list[Path] = []
    for leg_dir in sorted((REPLAY / "legs").glob("leg_*")):
        meta_path = leg_dir / "run_meta.json"
        positions_path = leg_dir / "positions.parquet"
        orders_path = leg_dir / "orders.parquet"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))["config"]
        legs.append(
            {
                "leg": leg_dir.name,
                "start": int(meta["start"]),
                "end": int(meta["end"]),
                "positions": _read_nonempty(positions_path, ["ts", "instrument_id", "qty"]),
                "orders": _read_nonempty(
                    orders_path, ["decision_ts", "instrument_id", "status", "qty"]
                ),
            }
        )
        lineage_paths.extend([meta_path, positions_path, orders_path])
    replay_start = min(leg["start"] for leg in legs)
    replay_end = max(leg["end"] for leg in legs)
    rows: list[dict[str, Any]] = []
    for event in events:
        event_ms = int(pd.Timestamp(event["ex_date"]).timestamp() * 1000)
        iid = event["instrument_id"]
        in_window = replay_start <= event_ms < replay_end
        held_rows: list[dict[str, Any]] = []
        queued_rows: list[dict[str, Any]] = []
        if in_window:
            positions = pd.concat(
                [leg["positions"] for leg in legs if leg["start"] <= event_ms < leg["end"]],
                ignore_index=True,
            )
            instrument_positions = positions.loc[
                (positions["instrument_id"] == iid) & (positions["ts"] < event_ms)
            ]
            if not instrument_positions.empty:
                latest_ts = int(instrument_positions["ts"].max())
                latest = instrument_positions.loc[instrument_positions["ts"] == latest_ts]
                held_rows = [
                    {"ts": int(row.ts), "qty": float(row.qty)}
                    for row in latest.itertuples(index=False)
                    if float(row.qty) != 0.0
                ]
            orders = pd.concat(
                [leg["orders"] for leg in legs if leg["start"] <= event_ms < leg["end"]],
                ignore_index=True,
            )
            candidates = orders.loc[
                (orders["instrument_id"] == iid)
                & (orders["decision_ts"] < event_ms)
                & (orders["decision_ts"] >= event_ms - 7 * DAY_MS)
                & (orders["status"] == "queued")
            ]
            queued_rows = [
                {
                    "decision_ts": int(row.decision_ts),
                    "qty": float(row.qty),
                    "status": str(row.status),
                }
                for row in candidates.itertuples(index=False)
            ]
        classification = classify_exposure(
            held=bool(held_rows), queued=bool(queued_rows), in_window=in_window
        )
        rows.append(
            {
                "instrument_id": iid,
                "ticker": event["ticker"],
                "ex_date": event["ex_date"],
                "stored_ratio": event["stored_ratio"],
                "provider_classification": event["provider_classification"],
                "context_classification": context_by_key.get(
                    (event["instrument_id"], event["ex_date"]),
                    "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO",
                ),
                "exposure_classification": classification,
                "held_evidence": held_rows,
                "queued_order_evidence": queued_rows,
            }
        )
    counts = pd.Series([row["exposure_classification"] for row in rows]).value_counts()
    payload: dict[str, Any] = {
        "schema": "canli.alphac-operating-margin-failed-split-exposure-audit.v2",
        "author": "Arhan Canli",
        "decision": "SEALED_PATH_SPLIT_EXPOSURE_AUDITED_REPLAY_NOT_AUTHORIZED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "summary": {
            "post_2005_in_lifecycle_failed_events": len(rows),
            "independent_provider_confirmed_events": sum(
                row["provider_classification"]
                == "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO"
                for row in rows
            ),
            "unresolved_events": sum(
                row["provider_classification"]
                != "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO"
                for row in rows
            ),
            "observed_held_pre_boundary": int(counts.get("OBSERVED_HELD_PRE_BOUNDARY", 0)),
            "observed_queued_pre_boundary": int(
                counts.get("OBSERVED_QUEUED_PRE_BOUNDARY", 0)
            ),
            "no_observed_pre_boundary_exposure": int(
                counts.get("NO_OBSERVED_PRE_BOUNDARY_EXPOSURE", 0)
            ),
            "outside_sealed_replay_window": int(
                counts.get("EVENT_OUTSIDE_SEALED_REPLAY_WINDOW", 0)
            ),
        },
        "events": rows,
        "lineage": {
            "context_path": str(CONTEXT.relative_to(REPO)),
            "context_sha256": _sha256(CONTEXT),
            "context_content_hash": context["content_hash"],
            "lifecycle_path": str(LIFECYCLE.relative_to(REPO)),
            "lifecycle_sha256": _sha256(LIFECYCLE),
            "lifecycle_content_hash": lifecycle["content_hash"],
            "sealed_replay_path": str(REPLAY.relative_to(REPO)),
            "execution_path_files": len(lineage_paths),
            "execution_path_tree_sha256": _tree_hash(lineage_paths),
            "replay_start_ms": replay_start,
            "replay_end_ms": replay_end,
        },
        "required_next_action": (
            "Resolve every event with observed pre-boundary exposure using issuer evidence. "
            "Treat no-observed-exposure classifications as historical-path evidence only; do not "
            "assume they prove a future replay cannot select the instrument."
        ),
        "claim_boundary": (
            "This reads only sealed order and position artifacts, not equity or return series. "
            "It does not authorize replay, establish counterfactual exposure, or validate "
            "performance."
        ),
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main() -> int:
    payload = build()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    for host in HOSTS:
        host.parent.mkdir(parents=True, exist_ok=True)
        host.write_text(rendered, encoding="utf-8")
    print(json.dumps({"summary": payload["summary"], "content_hash": payload["content_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
