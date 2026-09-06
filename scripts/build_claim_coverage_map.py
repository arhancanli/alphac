"""Which published claims have a guard, which mechanism guards them, and when it last ran.

WHY. Nothing said. Every guard in this repository reports on itself and none of them reports on
the SET — so a published artifact with no guard at all looked exactly like one with three, and the
repository has already shipped the consequence twice: two publish jobs each assuming the other
checked a file, and five honesty guards all running and none able to fire. Split coverage reads as
coverage right up until somebody asks which job checks which file.

WHAT A CLAIM IS HERE. One published artifact. That is the unit a reader can download, and it is
the unit a guard can name.

THE FIVE MECHANISMS, and they are not equal:

  NAMED_GUARD    a test or verifier that mentions this artifact specifically. The strongest.
  CONTENT_HASH   the artifact carries a sha256 over its own canonical bytes, recomputed by the
                 published reproduce kit. Proves it was not edited after publication; proves
                 nothing about whether it is right.
  SIGNATURE      Ed25519 over the payload, for the commitments and the append-only chain.
  RENDERED_PAGE  it becomes a measurement page, so the site verifier checks it renders with a
                 claim boundary and is reachable.
  HOST_MIRROR    both hosts receive the identical file. The WEAKEST: it says two copies agree,
                 and nothing about what they say.

An artifact whose ONLY coverage is the mirror is the finding this map exists to produce.

Derived from what is actually published, not from a list. 0 trials.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SITE = REPO.parent / "meridian"
GLASSBOX = SITE / "public" / "glassbox"
EXPORTER = REPO / "scripts" / "research_export.py"
OUTPUT = REPO / "artifacts" / "engineering" / "claim_coverage_map.json"

#: Verified by signature rather than by content hash — reproduce.py skips them at L1 on purpose.
SIGNED = ("capacity_commitment.json", "founder_commitment.json", "transparency_log.json")


def _guard_sources() -> dict[str, str]:
    """Every file that acts as a guard over published claims, and its text."""
    paths: list[Path] = sorted((REPO / "tests" / "unit").glob("test_*.py"))
    paths += sorted((SITE / "scripts").glob("*.mjs"))
    paths += [
        REPO / "scripts" / "reproduce.py",
        REPO / "scripts" / "check_retracted_claims.py",
        REPO / "scripts" / "verify_transparency.py",
        REPO / "scripts" / "mutation_ledger.py",
        REPO / "scripts" / "audit_guards_that_cannot_fire.py",
        REPO / "scripts" / "audit_contract_and_units.py",
    ]
    return {
        str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p.relative_to(SITE.parent)): (
            p.read_text()
        )
        for p in paths
        if p.exists()
    }


def _rendered_artifacts() -> set[str]:
    """Artifacts that become a measurement page, by the builder's own discovery rule."""
    research = GLASSBOX / "research.json"
    if not research.exists():
        return set()
    bundle = json.loads(research.read_text())

    def qualifies(value: Any) -> bool:
        return isinstance(value, dict) and (
            "claim_boundary" in value
            or (isinstance(value.get("schema"), str) and value["schema"].startswith("canli."))
        )

    rendered: set[str] = set()
    for key, value in bundle.items():
        if not isinstance(value, dict):
            continue
        if qualifies(value) or any(qualifies(child) for child in value.values()):
            rendered.add(key)
    return rendered


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    """Run a guard mechanism now, so 'last run' is observed rather than asserted."""
    started = datetime.now(UTC).isoformat(timespec="seconds")
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()][-3:]
    return {
        "command": " ".join(command),
        "cwd": str(cwd),
        "ran_at": started,
        "exit_code": result.returncode,
        "outcome": "PASS" if result.returncode == 0 else "FAIL",
        "tail": tail,
    }


def main() -> int:
    guards = _guard_sources()
    rendered = _rendered_artifacts()
    exporter = EXPORTER.read_text()

    rows: list[dict[str, Any]] = []
    for path in sorted(GLASSBOX.glob("*.json")):
        try:
            document = json.loads(path.read_text())
        except (ValueError, OSError):
            document = None
        named = sorted(name for name, text in guards.items() if path.stem in text)
        mechanisms: list[str] = []
        if named:
            mechanisms.append("NAMED_GUARD")
        if isinstance(document, dict) and "content_hash" in document:
            mechanisms.append("CONTENT_HASH")
        if path.name in SIGNED:
            mechanisms.append("SIGNATURE")
        if path.stem in rendered:
            mechanisms.append("RENDERED_PAGE")
        if f'"{path.name}"' in exporter:
            mechanisms.append("HOST_MIRROR")
        rows.append(
            {
                "artifact": path.name,
                "mechanisms": mechanisms,
                "named_guards": named,
                "strongest": mechanisms[0] if mechanisms else "NONE",
            }
        )

    unguarded = [r["artifact"] for r in rows if not r["mechanisms"]]
    mirror_only = [r["artifact"] for r in rows if r["mechanisms"] == ["HOST_MIRROR"]]

    # REBUILD FIRST, IN THE PUBLISH PIPELINE'S DECLARED ORDER. The first run of this map recorded
    # the unit suite as FAILING, and it was the known ordering transient: adding a script leaves
    # the lint-debt contract stale until the exporter reruns, and the publish path reruns it before
    # anything is checked. Observing the suite in a state the publish path never ships would have
    # published a FAIL that describes nothing real.
    print("rebuilding in the publish pipeline's declared order before observing…")
    rebuild = {
        "lint_debt_contract": _run([sys.executable, "scripts/export_lint_debt_contract.py"], REPO),
        "research_export": _run([sys.executable, "scripts/research_export.py"], REPO),
    }

    print("running each mechanism so 'last run' is observed rather than asserted…")
    last_run = {
        "unit_suite": _run([sys.executable, "-m", "pytest", "tests/unit", "-q", "--no-cov"], REPO),
        "reproduce_kit": _run([sys.executable, "scripts/reproduce.py"], REPO),
        "retracted_claim_gate": _run([sys.executable, "scripts/check_retracted_claims.py"], REPO),
        "site_verifiers": _run(["npm", "run", "--silent", "verify"], SITE),
    }

    result = {
        "schema": "canli.alphac-claim-coverage-map.v1",
        "claim_boundary": (
            "Maps each PUBLISHED ARTIFACT to the mechanisms that guard it and records when each "
            "mechanism last ran, by running it. It does not claim any guard is correct — only "
            "which claims have one and which do not. Runs no backtest, opens no return data, "
            "registers no hypothesis identity. 0 trials."
        ),
        "why": (
            "Split coverage reads as coverage. Every guard here reports on itself and none "
            "reported on the set, so an artifact with no guard looked exactly like one with three."
        ),
        "mechanisms": {
            "NAMED_GUARD": "a test or verifier that mentions this artifact specifically",
            "CONTENT_HASH": "recomputed by the published reproduce kit; proves it was not edited "
            "after publication and nothing about whether it is right",
            "SIGNATURE": "Ed25519 over the payload",
            "RENDERED_PAGE": "rendered as a measurement page and checked for a claim boundary",
            "HOST_MIRROR": "both hosts receive the identical file — the weakest, because it says "
            "two copies agree and nothing about what they say",
        },
        "published_artifacts": len(rows),
        "with_a_named_guard": sum(1 for r in rows if "NAMED_GUARD" in r["mechanisms"]),
        "unguarded": unguarded,
        "guarded_only_by_the_host_mirror": mirror_only,
        "what_mirror_only_means": (
            "We verify both hosts received the identical file, and nothing verifies the file. No "
            "test names it, it carries no content hash, it renders on no page. If its contents "
            "went stale or wrong, both hosts would publish the same wrong thing and every check "
            "would pass."
        ),
        "rebuilt_before_observing": rebuild,
        "why_rebuild_first": (
            "The publish path rebuilds the derived contracts before anything checks them, so a "
            "suite observed before that rebuild reports a failure the publish never ships. The "
            "first run of this map did exactly that."
        ),
        "last_run": last_run,
        "coverage": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(f"\nwrote {OUTPUT.relative_to(REPO)}")
    print(f"  published artifacts        : {len(rows)}")
    print(f"  with a named guard         : {result['with_a_named_guard']}")
    print(f"  UNGUARDED                  : {len(unguarded)} {unguarded}")
    print(f"  mirror-only (weakest)      : {len(mirror_only)}")
    for name in mirror_only:
        print(f"      {name}")
    print("  last run:")
    for key, value in last_run.items():
        print(f"      {key:22} {value['outcome']}  ({value['ran_at']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
