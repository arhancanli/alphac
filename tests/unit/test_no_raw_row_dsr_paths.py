"""Repository guard for stale raw-row DSR selection contexts."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config" / "legacy_dsr_exceptions.json"


def _called_attributes(tree: ast.AST) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _called_names(tree: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _raw_row_dsr_paths() -> set[str]:
    paths: set[str] = set()
    for base in (ROOT / "src", ROOT / "scripts"):
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            names = _called_names(tree)
            attributes = _called_attributes(tree)
            uses_raw_context = bool(
                attributes & {"n_trials", "trial_sharpe_variance"}
            )
            uses_aligned_context = {
                "n_hypotheses",
                "hypothesis_sharpe_variance",
            }.issubset(attributes)
            if "dsr_from_returns" in names and uses_raw_context and not uses_aligned_context:
                paths.add(str(path.relative_to(ROOT)))
    return paths


def test_every_raw_row_dsr_path_is_an_explicit_legacy_exception() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    exceptions = set(policy["exceptions"])
    observed = _raw_row_dsr_paths()

    assert observed == exceptions, (
        f"raw-row DSR path policy drift: unlisted={sorted(observed - exceptions)}, "
        f"stale_exceptions={sorted(exceptions - observed)}"
    )
    assert all(path.startswith("scripts/") for path in exceptions)
    assert all((ROOT / path).is_file() for path in exceptions)
    assert not (set(policy.get("resolved_paths", {})) & observed)
    assert policy["status"] == "CODE_RESOLVED_HISTORICAL_CLAIMS_RETIRED"


def test_repaired_historical_screens_preflight_and_register_union_trials() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    registration_paths = set(policy["union_registration_paths"])

    assert registration_paths <= set(policy["resolved_paths"])
    for relative in registration_paths:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        names = _called_names(tree)
        attributes = _called_attributes(tree)
        assert "preflight_hypotheses" in attributes, f"{relative} lacks fail-closed preflight"
        assert "record_probe_trial" in names or "record" in attributes, (
            f"{relative} can measure returns without union registration"
        )
        assert "n_hypotheses" in attributes
        assert "hypothesis_sharpe_variance" in attributes
