from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_split_exception_issuer_resolution.py"


def _module():
    spec = importlib.util.spec_from_file_location("split_exception_issuer_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_source_requires_every_issuer_anchor() -> None:
    verify = _module().verify_source
    verify("The NET 1 FOR 200 REVERSE-SPLIT was effective as of April 27, 2021.", [
        "net 1 for 200 reverse-split",
        "effective as of April 27, 2021",
    ])
    with pytest.raises(ValueError, match="missing required fragments"):
        verify("net 1 for 200 reverse-split", ["effective as of April 27, 2021"])
