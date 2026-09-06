from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "seal_operating_margin_exposed_split_resolution.py"


def _module():
    spec = importlib.util.spec_from_file_location("exposed_split_resolution_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_issuer_source_verification_requires_every_anchor() -> None:
    verify = _module().verify_source
    verify(
        "A 1-for-20 reverse stock split will commence trading on a split-adjusted basis.",
        ["1-for-20 reverse stock split", "commence trading on a split-adjusted basis"],
    )
    with pytest.raises(ValueError, match="missing required fragments"):
        verify("1-for-20 reverse stock split", ["commence trading on a split-adjusted basis"])
