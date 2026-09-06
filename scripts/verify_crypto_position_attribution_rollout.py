#!/usr/bin/env python3
"""Verify the first non-empty natural crypto cycle after attribution rollout.

The verifier is read-only on Frankfurt. It binds the deployment receipt, reads
one transactionally consistent latest-cycle snapshot, reuses the canonical
attribution evaluator, and emits a content-hashed engineering receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT: Final = ROOT / "scripts" / "deploy_crypto_position_attribution_vps.py"
ATTRIBUTION_SCRIPT: Final = ROOT / "scripts" / "export_crypto_position_attribution.py"
CONTRACT_PATH: Final = (
    ROOT / "artifacts" / "engineering" / "crypto_position_attribution_vps_preflight.json"
)
RECEIPT_PATH: Final = (
    ROOT / "artifacts" / "engineering" / "crypto_position_attribution_vps_receipt.json"
)
OUTPUT_PATH: Final = (
    ROOT / "artifacts" / "engineering" / "crypto_position_attribution_rollout_verification.json"
)
SCHEMA: Final = "canli.alphac-crypto-position-attribution-rollout-verification.v1"


class VerificationError(RuntimeError):
    """Deployment or natural-cycle evidence is malformed or contradictory."""


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise VerificationError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def no_deployment_receipt_document() -> dict[str, Any]:
    document = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "status": "NO_DEPLOYMENT_RECEIPT",
        "passes": False,
        "remote_query_performed": False,
        "deployment_boundary_cycle_ts": None,
        "natural_cycle_after_deployment": False,
        "attribution": None,
        "source_binding": None,
        "claim_boundary": (
            "No deployment is claimed and Frankfurt was not queried. Natural-cycle verification "
            "cannot begin until a valid hash-bound deployment receipt exists."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def is_frozen_success(
    document: dict[str, Any], *, receipt_sha256: str, contract: dict[str, Any]
) -> bool:
    """A frozen success is terminal for the FIRST-NATURAL-CYCLE claim -- but only while it still
    describes the currently declared desired source state. If the contract's required_files
    desired_sha256 values move (a legitimate re-pin, e.g. desired_revisions), the frozen document
    no longer proves anything about what is deployed NOW, so it must not shortcut a fresh remote
    re-check.
    """
    binding = document.get("source_binding") or {}
    current_required = {item["path"]: item["desired_sha256"] for item in contract["required_files"]}
    return (
        document.get("schema") == SCHEMA
        and document.get("status") == "VERIFIED_FIRST_NATURAL_MARKED_CYCLE"
        and document.get("passes") is True
        and binding.get("deployment_receipt_sha256") == receipt_sha256
        and binding.get("contract_required_files_desired_sha256") == current_required
        and document.get("content_hash") == _content_hash(document)
    )


def write_if_changed(path: Path, document: dict[str, Any]) -> None:
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _binding_revisions(contract: dict[str, Any]) -> list[dict[str, Any]]:
    revisions = contract.get("binding_revisions")
    if not isinstance(revisions, list):
        return []
    return [entry for entry in revisions if isinstance(entry, dict)]


def _entry_date(entry: dict[str, Any]) -> Any:
    raw = entry.get("date")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _check_source_binding(
    key: str,
    sealed_value: Any,
    current_value: str,
    *,
    revisions: list[dict[str, Any]],
    sealed_at: Any,
) -> None:
    """Fail-closed per-key check: the receipt's sealed hash for one binding must be either the
    CURRENT file hash, or a value some binding_revisions entry itself records as the predecessor
    it superseded -- and that entry must postdate the receipt. A legitimate re-pin of the contract
    or the verifier moves the CURRENT hash away from what an old receipt sealed; without this a
    fixed historical receipt could never validate again after the first such re-pin (the same
    gate-nobody-can-pass class as the preflight observation's contract binding), but a value
    recorded nowhere -- an unreviewed drift -- must still be rejected.
    """
    if sealed_value == current_value:
        return
    matches = [e for e in revisions if e.get("preceding_bindings", {}).get(key) == sealed_value]
    if not matches:
        raise VerificationError(
            f"deployment receipt source binding {key}={sealed_value!r} matches neither the "
            f"current file ({current_value!r}) nor any recorded preceding_bindings entry"
        )
    postdating = [e for e in matches if (d := _entry_date(e)) is not None and d > sealed_at]
    if not postdating:
        raise VerificationError(
            f"binding_revisions entry recording {key}={sealed_value!r} as a predecessor does not "
            f"postdate the receipt sealed at {sealed_at.isoformat()}"
        )


def _desired_revisions(contract: dict[str, Any]) -> list[dict[str, Any]]:
    revisions = contract.get("desired_revisions")
    if not isinstance(revisions, list):
        return []
    return [entry for entry in revisions if isinstance(entry, dict)]


def _check_required_file(
    path: str,
    sealed_value: Any,
    current_desired: str,
    *,
    revisions: list[dict[str, Any]],
    sealed_at: Any,
) -> None:
    """Same fail-closed shape as _check_source_binding, scoped to one required_files path.

    The 2026-08-25 receipt's after-migration hash for a file is a snapshot of what THAT rollout
    deployed. required_files[].desired_sha256 has since moved for unrelated reasons (the
    drawdown-ladder and overlay_scale fixes recorded in desired_revisions), so the receipt's
    after-hash must be accepted if it is either the CURRENT desired_sha256 or a value some
    desired_revisions entry for this exact path records as the state it moved FROM -- postdating
    the receipt. A hash explained by neither still fails closed.
    """
    if sealed_value == current_desired:
        return
    matches = [
        e for e in revisions if e.get("path") == path and e.get("from_sha256") == sealed_value
    ]
    if not matches:
        raise VerificationError(
            f"deployment receipt after-hash for {path}={sealed_value!r} matches neither the "
            f"current desired_sha256 ({current_desired!r}) nor any recorded desired_revisions "
            "from_sha256 for this path"
        )
    postdating = [e for e in matches if (d := _entry_date(e)) is not None and d > sealed_at]
    if not postdating:
        raise VerificationError(
            f"desired_revisions entry recording {path} from_sha256={sealed_value!r} does not "
            f"postdate the receipt sealed at {sealed_at.isoformat()}"
        )


def validate_receipt(receipt: dict[str, Any], contract: dict[str, Any], deploy: ModuleType) -> int:
    if receipt.get("schema") != "canli.alphac-crypto-position-attribution-vps-receipt.v1":
        raise VerificationError("missing or unexpected deployment receipt schema")
    if receipt.get("status") != "DEPLOYED_WAITING_FOR_FIRST_NATURAL_MARKED_CYCLE":
        raise VerificationError("deployment receipt is not awaiting natural-cycle verification")
    if receipt.get("forced_cycle_run") is not False:
        raise VerificationError("deployment receipt does not preserve the natural-cycle boundary")
    if receipt.get("content_hash") != deploy._content_hash(receipt):
        raise VerificationError("deployment receipt content hash is invalid")

    try:
        sealed_at = (
            datetime.strptime(receipt["deployed_at_utc"], "%Y%m%dT%H%M%SZ")
            .replace(tzinfo=UTC)
            .date()
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(
            "deployment receipt has no valid deployed_at_utc timestamp"
        ) from exc

    current_bindings = {
        "deployment_tool_sha256": deploy._sha256(Path(deploy.__file__).resolve()),
        "preflight_contract_sha256": deploy._sha256(CONTRACT_PATH),
        "attribution_evaluator_sha256": deploy._sha256(ATTRIBUTION_SCRIPT),
        "rollout_verifier_sha256": deploy._sha256(Path(__file__).resolve()),
    }
    sealed_bindings = receipt.get("source_bindings") or {}
    revisions = _binding_revisions(contract)
    for key, current_value in current_bindings.items():
        _check_source_binding(
            key, sealed_bindings.get(key), current_value, revisions=revisions, sealed_at=sealed_at
        )

    after = receipt.get("after", {})
    after_files = after.get("files") if isinstance(after.get("files"), dict) else {}
    required_paths = {item["path"] for item in contract["required_files"]}
    if set(after_files) != required_paths:
        raise VerificationError(
            "deployment receipt after-snapshot does not cover exactly the contract's "
            "required_files paths"
        )
    file_revisions = _desired_revisions(contract)
    for item in contract["required_files"]:
        _check_required_file(
            item["path"],
            after_files.get(item["path"]),
            item["desired_sha256"],
            revisions=file_revisions,
            sealed_at=sealed_at,
        )
    if not set(deploy.REQUIRED_COLUMNS).issubset(after.get("position_snapshot_columns", [])):
        raise VerificationError("deployment receipt does not prove the additive schema migration")

    baseline = receipt.get("before", {}).get("latest_equity_cycle_ts")
    if not isinstance(baseline, int):
        raise VerificationError("deployment receipt lacks the pre-rollout cycle boundary")
    return baseline


def remote_latest_cycle(*, host: str, identity: Path, deploy: ModuleType) -> dict[str, Any]:
    required_columns = tuple(sorted(deploy.REQUIRED_COLUMNS))
    code = f"""
import hashlib, json, pathlib, sqlite3, subprocess
db = {deploy.REMOTE_DB!r}
root = pathlib.Path({deploy.REMOTE_ROOT!r})
required_paths = {deploy.EXPECTED_PATHS!r}
required = set({required_columns!r})
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def state(unit):
    result = subprocess.run(['systemctl', 'is-active', unit], text=True, capture_output=True)
    return result.stdout.strip() or 'unknown'
files = {{rel: digest(root / rel) for rel in required_paths}}
con = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row
try:
    con.execute('BEGIN')
    columns = [row['name'] for row in con.execute('PRAGMA table_info(positions_snapshots)')]
    equity_row = con.execute(
        'SELECT cycle_ts, equity_quote, cash_quote, n_pos, ts FROM equity_curve '
        'ORDER BY cycle_ts DESC LIMIT 1'
    ).fetchone()
    equity = None if equity_row is None else dict(equity_row)
    positions = []
    if equity is not None and required.issubset(columns):
        positions = [dict(row) for row in con.execute(
            'SELECT cycle_ts, instrument_id, qty, avg_entry_price, opened_ts, mark_price, '
            'mark_source, market_value_quote, unrealized_pnl_quote '
            'FROM positions_snapshots WHERE cycle_ts = ? ORDER BY instrument_id',
            (equity['cycle_ts'],),
        )]
finally:
    con.close()
print(json.dumps({{
    'timer_state': state({deploy.REMOTE_TIMER!r}),
    'service_state': state({deploy.REMOTE_SERVICE!r}),
    'position_snapshot_columns': columns,
    'equity': equity,
    'positions': positions,
    'files': files,
}}, sort_keys=True))
""".strip()
    result = deploy._run(
        [*deploy._ssh_prefix(host, identity), "python3", "-"],
        input_text=code,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("remote cycle inspection did not return valid JSON") from exc


def evaluate_payload(payload: dict[str, Any], attribution: ModuleType) -> dict[str, Any]:
    columns = set(payload.get("position_snapshot_columns", []))
    missing = sorted(attribution.REQUIRED_COLUMNS - columns)
    if missing:
        return {
            "status": "SCHEMA_NOT_YET_MIGRATED",
            "passes": False,
            "missing_columns": missing,
            "latest_cycle": None,
            "positions": [],
        }
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE equity_curve (cycle_ts INTEGER PRIMARY KEY, equity_quote REAL NOT NULL, "
            "cash_quote REAL NOT NULL, n_pos INTEGER NOT NULL, ts INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE positions_snapshots (cycle_ts INTEGER NOT NULL, "
            "instrument_id TEXT NOT NULL, qty REAL NOT NULL, avg_entry_price REAL NOT NULL, "
            "opened_ts INTEGER NOT NULL, mark_price REAL, mark_source TEXT, "
            "market_value_quote REAL, unrealized_pnl_quote REAL, "
            "PRIMARY KEY (cycle_ts, instrument_id)) WITHOUT ROWID"
        )
        equity = payload.get("equity")
        if equity is not None:
            connection.execute(
                "INSERT INTO equity_curve VALUES (?, ?, ?, ?, ?)",
                (
                    equity["cycle_ts"],
                    equity["equity_quote"],
                    equity["cash_quote"],
                    equity["n_pos"],
                    equity["ts"],
                ),
            )
        connection.executemany(
            "INSERT INTO positions_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row["cycle_ts"],
                    row["instrument_id"],
                    row["qty"],
                    row["avg_entry_price"],
                    row["opened_ts"],
                    row["mark_price"],
                    row["mark_source"],
                    row["market_value_quote"],
                    row["unrealized_pnl_quote"],
                )
                for row in payload.get("positions", [])
            ],
        )
        return attribution.evaluate(connection)
    finally:
        connection.close()


def build_document(
    *,
    receipt: dict[str, Any],
    contract: dict[str, Any],
    payload: dict[str, Any],
    receipt_sha256: str,
    deploy: ModuleType,
    attribution: ModuleType,
) -> dict[str, Any]:
    baseline = validate_receipt(receipt, contract, deploy)
    result = evaluate_payload(payload, attribution)
    cycle = result.get("latest_cycle") or {}
    cycle_ts = cycle.get("cycle_ts")
    natural_cycle_after_deployment = isinstance(cycle_ts, int) and cycle_ts > baseline
    remote_idle = payload.get("service_state") == "inactive"
    timer_active = payload.get("timer_state") == "active"

    if not remote_idle:
        status = "REMOTE_SERVICE_NOT_IDLE"
    elif not timer_active:
        status = "REMOTE_TIMER_NOT_ACTIVE"
    elif not natural_cycle_after_deployment:
        status = "WAITING_FOR_FIRST_NATURAL_CYCLE"
    elif result.get("status") != "COMPLETE" or result.get("passes") is not True:
        status = f"ATTRIBUTION_{result.get('status', 'INVALID')}"
    else:
        status = "VERIFIED_FIRST_NATURAL_MARKED_CYCLE"

    current_required_sha256 = {
        item["path"]: item["desired_sha256"] for item in contract["required_files"]
    }
    document = {
        "schema": SCHEMA,
        "author": "Arhan Canli",
        "status": status,
        "passes": status == "VERIFIED_FIRST_NATURAL_MARKED_CYCLE",
        "remote_query_performed": True,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "deployment_boundary_cycle_ts": baseline,
        "natural_cycle_after_deployment": natural_cycle_after_deployment,
        "remote_timer_active": timer_active,
        "remote_service_idle": remote_idle,
        "attribution": result,
        "source_binding": {
            "deployment_receipt_sha256": receipt_sha256,
            "remote_query_payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
            "remote_source_files": payload.get("files"),
            "contract_required_files_desired_sha256": current_required_sha256,
            "scope": "one transactionally consistent latest equity row and same-cycle positions",
        },
        "claim_boundary": (
            "This verifies only prospective position-attribution operation on the first eligible "
            "natural cycle. It is not a Sharpe estimate, return trial, or trading authorization. "
            "remote_source_files proves only that these three paths hashed to these values on "
            "Frankfurt AT verified_at_utc; it does not itself claim signal, weight, or risk-limit "
            "equivalence -- that is the change_scope declaration in the preflight contract."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def parse_args() -> argparse.Namespace:
    deploy = _load_module("crypto_attribution_deploy_cli", DEPLOY_SCRIPT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=deploy.DEFAULT_HOST)
    parser.add_argument("--identity", type=Path, default=deploy.DEFAULT_IDENTITY)
    parser.add_argument("--receipt", type=Path, default=RECEIPT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.receipt.is_file():
        document = no_deployment_receipt_document()
        write_if_changed(args.output, document)
        print(f"{document['status']}: {args.output} (Frankfurt not queried)")
        return 0
    deploy = _load_module("crypto_attribution_deploy", DEPLOY_SCRIPT)
    attribution = _load_module("crypto_attribution_export", ATTRIBUTION_SCRIPT)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    receipt_bytes = args.receipt.read_bytes()
    receipt = json.loads(receipt_bytes)
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if args.output.is_file():
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        if is_frozen_success(existing, receipt_sha256=receipt_sha256, contract=contract):
            print(f"{existing['status']}: {args.output} (frozen first-cycle evidence)")
            return 0
    payload = remote_latest_cycle(host=args.host, identity=args.identity, deploy=deploy)
    document = build_document(
        receipt=receipt,
        contract=contract,
        payload=payload,
        receipt_sha256=receipt_sha256,
        deploy=deploy,
        attribution=attribution,
    )
    write_if_changed(args.output, document)
    print(f"{document['status']}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
