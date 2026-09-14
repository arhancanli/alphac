#!/usr/bin/env python3
"""Register every hypothesis identity measured after the legacy epoch closed, one row each.

WHY. The legacy epoch is sealed at 228 retired identities with a packet manifest. Everything
measured since is the prospective epoch, and until 2026-09-14 that was exactly one identity
(`crypto_carry_portable_v1`, ordinal 229) with a bespoke public record. The publish pipeline and
the site's trial-accounting tool both encoded "one prospective identity whose ordinal equals
selection N". The 2026-09-14 import brought 118 more prospective identities (ordinals 230 to
347), each reserved through the governed path in a second checkout, measured once, and never
closed. The arithmetic the site checks (legacy + prospective = N) went false and the production
build failed, correctly.

This builder derives the prospective epoch instead of typing it: the union of every ledger,
minus the sealed legacy keys, is the epoch; each identity's reservation (ordinal, family, arm,
timestamps, evidence bindings) is read from the reservation record filed beside its ledger; its
first immutable measurement is read from the ledger; and its status says what evidence exists:
a governed serial packet with a final decision, an imported reservation that was measured but
never closed, or a measurement with no reservation at all (a governance finding, published as
such). The register fails closed when legacy + prospective does not equal the union, when a
key appears in both epochs, or when two identities claim one ordinal.

It reserves nothing, admits nothing and judges nothing. It is the list.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion, hypothesis_hash

REPO = Path(__file__).resolve().parents[1]
OUTPUT_RELATIVE = Path("artifacts/research/prospective_epoch_register.json")
LEGACY_CLOSURE_RELATIVE = Path("artifacts/research/legacy_research_epoch_closure.json")
GOVERNED_CLOSURES_RELATIVE = ("artifacts/research/crypto_carry_portable_v1_admission_closure.json",)
IMPORT_RECEIPT_GLOB = "artifacts/audit/external_ledger_import_*.json"
SCHEMA = "canli.alphac-prospective-epoch-register.v1"
AUTHOR = "Arhan Canli"

STATUS_GOVERNED = "GOVERNED_SERIAL_PACKET_CLOSED"
STATUS_IMPORTED = "IMPORTED_RESERVED_MEASURED_UNCLOSED"
STATUS_RESERVED = "RESERVED_MEASURED_UNCLOSED"
STATUS_UNRESERVED = "MEASURED_WITHOUT_RESERVATION"


def _content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _iso(now_ms: int) -> str:
    return dt.datetime.fromtimestamp(now_ms / 1000, tz=dt.UTC).isoformat()


def _finite(value: float) -> float | None:
    """A degenerate measurement is logged as NaN on the ledger; JSON has no NaN, so publish null.
    The row keeps its place in the union either way (the identity was spent)."""
    return float(value) if value == value and abs(value) != float("inf") else None


def first_records(repo: Path) -> dict[str, tuple[Any, Path]]:
    """First immutable record per hypothesis key across the union, with its ledger path."""
    union = ExperimentUnion.discover(repo / "var" / "experiments.jsonl", repo)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        for record in ExperimentLog(path).all():
            key = hypothesis_hash(record.config)
            current = first.get(key)
            if current is None or (record.now_ms, record.config_hash) < (
                current[0].now_ms,
                current[0].config_hash,
            ):
                first[key] = (record, path)
    return first


def reservations(repo: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """hypothesis key -> earliest reservation record (with its path); plus duplicate notes."""
    found: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    candidates = sorted(
        [
            *repo.glob("artifacts/analysis/**/reservation.json"),
            *repo.glob("artifacts/research/preregistrations/**/return_identity_reservation.json"),
        ]
    )
    for path in candidates:
        if any("archive" in part.casefold() for part in path.relative_to(repo).parts):
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        key = record.get("hypothesis_identity")
        if not isinstance(key, str):
            continue
        entry = {"record": record, "path": path.relative_to(repo)}
        current = found.get(key)
        if current is None or str(record.get("reserved_at", "")) < str(
            current["record"].get("reserved_at", "")
        ):
            if current is not None:
                duplicates.append({"hypothesis_key": key, "path": str(current["path"])})
            found[key] = entry
        else:
            duplicates.append({"hypothesis_key": key, "path": str(entry["path"])})
    return found, duplicates


def imported_directories(repo: Path) -> dict[str, str]:
    """analysis directory name -> import receipt path, for every imported directory."""
    mapping: dict[str, str] = {}
    for receipt_path in sorted(repo.glob(IMPORT_RECEIPT_GLOB)):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("dry_run"):
            continue
        for directory in receipt.get("directories_imported", []):
            mapping[str(directory["name"])] = str(receipt_path.relative_to(repo))
    return mapping


def governed_closures(repo: Path) -> dict[str, dict[str, Any]]:
    """hypothesis key -> governed serial closure (final decision on file)."""
    out: dict[str, dict[str, Any]] = {}
    for relative in GOVERNED_CLOSURES_RELATIVE:
        path = repo / relative
        if not path.exists():
            continue
        closure = json.loads(path.read_text(encoding="utf-8"))
        key = closure.get("identity", {}).get("hypothesis_key")
        if isinstance(key, str):
            out[key] = {"closure": closure, "path": relative}
    return out


def build(repo: Path = REPO, *, now: dt.datetime | None = None) -> dict[str, Any]:
    closure_path = repo / LEGACY_CLOSURE_RELATIVE
    legacy = json.loads(closure_path.read_text(encoding="utf-8"))
    legacy_keys = {str(item["hypothesis_key"]) for item in legacy["identities"]}
    union = first_records(repo)
    prospective_keys = sorted(k for k in union if k not in legacy_keys)
    reserved, duplicate_reservations = reservations(repo)
    imported = imported_directories(repo)
    governed = governed_closures(repo)

    rows: list[dict[str, Any]] = []
    ordinal_owner: dict[int, str] = {}
    for key in prospective_keys:
        record, ledger_path = union[key]
        ledger_relative = ledger_path.relative_to(repo)
        # artifacts/analysis/<study>/... -> the study directory the import receipt names.
        top = (
            ledger_relative.parts[2]
            if len(ledger_relative.parts) > 3
            and ledger_relative.parts[:2] == ("artifacts", "analysis")
            else None
        )
        reservation = reserved.get(key)
        governed_entry = governed.get(key)
        ordinal: int | None = None
        family: str | None = None
        arm: str | None = None
        reserved_at: str | None = None
        return_identity_id: str | None = None
        if reservation is not None:
            rec = reservation["record"]
            ordinal_raw = (rec.get("governance_epoch") or {}).get("reservation_ordinal")
            ordinal = int(ordinal_raw) if isinstance(ordinal_raw, int) else None
            family = rec.get("family_trial_account")
            trial_config = rec.get("trial_config") or {}
            arm = trial_config.get("arm") or trial_config.get("candidate")
            arm = str(arm) if arm is not None else None
            reserved_at = rec.get("reserved_at")
            return_identity_id = rec.get("return_identity_id")
        if governed_entry is not None:
            status = STATUS_GOVERNED
        elif reservation is None:
            status = STATUS_UNRESERVED
        elif top is not None and top in imported:
            status = STATUS_IMPORTED
        else:
            status = STATUS_RESERVED
        if ordinal is not None:
            if ordinal in ordinal_owner and ordinal_owner[ordinal] != key:
                raise ValueError(
                    f"reservation ordinal {ordinal} is claimed by two identities: "
                    f"{ordinal_owner[ordinal]} and {key}"
                )
            ordinal_owner[ordinal] = key
        decision = governed_entry["closure"]["decision"] if governed_entry is not None else None
        rows.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "reservation_ordinal": ordinal,
                "return_identity_id": return_identity_id,
                "family_trial_account": family,
                "arm": arm,
                "status": status,
                "reserved_at": reserved_at,
                "reservation_path": (str(reservation["path"]) if reservation is not None else None),
                "ledger_path": str(ledger_relative),
                "source": (
                    {"kind": "imported", "receipt": imported[top]}
                    if top is not None and top in imported
                    else {"kind": "canonical", "receipt": None}
                ),
                "first_measurement": {
                    "recorded_at": _iso(int(record.now_ms)),
                    "sharpe_ann": _finite(record.sharpe_ann),
                    "sharpe_per_period": _finite(record.sharpe_per_period),
                    "n_obs": int(record.n_obs),
                },
                "packet_complete": bool(governed_entry is not None),
                "closure_path": governed_entry["path"] if governed_entry is not None else None,
                "final_disposition": decision["disposition"] if decision else None,
                "admitted": bool(decision["admitted"]) if decision else False,
            }
        )
    rows.sort(
        key=lambda row: (
            row["reservation_ordinal"] is None,
            row["reservation_ordinal"] or 0,
            row["hypothesis_key"],
        )
    )

    ordinals = sorted(o for o in ordinal_owner)
    gaps: list[int] = []
    if ordinals:
        gaps = [o for o in range(ordinals[0], ordinals[-1] + 1) if o not in ordinal_owner]
    counts = {
        STATUS_GOVERNED: sum(1 for r in rows if r["status"] == STATUS_GOVERNED),
        STATUS_IMPORTED: sum(1 for r in rows if r["status"] == STATUS_IMPORTED),
        STATUS_RESERVED: sum(1 for r in rows if r["status"] == STATUS_RESERVED),
        STATUS_UNRESERVED: sum(1 for r in rows if r["status"] == STATUS_UNRESERVED),
    }
    families: dict[str, int] = {}
    for row in rows:
        families[row["family_trial_account"] or "(no reservation)"] = (
            families.get(row["family_trial_account"] or "(no reservation)", 0) + 1
        )
    legacy_count = int(legacy["summary"]["retired_identities"])
    if legacy_count != len(legacy_keys):
        raise ValueError("legacy closure summary does not match its identity list")
    if legacy_count + len(rows) != len(union):
        raise ValueError(
            f"legacy {legacy_count} + prospective {len(rows)} != union {len(union)}; "
            "a key is in both epochs or missing from one"
        )
    summary = {
        "union_identities": len(union),
        "legacy_retired_identities": legacy_count,
        "observed_identities": len(rows),
        "identity_arithmetic_holds": True,
        "by_status": counts,
        "families": dict(sorted(families.items())),
        "distinct_families": len(families),
        "latest_reservation_ordinal": ordinals[-1] if ordinals else None,
        "first_reservation_ordinal": ordinals[0] if ordinals else None,
        "reservation_ordinals_contiguous": not gaps,
        "reservation_ordinal_gaps": gaps,
        "duplicate_reservation_records": duplicate_reservations,
        "admitted_identities": sum(1 for r in rows if r["admitted"]),
    }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "author": AUTHOR,
        "generated_at": (now or dt.datetime.now(dt.UTC)).isoformat(),
        "claim_boundary": (
            "One row per hypothesis identity measured after the legacy epoch closed, with its "
            "reservation, first immutable measurement and evidence status. Listing an identity "
            "is not admission, validation or a performance claim; an unclosed identity has been "
            "measured and counted against the budget and nothing else. Legacy retired identities "
            "plus these rows equal selection N by construction, or this file is not written."
        ),
        "source_bindings": {
            "legacy_epoch_closure": {
                "path": str(LEGACY_CLOSURE_RELATIVE),
                "content_hash": legacy.get("content_hash"),
            },
            "import_receipts": sorted(set(imported.values())),
        },
        "summary": summary,
        "identities": rows,
    }
    payload["content_hash"] = _content_hash(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--write", type=Path, default=None)
    args = ap.parse_args(argv)
    payload = build(args.root)
    out = args.write or (args.root / OUTPUT_RELATIVE)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    s = payload["summary"]
    print(
        f"prospective epoch: {s['observed_identities']} identities "
        f"(legacy {s['legacy_retired_identities']} + prospective = union "
        f"{s['union_identities']}); by status {s['by_status']}; ordinals "
        f"{s['first_reservation_ordinal']}..{s['latest_reservation_ordinal']} "
        f"contiguous={s['reservation_ordinals_contiguous']}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
