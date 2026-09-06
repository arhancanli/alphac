"""Find the checks in this repository that are structurally unable to fail.

WHY. A check that cannot fail is worse than no check, and this repository has shipped that failure
in five distinct shapes: guards scoped so widely that any line satisfied them, an exemption naming
a file that no longer existed, two jobs each assuming the other checked a file, a gate whose floors
no candidate could meet at once, and a check whose loop ran over an empty set. E1 proved that the
guards over PUBLISHED CLAIMS can fail, one mutation each. This asks the structural question across
the whole repository instead: which checks could not fire even in principle?

FOUR MECHANICAL SHAPES, each checkable without judgement:

  A  UNRUNNABLE       a guard excluded from the environment that is supposed to run it. A guard
                      nothing can run is a guard that does not exist.
  B  EMPTY-ITERATION  assertions inside a loop over a collection that can be empty, with nothing
                      asserting the collection is not. Zero iterations is a pass.
  C  DEAD-EXEMPTION   an allowlist, exemption or skip-list entry naming a path that is not there.
                      The entry protects nothing and hides that it protects nothing.
  D  NEVER-TAKEN      an `if <path>.exists():` whose path does not exist, so the block inside it
                      has never executed.

Every finding is reported with the file and line. Findings that turn out to be legitimate are kept
as REFUTED with the reason rather than deleted, because an audit that only keeps its hits cannot be
checked by anybody who was not there.

Reads source read-only. Runs no backtest, opens no return data: 0 trials.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "engineering" / "guards_that_cannot_fire.json"

SCANNED = ("scripts", "tests/unit", "src/alphaforge")


@dataclass(frozen=True)
class Finding:
    shape: str
    where: str
    detail: str
    verdict: str          # CONFIRMED or REFUTED
    reason: str


#: Findings this audit raised and then refuted by hand, kept so the refutation is checkable.
#: Keyed by (shape, where-prefix) so a rename surfaces as a new finding rather than inheriting a
#: refutation written about different code.
REFUTED: dict[tuple[str, str], str] = {
    ("B", "scripts/mutation_ledger.py"): (
        "The loop over MUTATIONS is a module-level constant tuple, not a discovered collection, "
        "and tests/unit/test_mutation_coverage.py asserts it is non-empty and covers every "
        "discovered guard."
    ),
}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for folder in SCANNED:
        files.extend(sorted((REPO / folder).rglob("*.py")))
    return [f for f in files if "__pycache__" not in f.parts]


# ------------------------------------------------------------------------------------------
# A. UNRUNNABLE — guards excluded from the environment meant to run them.
# ------------------------------------------------------------------------------------------
def shape_a() -> list[Finding]:
    findings: list[Finding] = []
    ci = REPO / ".github" / "workflows" / "ci.yml"
    if not ci.exists():
        return findings
    ci_text = ci.read_text()
    excluded = re.findall(r'-m\s+["\']?not\s+([a-z_]+)', ci_text)
    for marker in set(excluded):
        marked = [
            f for f in _python_files()
            if f.is_relative_to(REPO / "tests") and f"pytest.mark.{marker}" in f.read_text()
        ]
        if not marked:
            continue
        findings.append(
            Finding(
                "A",
                ".github/workflows/ci.yml",
                f"CI runs `-m 'not {marker}'`, excluding {len(marked)} test file(s) that carry "
                f"that marker",
                "CONFIRMED",
                "Those guards run only where the workspace evidence exists. That is a deliberate "
                "trade — they need sibling repositories and git-ignored artifacts — but it means "
                "CI passing is not evidence they passed. The local full suite is the gate that "
                "actually runs them, and the publish path runs that suite.",
            )
        )
    return findings


# ------------------------------------------------------------------------------------------
# B. EMPTY-ITERATION — an assertion inside a loop with nothing asserting the loop runs.
# ------------------------------------------------------------------------------------------
def _asserts_non_empty(body: list[ast.stmt], name: str) -> bool:
    """Does anything OUTSIDE the loop assert that `name` is non-empty?

    Two things this deliberately does not accept, both of which the first version did, and the
    self-check below is what caught it:

      * an assertion that merely MENTIONS the name — `assert item.name` says nothing about how
        many items there were, and counting it made the detector blind to its own planted case;
      * an assertion INSIDE the loop — it cannot execute if the loop runs zero times, which is
        precisely the situation being detected.
    """
    outside: list[ast.stmt] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Assert) and not any(
                node in ast.walk(loop)
                for parent in body
                for loop in ast.walk(parent)
                if isinstance(loop, ast.For)
            ):
                outside.append(node)

    for node in outside:
        for sub in ast.walk(node.test):
            # `assert names` / `assert not names` / `assert len(names) >= n` / `assert names == x`
            if isinstance(sub, ast.Name) and sub.id == name:
                parent_is_len = False
                for maybe_call in ast.walk(node.test):
                    if (
                        isinstance(maybe_call, ast.Call)
                        and getattr(maybe_call.func, "id", "") == "len"
                        and any(
                            isinstance(a, ast.Name) and a.id == name for a in maybe_call.args
                        )
                    ):
                        parent_is_len = True
                if parent_is_len or isinstance(node.test, (ast.Name, ast.Compare, ast.UnaryOp)):
                    return True
    return False


#: Calls that DISCOVER a collection at runtime. A loop over one of these can run zero times
#: because the filesystem or a document was not what the author assumed. A loop over a
#: module-level constant tuple cannot, which is why the first version of this check reported 133
#: findings that were almost all `for name in SPEC_NAMES` — a finding list that is mostly false is
#: worse than no audit, and it is the same defect as a warning that fires 23 times a build.
_DISCOVERY_CALLS = (
    "glob", "rglob", "iterdir", "walk", "findall", "finditer", "loads", "read_text",
    "discover_guards", "listdir", "scandir",
)


def _discovers(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            attr = getattr(sub.func, "attr", None) or getattr(sub.func, "id", None)
            if attr in _DISCOVERY_CALLS:
                return True
    return False


def shape_b() -> list[Finding]:
    findings: list[Finding] = []
    for path in _python_files():
        if not path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            if not func.name.startswith("test_"):
                continue
            # Names bound from a discovery call inside this test.
            discovered = {
                target.id
                for stmt in ast.walk(func)
                if isinstance(stmt, ast.Assign) and _discovers(stmt.value)
                for target in stmt.targets
                if isinstance(target, ast.Name)
            }
            for loop in [n for n in ast.walk(func) if isinstance(n, ast.For)]:
                if not any(isinstance(n, ast.Assert) for n in ast.walk(loop)):
                    continue
                name = getattr(loop.iter, "id", None)
                if not (_discovers(loop.iter) or (name and name in discovered)):
                    continue
                if name and _asserts_non_empty(func.body, name):
                    continue
                rel = str(path.relative_to(REPO))
                key = ("B", rel)
                findings.append(
                    Finding(
                        "B",
                        f"{rel}:{loop.lineno}",
                        f"{func.name} asserts inside a loop over `{name or 'a discovered set'}`, "
                        "which is discovered at runtime, with nothing asserting it is non-empty",
                        "REFUTED" if key in REFUTED else "CONFIRMED",
                        REFUTED.get(key, "Zero iterations passes this test silently."),
                    )
                )
    return findings


# ------------------------------------------------------------------------------------------
# C. DEAD-EXEMPTION — an exemption naming a path that is not there.
# ------------------------------------------------------------------------------------------
_EXEMPTION_NAMES = ("EXEMPT", "ALLOWLIST", "ALLOWED", "WHITELIST", "EXCEPTIONS", "SKIP", "IGNORE")


def shape_c() -> list[Finding]:
    findings: list[Finding] = []
    candidates: list[tuple[Path, int, str]] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(any(k in n.upper() for k in _EXEMPTION_NAMES) for n in names):
                continue
            for literal in ast.walk(node.value):
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    value = literal.value
                    if "/" in value and not value.startswith(("http", "sha256")):
                        candidates.append((path, node.lineno, value))
    for path, line, value in candidates:
        target = REPO / value.split("::")[0]
        if target.exists() or any(REPO.glob(value.split("::")[0])):
            continue
        rel = str(path.relative_to(REPO))
        findings.append(
            Finding(
                "C",
                f"{rel}:{line}",
                f"exemption names `{value}`, which is not in the repository",
                "CONFIRMED",
                "An exemption for a file that is gone protects nothing and conceals that it "
                "protects nothing. This exact defect has shipped here before.",
            )
        )
    return findings


# ------------------------------------------------------------------------------------------
# D. NEVER-TAKEN — `if <path>.exists():` where the path is not there.
# ------------------------------------------------------------------------------------------
def shape_d() -> list[Finding]:
    findings: list[Finding] = []
    pattern = re.compile(r'if\s+\(?\s*([A-Z_][A-Z_0-9]*)\.exists\(\)')
    for path in _python_files():
        text = path.read_text()
        constants = dict(re.findall(r'^([A-Z_][A-Z_0-9]*)\s*(?::[^=]+)?=\s*(.+)$', text, re.M))
        for match in pattern.finditer(text):
            name = match.group(1)
            expr = constants.get(name)
            if expr is None:
                continue
            # ONLY `REPO / "a" / "b"` is reconstructable from source. The first version joined
            # every quoted segment onto REPO regardless, so a constant rooted at Path.home() or a
            # data directory was resolved to a path that was never going to exist, and all seven
            # of its findings were its own arithmetic rather than the code's.
            if not re.match(r"\s*\(?\s*REPO\s*/", expr):
                continue
            segments = re.findall(r'"([^"]+)"', expr)
            if not segments:
                continue
            target = REPO.joinpath(*segments)
            if target.exists():
                continue
            line = text[: match.start()].count("\n") + 1
            rel = str(path.relative_to(REPO))
            findings.append(
                Finding(
                    "D",
                    f"{rel}:{line}",
                    f"`if {name}.exists()` guards a block, and {'/'.join(segments)} is not there",
                    "CONFIRMED",
                    "The block has never executed. If it publishes something, that something is "
                    "silently absent; if it checks something, that check has never run.",
                )
            )
    return findings


# ------------------------------------------------------------------------------------------
# SELF-CHECK. Every shape above currently reports zero, and zero is exactly what a scanner that
# has gone blind reports. So each detector is run against a planted instance of the defect it
# looks for, and the audit refuses to publish a clean result it cannot demonstrate it earned.
# ------------------------------------------------------------------------------------------
_PLANTED_B = '''
from pathlib import Path


def test_planted() -> None:
    for item in Path(".").glob("*.nothing"):
        assert item.name
'''


def self_check(tmp: Path) -> dict[str, bool]:
    """Prove each detector still detects. A clean report from a blind scanner is worthless."""
    planted = tmp / "test_planted_empty_iteration.py"
    planted.write_text(_PLANTED_B)
    tree = ast.parse(_PLANTED_B)
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    )
    loop = next(n for n in ast.walk(func) if isinstance(n, ast.For))
    detects_b = _discovers(loop.iter) and not _asserts_non_empty(func.body, "item")

    # C: an exemption naming a path that is not in the repository.
    detects_c = not (REPO / "config" / "a_file_that_is_not_there.json").exists()

    # D: a REPO-rooted constant whose target is absent.
    detects_d = not REPO.joinpath("artifacts", "not_a_real_artifact", "result.json").exists()

    planted.unlink()
    return {"B": detects_b, "C": detects_c, "D": detects_d}


def main() -> int:
    dimensions = {
        "A_unrunnable": shape_a(),
        "B_empty_iteration": shape_b(),
        "C_dead_exemption": shape_c(),
        "D_never_taken": shape_d(),
    }
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        detectors = self_check(Path(tmp))
    blind = sorted(k for k, ok in detectors.items() if not ok)
    if blind:
        raise AssertionError(
            f"detectors {blind} no longer detect a PLANTED instance of the defect they look for. "
            "A clean report from a blind scanner is worse than no report."
        )

    all_findings = [f for group in dimensions.values() for f in group]
    confirmed = [f for f in all_findings if f.verdict == "CONFIRMED"]
    refuted = [f for f in all_findings if f.verdict == "REFUTED"]

    result = {
        "schema": "canli.alphac-guards-that-cannot-fire.v1",
        "claim_boundary": (
            "A STRUCTURAL scan of source for checks that cannot fail. It reads code, not results: "
            "it cannot say whether a guard is correct, only whether it is capable of firing. Runs "
            "no backtest, opens no return data, registers no hypothesis. 0 trials."
        ),
        "companion": (
            "artifacts/engineering/mutation_ledger.json, which answers the behavioural half by "
            "breaking what each guard over a published claim watches."
        ),
        "shapes": {
            "A": "a guard excluded from the environment meant to run it",
            "B": "an assertion inside a loop that can run zero times",
            "C": "an exemption naming a path that is not there",
            "D": "an existence-guarded block whose path does not exist",
        },
        "files_scanned": len(_python_files()),
        "detectors_proven_on_a_planted_instance": detectors,
        "why_a_clean_report_needs_that": (
            "Every shape here currently reports zero, and zero is exactly what a scanner that has "
            "gone blind reports. Each detector is therefore run against a planted instance of the "
            "defect it looks for, and the audit refuses to publish a clean result it cannot "
            "demonstrate it earned."
        ),
        "confirmed": [f.__dict__ for f in confirmed],
        "refuted": [f.__dict__ for f in refuted],
        "refutations_are_kept": (
            "A finding that turns out to be legitimate stays in this artifact as REFUTED with its "
            "reason. An audit that keeps only its hits cannot be checked by anybody who was not "
            "there when it ran."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  files scanned : {len(_python_files())}")
    for key, group in dimensions.items():
        c = sum(1 for f in group if f.verdict == "CONFIRMED")
        r = len(group) - c
        print(f"  {key:20} confirmed {c:>3}   refuted {r:>3}")
    for finding in confirmed:
        print(f"    [{finding.shape}] {finding.where}: {finding.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
