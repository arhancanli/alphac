from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "seal_crypto_carry_portable_lake_readiness.py"
)
SPEC = importlib.util.spec_from_file_location("crypto_portable_lake_readiness_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LakeReadinessError = MODULE.LakeReadinessError


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    document["content_hash"] = "sha256:" + hashlib.sha256(_canonical(body)).hexdigest()
    return document


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "portable"
    leaf = root / "lake/ohlcv/instrument_id=BINANCE:PERP:TESTUSDT/year=2022/data.parquet"
    leaf.parent.mkdir(parents=True)
    leaf.write_bytes(b"leaf")
    ops = root / "ops.sqlite"
    ops.write_bytes(b"ops")
    leaves = [
        {
            "path": str(leaf.relative_to(root)),
            "bytes": leaf.stat().st_size,
            "sha256": hashlib.sha256(leaf.read_bytes()).hexdigest(),
        }
    ]
    manifest = _seal(
        {
            "schema": "canli.alphac-crypto-carry-portable-lake.v1",
            "status": "PASS_ISOLATED_PORTABLE_LAKE_BUILT_ZERO_RETURN",
            "output_inventory": {
                "leaves": leaves,
                "ops_sqlite_sha256": hashlib.sha256(ops.read_bytes()).hexdigest(),
            },
        }
    )
    (root / "portable_lake_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def test_private_root_validation_rehashes_every_leaf_and_metadata_store(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    result = MODULE._validate_private_root(root)
    assert result["status"] == "PASS_ISOLATED_PORTABLE_LAKE_BUILT_ZERO_RETURN"


def test_private_root_validation_rejects_return_artifacts(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    (root / "equity.parquet").write_bytes(b"forbidden")
    with pytest.raises(LakeReadinessError, match="return artifacts"):
        MODULE._validate_private_root(root)


def test_private_root_validation_rejects_leaf_tampering(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    leaf = next((root / "lake").rglob("data.parquet"))
    leaf.write_bytes(b"tampered")
    with pytest.raises(LakeReadinessError, match="leaf inventory drifted"):
        MODULE._validate_private_root(root)


def test_published_receipt_is_self_hashed_and_return_blocked() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "artifacts/audit/crypto_carry_portable_lake_readiness.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["content_hash"] == MODULE._content_hash(document)
    assert document["status"].endswith("READY_TO_PREREGISTER_RETURN_BLOCKED")
    assert document["research_accounting"]["new_return_trials_executed"] == 0
    assert document["production_interface_readback"]["strategy_or_return_engine_invoked"] is False
