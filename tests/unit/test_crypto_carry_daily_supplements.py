from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/fetch_crypto_carry_daily_supplements.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_daily_supplements", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_content_hash_excludes_only_its_own_field() -> None:
    module = _module()
    document = {"schema": "test", "passes": True}
    document["content_hash"] = module._content_hash(document)
    assert document["content_hash"] == module._content_hash(document)
    document["passes"] = False
    assert document["content_hash"] != module._content_hash(document)
