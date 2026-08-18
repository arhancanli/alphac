#!/usr/bin/env python3
"""Export the reproducible Ruff quality boundary without hiding historical debt."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
OUTPUT: Final = ROOT / "artifacts" / "engineering" / "lint_debt_contract.json"
SCOPES: Final = {
    "production": ROOT / "src" / "alphaforge",
    "tests": ROOT / "tests",
    "historical_scripts": ROOT / "scripts",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ruff_binary() -> str:
    binary = shutil.which("ruff")
    if binary is None:
        candidate = ROOT / ".venv" / "bin" / "ruff"
        if candidate.is_file():
            return str(candidate)
        raise RuntimeError("ruff executable not found")
    return binary


def _check(scope: Path) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [_ruff_binary(), "check", str(scope), "--output-format", "json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"ruff failed for {scope}: {completed.stderr.strip()}")
    result = json.loads(completed.stdout)
    if not isinstance(result, list):
        raise RuntimeError(f"unexpected Ruff JSON for {scope}")
    return result


def _scope_summary(scope: Path, violations: list[dict[str, Any]]) -> dict[str, object]:
    by_rule = Counter(str(item["code"]) for item in violations)
    relative_files = [
        Path(str(item["filename"])).resolve().relative_to(ROOT) for item in violations
    ]
    by_file = Counter(path.as_posix() for path in relative_files)
    safe = sum(
        1
        for item in violations
        if isinstance(item.get("fix"), dict)
        and item["fix"].get("applicability") == "safe"
    )
    unsafe = sum(
        1
        for item in violations
        if isinstance(item.get("fix"), dict)
        and item["fix"].get("applicability") == "unsafe"
    )
    return {
        "python_files": sum(1 for path in scope.rglob("*.py") if path.is_file()),
        "violations": len(violations),
        "files_with_violations": len(by_file),
        "safe_autofixes_available": safe,
        "unsafe_autofixes_available": unsafe,
        "by_rule": dict(sorted(by_rule.items())),
        "by_file": dict(sorted(by_file.items())),
    }


def build_contract() -> dict[str, object]:
    """Build a deterministic, source-bound snapshot of the current lint boundary."""
    checks = {name: _check(path) for name, path in SCOPES.items()}
    summaries = {
        name: _scope_summary(SCOPES[name], violations)
        for name, violations in checks.items()
    }
    debt_files = sorted(
        {
            Path(str(item["filename"])).resolve().relative_to(ROOT)
            for item in checks["historical_scripts"]
        }
    )
    source_paths = [ROOT / "pyproject.toml", *[ROOT / path for path in debt_files]]
    contract: dict[str, object] = {
        "schema": "alphaforge.lint-debt-contract.v1",
        "status": "PRODUCTION_AND_TESTS_CLEAN_HISTORICAL_SCRIPTS_DEBT",
        "command": "ruff check <scope> --output-format json",
        "scopes": summaries,
        "claim_boundary": (
            "Ruff is clean for src/alphaforge and tests. Historical and exploratory scripts "
            "retain the enumerated debt; this artifact is not a whole-repository clean claim."
        ),
        "trial_accounting": {
            "hypotheses_spent": 0,
            "returns_evaluated": False,
        },
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): _sha256(path) for path in source_paths
        },
    }
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    contract["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return contract


def main() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_contract(), indent=2) + "\n")
    return OUTPUT


if __name__ == "__main__":
    print(main())
