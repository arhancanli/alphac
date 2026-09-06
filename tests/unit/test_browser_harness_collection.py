from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests" / "browser" / "test_active_ownership_review_workspace.py"


def test_browser_harness_import_does_not_require_playwright(monkeypatch) -> None:
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise AssertionError("Playwright must be imported only when the harness executes")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = importlib.util.spec_from_file_location("active_ownership_browser_harness", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)
