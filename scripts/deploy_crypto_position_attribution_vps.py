#!/usr/bin/env python3
"""Guarded deployment of prospective crypto position-mark attribution.

The default mode is a read-only remote preflight. ``--apply`` additionally
requires an explicit approval phrase in the environment. The rollout never
runs a paper cycle: after the additive migration it restarts the timer and
waits for the next natural ``:10`` observation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT: Final = (
    ROOT / "artifacts" / "engineering" / "crypto_position_attribution_vps_preflight.json"
)
DEFAULT_OBSERVATION: Final = (
    ROOT
    / "artifacts"
    / "engineering"
    / "crypto_position_attribution_vps_preflight_observation.json"
)
DEFAULT_HOST: Final = "root@201.79.12.40"
DEFAULT_IDENTITY: Final = Path.home() / ".ssh" / "moonshot_vps"
APPROVAL_ENV: Final = "ALPHAC_CRYPTO_ATTRIBUTION_DEPLOY_APPROVAL"
APPROVAL_PHRASE: Final = "AUTHORIZE_HASH_LOCKED_CRYPTO_ATTRIBUTION_DEPLOYMENT"
REMOTE_ROOT: Final = "/opt/alphaforge"
REMOTE_DB: Final = f"{REMOTE_ROOT}/var/trading_crypto_perp.sqlite"
REMOTE_TIMER: Final = "af-trade.timer"
REMOTE_SERVICE: Final = "af-trade.service"
EXPECTED_PATHS: Final = (
    "src/alphaforge/execution/paper.py",
    "src/alphaforge/live/store.py",
    "src/alphaforge/live/loop.py",
)
ATTRIBUTION_SCRIPT: Final = ROOT / "scripts" / "export_crypto_position_attribution.py"
ROLLOUT_VERIFIER_SCRIPT: Final = ROOT / "scripts" / "verify_crypto_position_attribution_rollout.py"
REQUIRED_COLUMNS: Final = (
    "mark_price",
    "mark_source",
    "market_value_quote",
    "unrealized_pnl_quote",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PreflightError(RuntimeError):
    """A fail-closed deployment precondition was not met."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: Mapping[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def load_and_validate_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "canli.alphac-crypto-position-attribution-vps-preflight.v1":
        raise PreflightError("unexpected preflight schema")
    if payload.get("status") != "READY_FOR_AUTHORIZED_DEPLOYMENT":
        raise PreflightError("preflight is not deployment-ready")
    if payload.get("authorization", {}).get("remote_mutations_performed") is not False:
        raise PreflightError("preflight already claims a remote mutation")

    files = payload.get("required_files")
    if not isinstance(files, list) or tuple(item.get("path") for item in files) != EXPECTED_PATHS:
        raise PreflightError("deployment file set is not the exact three-file contract")
    for item in files:
        remote_hash = item.get("remote_sha256")
        desired_hash = item.get("desired_sha256")
        if not isinstance(remote_hash, str) or _SHA256.fullmatch(remote_hash) is None:
            raise PreflightError(f"invalid remote hash for {item['path']}")
        if not isinstance(desired_hash, str) or _SHA256.fullmatch(desired_hash) is None:
            raise PreflightError(f"invalid desired hash for {item['path']}")
        actual = _sha256(ROOT / item["path"])
        if actual != desired_hash:
            raise PreflightError(
                f"local source drift for {item['path']}: expected {desired_hash}, got {actual}"
            )
    return payload


def require_apply_authorization(*, apply: bool, environ: Mapping[str, str]) -> None:
    if apply and environ.get(APPROVAL_ENV) != APPROVAL_PHRASE:
        raise PreflightError(
            f"--apply requires {APPROVAL_ENV}={APPROVAL_PHRASE}; no mutation attempted"
        )


def _ssh_prefix(host: str, identity: Path) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-i",
        str(identity),
        host,
    ]


def _run(
    command: Sequence[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        input=input_text,
        text=True,
        check=True,
        capture_output=True,
    )


def remote_snapshot(*, host: str, identity: Path) -> dict[str, Any]:
    code = f"""
import hashlib, json, pathlib, sqlite3, subprocess
root = pathlib.Path({REMOTE_ROOT!r})
paths = {EXPECTED_PATHS!r}
db = pathlib.Path({REMOTE_DB!r})
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def state(unit):
    result = subprocess.run(['systemctl', 'is-active', unit], text=True, capture_output=True)
    return result.stdout.strip() or 'unknown'
columns = []
latest_equity_cycle_ts = None
if db.is_file():
    con = sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True)
    try:
        columns = [row[1] for row in con.execute('PRAGMA table_info(positions_snapshots)')]
        row = con.execute('SELECT MAX(cycle_ts) FROM equity_curve').fetchone()
        latest_equity_cycle_ts = None if row is None or row[0] is None else int(row[0])
    finally:
        con.close()
print(json.dumps({{
    'files': {{rel: digest(root / rel) for rel in paths}},
    'database_exists': db.is_file(),
    'database_sha256': digest(db),
    'position_snapshot_columns': columns,
    'latest_equity_cycle_ts': latest_equity_cycle_ts,
    'timer_state': state({REMOTE_TIMER!r}),
    'service_state': state({REMOTE_SERVICE!r}),
}}, sort_keys=True))
""".strip()
    # SSH joins trailing arguments through the remote shell; passing source as an
    # argument would make shell quoting part of the evidence path. Standard input
    # keeps the inspection program byte-for-byte intact and read-only.
    result = _run(
        [*_ssh_prefix(host, identity), "python3", "-"],
        input_text=code,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError("remote preflight did not return valid JSON") from exc


def validate_remote_snapshot(
    snapshot: Mapping[str, Any], contract: Mapping[str, Any], *, before_apply: bool
) -> None:
    if snapshot.get("database_exists") is not True:
        raise PreflightError("authoritative crypto trading database is missing")
    if not isinstance(snapshot.get("latest_equity_cycle_ts"), int):
        raise PreflightError("authoritative crypto equity curve has no latest cycle")
    if snapshot.get("timer_state") != "active":
        raise PreflightError(f"trade timer is not active: {snapshot.get('timer_state')}")
    if before_apply and snapshot.get("service_state") != "inactive":
        raise PreflightError(f"trade service is not safely idle: {snapshot.get('service_state')}")
    if not before_apply and snapshot.get("service_state") not in {"active", "inactive"}:
        raise PreflightError(
            f"trade service has invalid post-deployment state: {snapshot.get('service_state')}"
        )

    key = "remote_sha256" if before_apply else "desired_sha256"
    expected = {item["path"]: item[key] for item in contract["required_files"]}
    if snapshot.get("files") != expected:
        raise PreflightError(f"remote source hash mismatch for {key}")

    columns = set(snapshot.get("position_snapshot_columns", []))
    if before_apply and columns.intersection(REQUIRED_COLUMNS):
        raise PreflightError("remote schema is no longer the declared pre-migration schema")
    if not before_apply and not set(REQUIRED_COLUMNS).issubset(columns):
        raise PreflightError("post-deployment schema is missing attribution columns")


def build_preflight_observation(
    *,
    snapshot: Mapping[str, Any],
    contract_path: Path,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Seal a local receipt for a successful, strictly read-only remote preflight."""
    instant = observed_at or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-position-attribution-vps-preflight-observation.v1",
        "author": "Arhan Canli",
        "observed_at_utc": instant.astimezone(UTC).isoformat(),
        "status": "PASS_READ_ONLY_PREFLIGHT_DEPLOYMENT_NOT_AUTHORIZED",
        "passes_read_only_preflight": True,
        "remote_query_performed": True,
        "remote_mutations_performed": False,
        "deployment_authorized": False,
        "forced_cycle_run": False,
        "authority": "FRANKFURT_CRYPTO_PAPER_HOST_SOLE_REMOTE_WRITER",
        "remote_snapshot": dict(snapshot),
        "source_bindings": {
            "deployment_tool_sha256": _sha256(Path(__file__).resolve()),
            "preflight_contract_path": str(contract_path.relative_to(ROOT)),
            "preflight_contract_sha256": _sha256(contract_path),
        },
        "claim_boundary": (
            "This receipt proves only a successful read-only preflight at the stated instant. "
            "It does not claim deployment, schema migration, position-attribution completeness, "
            "a natural marked cycle, mature forward evidence, or real-capital trading."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def write_preflight_observation(
    *, snapshot: Mapping[str, Any], contract_path: Path, output: Path
) -> Path:
    document = build_preflight_observation(snapshot=snapshot, contract_path=contract_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _remote_apply_script(contract: Mapping[str, Any], stamp: str) -> str:
    files = contract["required_files"]
    stage = f"{REMOTE_ROOT}/var/deploy_staging/crypto-position-attribution/{stamp}"
    backup = f"{REMOTE_ROOT}/var/deploy_backups/crypto-position-attribution/{stamp}"
    live_checks = "\n".join(
        f"require_hash {shlex.quote(REMOTE_ROOT + '/' + item['path'])} {item['remote_sha256']}"
        for item in files
    )
    stage_checks = "\n".join(
        "require_hash "
        f"{shlex.quote(stage + '/' + Path(item['path']).name)} "
        f"{item['desired_sha256']}"
        for item in files
    )
    backup_commands = "\n".join(
        f"mkdir -p {shlex.quote(backup + '/' + str(Path(item['path']).parent))}\n"
        f"cp -p {shlex.quote(REMOTE_ROOT + '/' + item['path'])} "
        f"{shlex.quote(backup + '/' + item['path'])}"
        for item in files
    )
    install_commands = "\n".join(
        f"cp -p {shlex.quote(stage + '/' + Path(item['path']).name)} "
        f"{shlex.quote(REMOTE_ROOT + '/' + item['path'] + '.new')}\n"
        f"mv {shlex.quote(REMOTE_ROOT + '/' + item['path'] + '.new')} "
        f"{shlex.quote(REMOTE_ROOT + '/' + item['path'])}"
        for item in files
    )
    restore_commands = "\n".join(
        f"if [ -f {shlex.quote(backup + '/' + item['path'])} ]; then\n"
        f"  cp -p {shlex.quote(backup + '/' + item['path'])} "
        f"{shlex.quote(REMOTE_ROOT + '/' + item['path'] + '.rollback')}\n"
        f"  mv {shlex.quote(REMOTE_ROOT + '/' + item['path'] + '.rollback')} "
        f"{shlex.quote(REMOTE_ROOT + '/' + item['path'])}\n"
        "fi"
        for item in files
    )
    desired_checks = "\n".join(
        f"require_hash {shlex.quote(REMOTE_ROOT + '/' + item['path'])} {item['desired_sha256']}"
        for item in files
    )
    required_columns = repr(REQUIRED_COLUMNS)
    return f"""#!/bin/bash
set -Eeuo pipefail
ROOT={shlex.quote(REMOTE_ROOT)}
DB={shlex.quote(REMOTE_DB)}
TIMER={shlex.quote(REMOTE_TIMER)}
SERVICE={shlex.quote(REMOTE_SERVICE)}
STAGE={shlex.quote(stage)}
BACKUP={shlex.quote(backup)}
BACKUP_READY=0
require_hash() {{
  actual=$(sha256sum "$1" | awk '{{print $1}}')
  [ "$actual" = "$2" ] || {{ echo "hash mismatch: $1" >&2; return 1; }}
}}
rollback() {{
  rc=$?
  trap - ERR INT TERM
  set +e
  if [ "$BACKUP_READY" = 1 ]; then
    {restore_commands}
    if [ -f "$BACKUP/trading_crypto_perp.sqlite" ]; then
      python3 - "$BACKUP/trading_crypto_perp.sqlite" "$DB" <<'PYRESTORE'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PYRESTORE
    fi
  fi
  systemctl start "$TIMER"
  exit "$rc"
}}
trap rollback ERR INT TERM
{live_checks}
{stage_checks}
systemctl stop "$TIMER"
[ "$(systemctl is-active "$SERVICE" 2>/dev/null || true)" != active ] || {{
  echo "trade service active; refusing deployment" >&2
  false
}}
mkdir -p "$BACKUP"
{backup_commands}
python3 - "$DB" "$BACKUP/trading_crypto_perp.sqlite" <<'PYBACKUP'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PYBACKUP
sha256sum "$BACKUP/trading_crypto_perp.sqlite" > "$BACKUP/SHA256SUMS"
find "$BACKUP/src" -type f -print0 | sort -z | xargs -0 sha256sum >> "$BACKUP/SHA256SUMS"
BACKUP_READY=1
{install_commands}
{desired_checks}
cd "$ROOT"
./.venv/bin/python - "$DB" <<'PYMIGRATE'
import sys
from pathlib import Path
from alphaforge.live.store import TradingStore
with TradingStore(Path(sys.argv[1])):
    pass
PYMIGRATE
python3 - "$DB" <<'PYSCHEMA'
import sqlite3, sys
required = set({required_columns})
con = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)
try:
    columns = {{row[1] for row in con.execute('PRAGMA table_info(positions_snapshots)')}}
finally:
    con.close()
missing = sorted(required - columns)
if missing:
    raise SystemExit('missing attribution columns: ' + ','.join(missing))
PYSCHEMA
systemctl start "$TIMER"
[ "$(systemctl is-active "$TIMER")" = active ]
trap - ERR INT TERM
echo DEPLOYMENT_APPLIED_WAITING_FOR_NATURAL_CYCLE
"""


def apply_deployment(*, host: str, identity: Path, contract: Mapping[str, Any], stamp: str) -> None:
    stage = f"{REMOTE_ROOT}/var/deploy_staging/crypto-position-attribution/{stamp}"
    _run([*_ssh_prefix(host, identity), "install", "-d", "-m", "700", stage])
    for item in contract["required_files"]:
        _run(
            [
                "scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-i",
                str(identity),
                str(ROOT / item["path"]),
                f"{host}:{stage}/{Path(item['path']).name}",
            ]
        )
    script = _remote_apply_script(contract, stamp)
    _run([*_ssh_prefix(host, identity), "bash", "-s"], input_text=script)


def _remote_rollback_script(contract: Mapping[str, Any], stamp: str) -> str:
    """Restore exact pre-rollout sources and SQLite after client-side validation fails."""
    backup = f"{REMOTE_ROOT}/var/deploy_backups/crypto-position-attribution/{stamp}"
    restore_commands = "\n".join(
        f"require_hash {shlex.quote(backup + '/' + item['path'])} {item['remote_sha256']}\n"
        f"cp -p {shlex.quote(backup + '/' + item['path'])} "
        f"{shlex.quote(REMOTE_ROOT + '/' + item['path'] + '.rollback')}\n"
        f"mv {shlex.quote(REMOTE_ROOT + '/' + item['path'] + '.rollback')} "
        f"{shlex.quote(REMOTE_ROOT + '/' + item['path'])}"
        for item in contract["required_files"]
    )
    restored_checks = "\n".join(
        f"require_hash {shlex.quote(REMOTE_ROOT + '/' + item['path'])} {item['remote_sha256']}"
        for item in contract["required_files"]
    )
    return f"""#!/bin/bash
set -Eeuo pipefail
DB={shlex.quote(REMOTE_DB)}
TIMER={shlex.quote(REMOTE_TIMER)}
SERVICE={shlex.quote(REMOTE_SERVICE)}
BACKUP={shlex.quote(backup)}
require_hash() {{
  actual=$(sha256sum "$1" | awk '{{print $1}}')
  [ "$actual" = "$2" ] || {{ echo "hash mismatch: $1" >&2; return 1; }}
}}
systemctl stop "$TIMER"
systemctl stop "$SERVICE"
[ -f "$BACKUP/trading_crypto_perp.sqlite" ]
{restore_commands}
python3 - "$BACKUP/trading_crypto_perp.sqlite" "$DB" <<'PYRESTORE'
import sqlite3, sys
source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
    result = target.execute('PRAGMA integrity_check').fetchone()
    if result is None or result[0] != 'ok':
        raise RuntimeError('restored database integrity check failed')
finally:
    target.close()
    source.close()
PYRESTORE
{restored_checks}
systemctl start "$TIMER"
[ "$(systemctl is-active "$TIMER")" = active ]
echo DEPLOYMENT_ROLLED_BACK_AFTER_POST_VALIDATION_FAILURE
"""


def rollback_deployment(
    *, host: str, identity: Path, contract: Mapping[str, Any], stamp: str
) -> None:
    script = _remote_rollback_script(contract, stamp)
    _run([*_ssh_prefix(host, identity), "bash", "-s"], input_text=script)


def apply_and_validate(
    *,
    host: str,
    identity: Path,
    contract: Mapping[str, Any],
    before: Mapping[str, Any],
    stamp: str,
) -> dict[str, Any]:
    """Apply once and guarantee rollback if the independent postflight does not pass."""
    apply_deployment(host=host, identity=identity, contract=contract, stamp=stamp)
    try:
        after = remote_snapshot(host=host, identity=identity)
        validate_remote_snapshot(after, contract, before_apply=False)
        return after
    except Exception as exc:
        try:
            rollback_deployment(host=host, identity=identity, contract=contract, stamp=stamp)
            restored = remote_snapshot(host=host, identity=identity)
            validate_remote_snapshot(restored, contract, before_apply=True)
        except Exception as rollback_exc:
            raise PreflightError(
                "post-deployment validation failed and automatic rollback could not be proven"
            ) from rollback_exc
        raise PreflightError(
            "post-deployment validation failed; exact pre-rollout state was restored"
        ) from exc


def build_receipt(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    stamp: str,
    contract_path: Path,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "canli.alphac-crypto-position-attribution-vps-receipt.v1",
        "author": "Arhan Canli",
        "deployed_at_utc": stamp,
        "status": "DEPLOYED_WAITING_FOR_FIRST_NATURAL_MARKED_CYCLE",
        "forced_cycle_run": False,
        "before": dict(before),
        "after": dict(after),
        "source_bindings": {
            "deployment_tool_sha256": _sha256(Path(__file__).resolve()),
            "preflight_contract_sha256": _sha256(contract_path),
            "attribution_evaluator_sha256": _sha256(ATTRIBUTION_SCRIPT),
            "rollout_verifier_sha256": _sha256(ROLLOUT_VERIFIER_SCRIPT),
        },
        "claim_boundary": (
            "Deployment and migration are verified; attribution remains incomplete until the "
            "next natural cycle reconciles exact position marks to account equity."
        ),
    }
    document["content_hash"] = _content_hash(document)
    return document


def write_receipt(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    stamp: str,
    contract_path: Path,
) -> Path:
    output = ROOT / "artifacts" / "engineering" / "crypto_position_attribution_vps_receipt.json"
    payload = build_receipt(
        before=before,
        after=after,
        stamp=stamp,
        contract_path=contract_path,
    )
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Perform the guarded rollout.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observation-output", type=Path, default=DEFAULT_OBSERVATION)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    contract = load_and_validate_contract(args.contract)
    require_apply_authorization(apply=args.apply, environ=os.environ)
    before = remote_snapshot(host=args.host, identity=args.identity)
    validate_remote_snapshot(before, contract, before_apply=True)
    observation = write_preflight_observation(
        snapshot=before,
        contract_path=args.contract,
        output=args.observation_output,
    )
    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": "READ_ONLY_PREFLIGHT",
                    "remote": before,
                    "observation": str(observation),
                },
                indent=2,
            )
        )
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    after = apply_and_validate(
        host=args.host,
        identity=args.identity,
        contract=contract,
        before=before,
        stamp=stamp,
    )
    receipt = write_receipt(
        before=before,
        after=after,
        stamp=stamp,
        contract_path=args.contract,
    )
    print(f"deployed; waiting for next natural cycle; receipt={receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
