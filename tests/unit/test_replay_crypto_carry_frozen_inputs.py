from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/replay_crypto_carry_frozen_inputs.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_frozen_replay", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_crypto_carry_artifact_matches_replay_declaration() -> None:
    module = _module()
    source = module.verify_source()
    assert source["config"]["n_legs"] == 25
    assert len(source["config"]["instrument_ids"]) == 58
    assert module.DECLARED["alpha_names"] == ["carry_fund_21"]


def test_first_divergence_reports_signed_replay_delta() -> None:
    module = _module()
    source = pd.Series([100.0, 101.0, 102.0], index=[1, 2, 3])
    replay = pd.Series([100.0, 100.5, 500.0], index=[1, 2, 3])
    assert module._first_divergence(source, replay) == {
        "overlap_row_index": 1,
        "ts": 2,
        "source_equity": 101.0,
        "replay_equity": 100.5,
        "delta_replay_minus_source": -0.5,
    }


def test_verified_receipt_rejects_tampering(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "receipt.json"
    document = {"status": "REPLAY_EXECUTED", "content_hash": ""}
    document["content_hash"] = module._content_hash(document)
    path.write_text(json.dumps(document))
    assert module._verified_receipt(path) == document
    document["status"] = "PASS_EXACT_FROZEN_REPLAY"
    path.write_text(json.dumps(document))
    try:
        module._verified_receipt(path)
    except RuntimeError as exc:
        assert "content hash is invalid" in str(exc)
    else:  # pragma: no cover - assertion spelling is clearer than pytest.raises here
        raise AssertionError("tampered receipt was accepted")
