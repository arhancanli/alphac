from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

from alphaforge.validation import trial_reservation
from alphaforge.validation.experiments import config_hash, hypothesis_hash
from alphaforge.validation.history import recover_bound_bytes

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_crypto_carry_portable_v1.py"
CONFIG = ROOT / "config/crypto_carry_portable_v1_run.json"
RESERVATION = ROOT / (
    "artifacts/research/preregistrations/crypto_carry_portable_v1/return_identity_reservation.json"
)
RESULT = ROOT / "artifacts/research/crypto_carry_portable_v1_result.json"
CLOSURE = ROOT / "artifacts/research/crypto_carry_portable_v1_admission_closure.json"
FORWARD_INDEX = ROOT / "artifacts/research/trial_packets/forward_index.json"
SPEC = importlib.util.spec_from_file_location("crypto_portable_v1_run_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_run_config_is_self_hashed_and_uses_the_exact_reserved_identity() -> None:
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert document["content_hash"] == MODULE._content_hash(document)
    trial = document["trial_config"]
    assert config_hash(trial) == document["config_hash"] == "50d9e8b059fee773"
    assert hypothesis_hash(trial) == document["hypothesis_identity"] == "da5f5f47f99f9bd2"
    assert len(trial["instrument_ids"]) == len(set(trial["instrument_ids"])) == 57
    assert "BINANCE:PERP:ICPUSDT" not in trial["instrument_ids"]


def _sealed_bytes(relative: str, sha256_hex: str) -> bytes:
    """The bytes a seal bound at ``relative``: the current file, else the commit that held them.

    uv.lock and configs/base.yaml move on after a seal, so demanding the current bytes fails a
    re-verification forever. The claimed hash comes from inside the sealed record and the bytes
    must exist at that path in this repository's history (validation/history.py).
    """
    current = (ROOT / relative).read_bytes()
    if hashlib.sha256(current).hexdigest() == sha256_hex:
        return current
    found = recover_bound_bytes(ROOT, relative, sha256_hex)
    assert found is not None, f"{relative}: bound bytes {sha256_hex} are in no commit"
    commit, size = found
    blob = subprocess.run(
        ["git", "show", f"{commit}:{relative}"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    assert len(blob) == size
    return blob


def test_the_executed_reservation_is_the_sealed_one_and_its_timeless_checks_hold() -> None:
    """Re-verify the reservation AFTER its run, from what the seal proves.

    validate_reservation is a pre-run gate: it requires the reservation to be the next governed
    identity, true at ordinal 229 and false forever once identity 230 was reserved. The runner's
    execute() refuses to compute returns unless that gate passed, and the sealed result binds this
    reservation byte for byte; so the ordering held at run time. What can still be checked today
    is checked here, against the sealed bytes.
    """
    run_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw = RESERVATION.read_bytes()
    reservation = json.loads(raw)
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))

    for sealed in (result, closure):
        binding = sealed["lineage"]["reservation"]
        assert binding["path"] == RESERVATION.relative_to(ROOT).as_posix()
        assert (binding["bytes"], binding["sha256"]) == (len(raw), hashlib.sha256(raw).hexdigest())
        assert sealed["identity"]["reservation_ordinal"] == 229

    assert reservation["schema"] == trial_reservation.SCHEMA
    assert reservation["status"] == trial_reservation.STATUS
    assert reservation["hypotheses_spent"] == 1
    assert not trial_reservation.FORBIDDEN_OUTCOME_KEYS.intersection(reservation)
    assert reservation["trial_config"] == run_config["trial_config"]
    assert reservation["hypothesis_identity"] == hypothesis_hash(run_config["trial_config"])

    epoch = reservation["governance_epoch"]
    assert epoch["reservation_ordinal"] == 229
    for kind in ("admission_contract", "trial_policy", "promotion_receipt"):
        sealed_bytes = _sealed_bytes(epoch[f"{kind}_path"], epoch[f"{kind}_sha256"])
        assert hashlib.sha256(sealed_bytes).hexdigest() == epoch[f"{kind}_sha256"]
    assert set(reservation["evidence"]) == trial_reservation.REQUIRED_EVIDENCE
    for item in reservation["evidence"].values():
        assert (
            hashlib.sha256(_sealed_bytes(item["path"], item["sha256"])).hexdigest()
            == item["sha256"]
        )

    packets = json.loads(FORWARD_INDEX.read_text(encoding="utf-8"))["packets"]
    logged = [row for row in packets if row["hypothesis_key"] == reservation["hypothesis_identity"]]
    assert [row["config_hash"] for row in logged] == [run_config["config_hash"]]


def test_runner_has_no_top_level_strategy_or_return_engine_import() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {alias.name for node in imports for alias in node.names}
    assert "alphaforge.analytics.walkforward" not in names
    assert "alphaforge.features.engine" not in names
    assert "alphaforge.signals.service" not in names


def test_runner_and_reservation_bind_every_required_evidence_file() -> None:
    run_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    reservation = json.loads(RESERVATION.read_text(encoding="utf-8"))
    for binding in run_config["bindings"].values():
        sealed = _sealed_bytes(binding["path"], binding["sha256"])
        assert hashlib.sha256(sealed).hexdigest() == binding["sha256"]
    assert set(reservation["evidence"]) == {
        "preregistration",
        "input_data_manifest",
        "runner",
        "python_project",
        "locked_environment",
    }
    assert not {
        "sharpe",
        "max_drawdown",
        "returns",
        "result",
        "verdict",
    }.intersection(reservation)
