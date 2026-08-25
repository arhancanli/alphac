from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

from alphaforge.validation.experiments import config_hash, hypothesis_hash
from alphaforge.validation.trial_reservation import validate_reservation

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_crypto_carry_portable_v1.py"
CONFIG = ROOT / "config/crypto_carry_portable_v1_run.json"
RESERVATION = ROOT / (
    "artifacts/research/preregistrations/crypto_carry_portable_v1/"
    "return_identity_reservation.json"
)
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


def test_reservation_validates_against_the_nested_exact_trial_config() -> None:
    run_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    reservation = json.loads(RESERVATION.read_text(encoding="utf-8"))
    result = validate_reservation(reservation, trial_config=run_config["trial_config"], repo=ROOT)
    assert result["status"] == "VALIDATED_BEFORE_RETURN_COMPUTE"
    assert result["governance_epoch"]["reservation_ordinal"] == 229
    assert result["governance_epoch"]["hypothesis_identity_budget"] == 400
    assert result["forward_epoch_seriality"]["forward_identities_already_logged"] == 0


def test_runner_has_no_top_level_strategy_or_return_engine_import() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    names = {
        alias.name
        for node in imports
        for alias in node.names
    }
    assert "alphaforge.analytics.walkforward" not in names
    assert "alphaforge.features.engine" not in names
    assert "alphaforge.signals.service" not in names


def test_runner_and_reservation_bind_every_required_evidence_file() -> None:
    run_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    reservation = json.loads(RESERVATION.read_text(encoding="utf-8"))
    for binding in run_config["bindings"].values():
        path = ROOT / binding["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]
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
