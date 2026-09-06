"""Every artifact that publishes a content_hash must reproduce under the PUBLIC verifier.

WHAT WENT WRONG, which this exists to stop repeating. `scripts/reproduce.py` is downloadable from
canlicapital.com/glassbox and is the whole basis of the claim that our record verifies. It
recomputes each artifact's sha256 over the entire payload MINUS `content_hash`. Every exporter
followed that convention except `audit_sleeve_family_lineage.py`, which stamped `generated_at`
AFTER taking the hash -- leaving a field inside the published file that no hash covered.

So the kit reported "22 reproduced, 1 failed" and the publish pipeline shipped it anyway, because
the self-check is a WARN. Anyone who downloaded the verifier we advertise got a FAIL. For a record
whose only asset is that it checks out, that is worse than publishing nothing.

WHY THIS TEST IMPORTS reproduce.py RATHER THAN REIMPLEMENTING IT. A test that recomputed the hash
its own way would be a second implementation free to drift from the one the public actually runs,
and would then certify a convention nobody outside this repo uses. The assertion has to be made
with the public's function or it is not the public's guarantee.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO / "artifacts"
#: Sibling site workspaces. Scanned when present; their absence is not a pass, it is a skip,
#: and the repo tree below is always scanned so the test can never go vacuously green.
PUBLISHED = (
    Path.home() / "meridian" / "public" / "glassbox",
    Path.home() / "meridian-app" / "public" / "glassbox",
)

#: The exporters wrote 22 hashed artifacts when this was written. The floor exists because a glob
#: that matches nothing makes every parametrized case pass -- the failure mode this project has
#: shipped before. It is a floor, not a pin: adding artifacts must not fail the suite.
MIN_HASHED_ARTIFACTS = 20


def _load_public_verifier() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_reproduce_public", REPO / "scripts" / "reproduce.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VERIFIER = _load_public_verifier()


def _hashed_payloads(root: Path) -> list[tuple[Path, dict]]:
    """Every *.json under `root` that publishes a sha256 content_hash.

    Signature-verified artifacts are excluded exactly as `reproduce.py` excludes them: their
    integrity is the Ed25519 signature, not a content hash.
    """
    found: list[tuple[Path, dict]] = []
    for path in sorted(root.rglob("*.json")):
        if path.name in VERIFIER._SIGNED or path.name == "repro_manifest.json":
            continue
        try:
            payload = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        digest = payload.get("content_hash")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            found.append((path, payload))
    return found


@pytest.mark.workspace_evidence
def test_the_scan_finds_the_artifacts_it_claims_to_check() -> None:
    """A glob that matches nothing certifies nothing."""
    assert ARTIFACTS.is_dir(), f"{ARTIFACTS} missing — this test cannot report a pass"
    found = _hashed_payloads(ARTIFACTS)
    assert len(found) >= MIN_HASHED_ARTIFACTS, (
        f"only {len(found)} hashed artifacts found under {ARTIFACTS}; expected at least "
        f"{MIN_HASHED_ARTIFACTS}. Either the exporters stopped writing content_hash or this "
        f"scan stopped finding them — both make the guarantee below vacuous."
    )


@pytest.mark.workspace_evidence
def test_every_repo_artifact_reproduces_under_the_public_convention() -> None:
    failures = [
        str(path.relative_to(REPO))
        for path, payload in _hashed_payloads(ARTIFACTS)
        if VERIFIER._canon_hash(payload) != payload["content_hash"]
    ]
    assert not failures, (
        "these artifacts do not reproduce under scripts/reproduce.py, the verifier we publish:\n  "
        + "\n  ".join(failures)
        + "\nThe usual cause is a field stamped into the payload AFTER the hash was taken."
    )


@pytest.mark.workspace_evidence
@pytest.mark.parametrize("site", PUBLISHED, ids=lambda p: p.parent.parent.name)
def test_every_published_artifact_reproduces_under_the_public_convention(site: Path) -> None:
    """The published bundle is what a reader actually downloads and checks."""
    if not site.is_dir():
        pytest.skip(f"{site} not present in this workspace")
    found = _hashed_payloads(site)
    assert found, f"{site} exists but publishes no hashed artifact — that is not a passing state"
    failures = [
        f"{path.name}: published {payload['content_hash'][:22]}… "
        f"recomputes {VERIFIER._canon_hash(payload)[:22]}…"
        for path, payload in found
        if VERIFIER._canon_hash(payload) != payload["content_hash"]
    ]
    assert not failures, "published artifacts that do not verify:\n  " + "\n  ".join(failures)


def test_this_check_can_fail() -> None:
    """A check that cannot fail is worse than no check.

    Mutating one byte of a payload must break its hash. Without this, a `_canon_hash` that
    returned a constant — or a comparison accidentally made against itself — would pass every
    assertion above on every artifact.
    """
    payload = {"a": 1, "b": ["x"], "generated_at": "2026-08-19T00:00:00+00:00"}
    payload["content_hash"] = VERIFIER._canon_hash(payload)
    assert VERIFIER._canon_hash(payload) == payload["content_hash"]

    tampered = {**payload, "b": ["y"]}
    assert VERIFIER._canon_hash(tampered) != tampered["content_hash"]

    # and specifically the defect that was shipped: a field the hash does not cover
    stamped_after = {**payload, "generated_at": "2026-08-20T00:00:00+00:00"}
    assert VERIFIER._canon_hash(stamped_after) != stamped_after["content_hash"], (
        "generated_at must be INSIDE the hashed payload; if it is not, the exporter can stamp it "
        "after hashing and the artifact will never reproduce"
    )


# ---------------------------------------------------------------------------------------------
# The same guarantee, statically, so CI can enforce it.
#
# The three tests above are marked `workspace_evidence` and CI runs
# `pytest -m 'not network and not workspace_evidence'` -- artifacts/ is git-ignored, so they
# genuinely cannot run there. That would leave the guarantee local-only, which is how this class
# of defect survives. The defect is detectable without any artifact: it is a payload key written
# AFTER the hash was taken. That is a property of the exporter's source, and every exporter is
# tracked in git.
# ---------------------------------------------------------------------------------------------

import ast  # noqa: E402

SCRIPTS = REPO / "scripts"


def _payload_key_written(node: ast.AST) -> tuple[str, str] | None:
    """`name["literal"] = ...` -> (name, literal), else None."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return node.value.id, key.value
    return None


def _late_writes(source: str) -> list[tuple[int, str, str]]:
    """Every `payload[k] = ...` that runs after `payload["content_hash"] = ...` in the same body."""
    tree = ast.parse(source)
    scopes = [tree] + [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    found: list[tuple[int, str, str]] = []
    for scope in scopes:
        body = getattr(scope, "body", [])
        hashed_at: dict[str, int] = {}
        for index, stmt in enumerate(body):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                written = _payload_key_written(target)
                if written and written[1] == "content_hash":
                    hashed_at[written[0]] = index
        for var, index in hashed_at.items():
            for stmt in body[index + 1 :]:
                for node in ast.walk(stmt):
                    if not isinstance(node, ast.Assign):
                        continue
                    for target in node.targets:
                        written = _payload_key_written(target)
                        if written and written[0] == var and written[1] != "content_hash":
                            found.append((node.lineno, var, written[1]))
    return found


def _exporters_that_hash() -> list[Path]:
    return [path for path in sorted(SCRIPTS.glob("*.py")) if '["content_hash"]' in path.read_text()]


def test_the_static_scan_finds_the_exporters_it_claims_to_check() -> None:
    """28 exporters wrote a content_hash when this was written.

    A scan that finds none proves nothing.
    """
    assert len(_exporters_that_hash()) >= 20, (
        "the content_hash exporter scan found almost nothing — either the convention changed or "
        "the scan broke, and either way the assertion below is vacuous"
    )


def test_no_exporter_writes_a_payload_key_after_taking_its_hash() -> None:
    """The defect that shipped, caught in source rather than in the published bundle.

    `audit_sleeve_family_lineage.py` stamped `generated_at` one line after computing the hash.
    Nothing failed at write time; the artifact simply could never reproduce, and the only thing
    that noticed was the verifier we hand to the public.
    """
    offenders = [
        f"{path.relative_to(REPO)}:{line} writes {var}[{key!r}] after {var}['content_hash']"
        for path in _exporters_that_hash()
        for line, var, key in _late_writes(path.read_text())
    ]
    assert not offenders, (
        "these exporters mutate the payload after hashing it, so their artifacts cannot "
        "reproduce under scripts/reproduce.py:\n  " + "\n  ".join(offenders)
    )


def test_the_static_scan_can_fail() -> None:
    """Feed it the exact shape that shipped and require it to object."""
    shipped_defect = (
        "def run():\n"
        "    payload = {}\n"
        '    payload["content_hash"] = digest(payload)\n'
        '    payload["generated_at"] = now()\n'
    )
    assert _late_writes(shipped_defect) == [(4, "payload", "generated_at")]

    corrected = (
        "def run():\n"
        "    payload = {}\n"
        '    payload["generated_at"] = now()\n'
        '    payload["content_hash"] = digest(payload)\n'
    )
    assert _late_writes(corrected) == []
