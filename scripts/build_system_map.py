"""Render docs/design/SYSTEM_MAP.md from the repository, not from memory.

WHY. Someone arriving cold — including whoever inherits this machine — faces 191 Python scripts,
17 shell entry points, 20 contracts and two publish pipelines with no statement of what the whole
thing is. Every existing document describes one part.

WHY IT IS GENERATED. A hand-written map is accurate on the day it is written and quietly wrong
afterwards, which is worse than none: it is the same defect as a hard-coded count on a published
page, and this repository has now caught that four times. Everything below is read off the files.
Each script's one-line purpose is the first line of its own docstring, so a script with no
docstring appears in the map as having none — visible, rather than absent.

`tests/unit/test_system_map_is_current.py` fails if the committed map is not what a fresh render
produces, and the pre-commit hook regenerates it, so it cannot drift silently.

Reads source and configuration read-only. Runs no backtest, opens no return data: 0 trials.
"""

from __future__ import annotations

import ast
import json
import plistlib
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "docs" / "design" / "SYSTEM_MAP.md"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"


def _docstring_first_line(path: Path) -> str:
    """The first line of a file's module docstring — its own statement of what it is for."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, OSError):
        return "_(unreadable)_"
    doc = ast.get_docstring(tree)
    if not doc:
        return "_(no docstring)_"
    return doc.strip().splitlines()[0].strip()


def _shell_purpose(path: Path) -> str:
    """A shell script's purpose: the first non-shebang, non-banner comment line."""
    for line in path.read_text().splitlines()[:40]:
        stripped = line.strip()
        if not stripped.startswith("#") or stripped.startswith("#!"):
            continue
        text = stripped.lstrip("#").strip()
        if not text or set(text) <= {"=", "-"} or (text.upper() == text and len(text) < 60):
            continue
        return text
    return "_(no comment)_"


def _steps_of(shell: Path) -> list[str]:
    """The scripts a shell pipeline invokes, in the order it invokes them."""
    seen: list[str] = []
    for match in re.finditer(r"(?:uv run python|python3?)\s+(scripts/[\w./-]+)", shell.read_text()):
        step = match.group(1)
        if step not in seen:
            seen.append(step)
    return seen


def _scheduled_jobs() -> list[dict[str, Any]]:
    jobs = []
    if not LAUNCH_AGENTS.is_dir():
        return jobs
    for plist in sorted(LAUNCH_AGENTS.glob("com.accapital.*.plist")):
        try:
            data = plistlib.loads(plist.read_bytes())
        except Exception:
            continue
        args = data.get("ProgramArguments") or []
        target = next((a for a in reversed(args) if "alphaforge" in a), args[-1] if args else "")
        if "alphaforge" not in target:
            continue
        calendar = data.get("StartCalendarInterval")
        interval = data.get("StartInterval")
        if isinstance(calendar, dict):
            when = f"{calendar.get('Hour', '*'):0>2}:{calendar.get('Minute', 0):0>2} daily"
        elif isinstance(calendar, list):
            when = f"{len(calendar)} times daily"
        elif interval:
            when = f"every {int(interval) // 60} min"
        else:
            when = "on demand"
        jobs.append(
            {
                "label": data.get("Label", plist.stem),
                "runs": Path(target).name,
                "when": when,
            }
        )
    return jobs


def _claim_boundary(path: Path) -> str:
    try:
        doc = json.loads(path.read_text())
    except (ValueError, OSError):
        return ""
    if not isinstance(doc, dict):
        return ""
    for key in ("claim_boundary", "summary", "note", "status"):
        value = doc.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().split(". ")[0].rstrip(".") + "."
    return ""


def _table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(out)


def render() -> str:
    scripts = sorted((REPO / "scripts").glob("*.py"))
    shells = sorted((REPO / "scripts").glob("*.sh"))
    configs = sorted((REPO / "config").glob("*.json"))
    contracts = sorted((REPO / "artifacts" / "engineering").glob("*.json"))
    tests = sorted((REPO / "tests" / "unit").glob("test_*.py"))
    lakes = (
        sorted(q for q in (REPO / "data").iterdir() if q.is_dir())
        if (REPO / "data").is_dir()
        else []
    )
    jobs = _scheduled_jobs()

    kinds: dict[str, list[Path]] = {
        "analyze_": [], "audit_": [], "build_": [], "probe_": [], "collect_": [],
        "ingest_": [], "check_": [], "export_": [], "run_": [], "verify_": [],
    }
    other: list[Path] = []
    for script in scripts:
        for prefix, bucket in kinds.items():
            if script.name.startswith(prefix):
                bucket.append(script)
                break
        else:
            other.append(script)

    parts: list[str] = []
    parts.append(f"""# System map

**Generated by `scripts/build_system_map.py`. Do not edit by hand.**

A hand-written map is accurate on the day it is written and quietly wrong afterwards, which is
worse than no map at all. Everything here is read off the files: each script's purpose is the first
line of its own docstring, each pipeline's steps are the scripts it actually invokes, and each
contract's boundary is the boundary it states about itself. A script with no docstring appears as
having none.

At a glance: **{len(scripts)} Python scripts**, **{len(shells)} shell entry points**,
**{len(configs)} configuration contracts**, **{len(contracts)} engineering artifacts**,
**{len(tests)} unit test files**, **{len(lakes)} data directories**, **{len(jobs)} scheduled jobs**.
""")

    parts.append("\n## What runs on a timer\n")
    if jobs:
        parts.append(
            _table(
                [(j["label"], f"`{j['runs']}`", j["when"]) for j in jobs],
                ("launchd label", "runs", "when"),
            )
        )
    else:
        parts.append("_No `com.accapital.*` agents found on this machine._")
    parts.append(
        "\nThese are the only paths that run without somebody typing a command. Everything else\n"
        "in this repository is invoked by hand or by one of these.\n"
    )

    parts.append("\n## The pipelines, and what each step is\n")
    for shell in shells:
        steps = _steps_of(shell)
        if not steps:
            continue
        parts.append(f"\n### `scripts/{shell.name}`\n")
        parts.append(f"{_shell_purpose(shell)}\n")
        parts.append(
            _table(
                [
                    (f"{i + 1}", f"`{step}`", _docstring_first_line(REPO / step))
                    for i, step in enumerate(steps)
                    if (REPO / step).exists()
                ],
                ("#", "step", "what it is"),
            )
        )

    parts.append("\n## Contracts — the things that say what may be published\n")
    parts.append(
        "A contract is a file that other code reads to decide whether something is allowed. These\n"
        "are the ones a reader has to know about; everything else is derived from them.\n"
    )
    rows = []
    for path in configs + contracts:
        boundary = _claim_boundary(path)
        rows.append(
            (
                f"`{path.relative_to(REPO)}`",
                (boundary[:150] + "…")
                if len(boundary) > 150
                else (boundary or "_(no stated boundary)_"),
            )
        )
    parts.append(_table(rows, ("file", "what it governs, in its own words")))

    parts.append("\n## Scripts by kind\n")
    parts.append(
        "Grouped by the verb they start with, which is this repository's only naming convention\n"
        "and is worth more than a hand-made taxonomy that would drift.\n"
    )
    for prefix, bucket in kinds.items():
        if not bucket:
            continue
        parts.append(f"\n### `{prefix}*` ({len(bucket)})\n")
        parts.append(
            _table(
                [(f"`{p.name}`", _docstring_first_line(p)) for p in bucket],
                ("script", "first line of its docstring"),
            )
        )
    if other:
        parts.append(f"\n### everything else ({len(other)})\n")
        parts.append(
            _table(
                [(f"`{p.name}`", _docstring_first_line(p)) for p in other],
                ("script", "first line of its docstring"),
            )
        )

    parts.append("\n## Where the evidence lives\n")
    parts.append(
        _table(
            [(f"`data/{q.name}/`", "") for q in lakes],
            ("directory", ""),
        )
    )
    parts.append(
        "\nDeliberately no file counts: the collectors write into these every day, and a number\n"
        "committed here would be wrong by the time anybody read it — and would make the currency\n"
        "check below fail hourly for nothing.\n"
    )
    parts.append(
        "\nNone of `data/` or `artifacts/` is tracked by git. The published copies under\n"
        "`~/meridian/public/glassbox/` are what an outsider can check, and\n"
        "`artifacts/engineering/claim_coverage_map.json` says which of those has a guard and\n"
        "which mechanism guards it.\n"
    )

    parts.append("\n## How to check that any of this is true\n")
    parts.append(
        "- `scripts/reproduce.py` — recompute every published hash and signature.\n"
        "- `scripts/mutation_ledger.py` — break what each guard watches and record whether it\n"
        "  fails.\n"
        "- `scripts/build_claim_coverage_map.py` — which published claim has which guard.\n"
        "- `scripts/audit_guards_that_cannot_fire.py` — checks that could not fail even in "
        "principle.\n"
        "- `.venv/bin/python -m pytest tests/unit` — the full suite; add `-n0` to debug one test.\n"
    )
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render())
    print(f"wrote {OUTPUT.relative_to(REPO)} ({len(render().splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
