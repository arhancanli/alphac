#!/usr/bin/env python3
"""Attach frozen ACTIONS context to the split events still requiring resolution."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
LIFECYCLE: Final[Path] = REPO / "artifacts" / "audit" / "sharadar_split_lifecycle_scope.json"
ACTIONS_ARCHIVE: Final[Path] = REPO / "data" / "sharadar_raw" / "ACTIONS.zip"
OUTPUT: Final[Path] = REPO / "artifacts" / "audit" / "unresolved_split_event_context.json"
HOSTS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "glassbox" / OUTPUT.name,
    REPO.parent / "meridian-app" / "public" / "glassbox" / OUTPUT.name,
)
CONTEXT_ACTIONS: Final[set[str]] = {
    "listed",
    "delisted",
    "acquisitionby",
    "acquisitionof",
    "mergerfrom",
    "mergerto",
    "spinoff",
    "spinoffdividend",
    "adrratiosplit",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def classify_context(*, event_date: str, nearby_actions: list[dict[str, Any]]) -> str:
    event = pd.Timestamp(event_date).date()
    actions = {str(row["action"]) for row in nearby_actions}
    same_day = {
        str(row["action"])
        for row in nearby_actions
        if pd.Timestamp(row["date"]).date() == event
    }
    if same_day & {"listed", "delisted"}:
        return "SAME_DAY_LISTING_OR_DELISTING_CONTEXT"
    if actions & {"acquisitionby", "acquisitionof", "mergerfrom", "mergerto"}:
        return "NEARBY_ACQUISITION_OR_MERGER_CONTEXT"
    if actions & {"spinoff", "spinoffdividend"}:
        return "NEARBY_SPINOFF_CONTEXT"
    if "adrratiosplit" in actions:
        return "NEARBY_ADR_RATIO_CONTEXT"
    if event.weekday() >= 5:
        return "WEEKEND_SPLIT_WITHOUT_LIFECYCLE_CONTEXT"
    return "PLAIN_SPLIT_WITHOUT_LIFECYCLE_CONTEXT"


def _raw_actions() -> pd.DataFrame:
    with zipfile.ZipFile(ACTIONS_ARCHIVE) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected exactly one ACTIONS CSV")
        with archive.open(names[0]) as stream:
            frame = pd.read_csv(stream, dtype={"ticker": str, "contraticker": str})
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    return frame


def build() -> dict[str, Any]:
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
    unresolved = [
        row
        for row in lifecycle["events"]
        if row["lifecycle_classification"]
        in {"WITHIN_PRICE_LIFECYCLE_REQUIRES_RESOLUTION", "NO_FROZEN_TICKER_LIFECYCLE"}
        and row["provider_classification"] != "INDEPENDENT_PROVIDER_CONFIRMS_STORED_RATIO"
    ]
    actions = _raw_actions()
    rows: list[dict[str, Any]] = []
    for event in unresolved:
        ticker = event["ticker"]
        date = pd.Timestamp(event["ex_date"]).tz_localize(None).normalize()
        near = actions.loc[
            (
                (actions["ticker"].str.upper() == ticker)
                | (actions["contraticker"].fillna("").str.upper() == ticker)
            )
            & actions["action"].isin(CONTEXT_ACTIONS)
            & ((actions["date"] - date).abs() <= pd.Timedelta(days=7))
        ].copy()
        nearby = [
            {
                "date": row.date.date().isoformat(),
                "action": str(row.action),
                "ticker": str(row.ticker),
                "value": None if pd.isna(row.value) else float(row.value),
                "contraticker": None if pd.isna(row.contraticker) else str(row.contraticker),
            }
            for row in near.sort_values(["date", "action", "ticker"]).itertuples(index=False)
        ]
        rows.append(
            {
                **event,
                "nearby_action_context": nearby,
                "context_classification": classify_context(
                    event_date=event["ex_date"], nearby_actions=nearby
                ),
            }
        )
    counts = pd.Series([row["context_classification"] for row in rows]).value_counts()
    payload: dict[str, Any] = {
        "schema": "canli.alphac-unresolved-split-event-context-audit.v1",
        "author": "Arhan Canli",
        "decision": "UNRESOLVED_SPLIT_CONTEXT_AUDITED_NO_REPAIR_AUTHORIZED",
        "hypotheses_spent": 0,
        "return_data_opened": False,
        "summary": {
            "events": len(rows),
            "same_day_listing_or_delisting_context": int(
                counts.get("SAME_DAY_LISTING_OR_DELISTING_CONTEXT", 0)
            ),
            "nearby_acquisition_or_merger_context": int(
                counts.get("NEARBY_ACQUISITION_OR_MERGER_CONTEXT", 0)
            ),
            "nearby_spinoff_context": int(counts.get("NEARBY_SPINOFF_CONTEXT", 0)),
            "nearby_adr_ratio_context": int(counts.get("NEARBY_ADR_RATIO_CONTEXT", 0)),
            "weekend_without_lifecycle_context": int(
                counts.get("WEEKEND_SPLIT_WITHOUT_LIFECYCLE_CONTEXT", 0)
            ),
            "plain_without_lifecycle_context": int(
                counts.get("PLAIN_SPLIT_WITHOUT_LIFECYCLE_CONTEXT", 0)
            ),
        },
        "events": rows,
        "lineage": {
            "lifecycle_path": str(LIFECYCLE.relative_to(REPO)),
            "lifecycle_sha256": _sha256(LIFECYCLE),
            "lifecycle_content_hash": lifecycle["content_hash"],
            "actions_archive_path": str(ACTIONS_ARCHIVE.relative_to(REPO)),
            "actions_archive_sha256": _sha256(ACTIONS_ARCHIVE),
        },
        "required_next_action": (
            "Prioritize issuer evidence for plain and weekend split rows. Treat merger, listing, "
            "spin-off, and ADR-context rows as lifecycle-semantics candidates, not automatic "
            "ratio repairs."
        ),
        "claim_boundary": (
            "Nearby context is descriptive evidence, not causal proof. No source row is deleted, "
            "no ratio is changed, and no replay or performance claim is authorized."
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
