"""The retracted-claim gate's own exemptions must stay honest.

WHAT WENT WRONG. `EXEMPT_NAMES` read
`{"paper-state.json", "track_record.json", "transparency.json"}` — three entries, none of them
right.

`transparency.json` MATCHES NO FILE. The signed append-only chain publishes as
`transparency_log.json`, so the one exemption that was actually justified was never in force.
Nobody noticed, because the chain passes the gate on its merits.

The two that WERE in force are the published surfaces the dashboard renders from, regenerated
from source every hour and therefore always fixable. Exempting them is how AlphaVintage's
withdrawn net Sharpe 0.3403 sat on canlicapital.com in the single most-read file on the site
while this gate reported a clean pass.

The rule the set now follows: an IMMUTABLE copy may be exempt, every MUTABLE copy is scanned.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE_PATH = REPO / "scripts" / "check_retracted_claims.py"
SCRIPTS = REPO / "scripts"

#: Published surfaces that must never be exempted again. Named individually, because this is a
#: regression pin on a specific incident and a generic "the set is small" assertion would not
#: have caught it.
MUST_BE_SCANNED = ("paper-state.json", "track_record.json", "research.json")

#: The only copy that cannot be repaired, and therefore the only one that may be exempt.
_IMMUTABLE_ONLY = ("transparency_log.json",)


def _load_gate() -> Any:
    spec = importlib.util.spec_from_file_location("_retracted_gate", GATE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load_gate()


def test_every_exempt_name_is_a_file_something_actually_writes() -> None:
    """A misspelled exemption is worse than no exemption: it silently protects nothing.

    "Some exporter writes it" is checked by looking for the literal filename in a script OTHER
    than the gate itself — the gate naturally contains every name it exempts, so including it
    would make this assertion vacuous. That distinction is the whole test: `transparency.json`
    appeared in exactly one file, and it was the gate.
    """
    writers = [p for p in sorted(SCRIPTS.glob("*.py")) if p != GATE_PATH]
    assert writers, "no exporter scripts found — this check cannot report a pass"
    for name in GATE.EXEMPT_NAMES:
        produced_by = [p.name for p in writers if name in p.read_text()]
        assert produced_by, (
            f"EXEMPT_NAMES contains {name!r} but no script outside the gate ever names it. "
            f"Either it is a typo (the case that shipped: 'transparency.json' for "
            f"'transparency_log.json') or it exempts a file that no longer exists."
        )


@pytest.mark.parametrize("name", MUST_BE_SCANNED)
def test_the_published_surfaces_are_not_exempt(name: str) -> None:
    assert name not in GATE.EXEMPT_NAMES, (
        f"{name} is regenerated from source every publish cycle, so a withdrawn claim in it is "
        f"always fixable and must never be exempted. Exempting it is what let a killed sleeve "
        f"read as validated on the live site for three days."
    )


def test_the_exemption_is_justified_only_by_immutability() -> None:
    """Only the signed append-only chain qualifies, because it alone cannot be repaired.

    An entry in the chain is hash-linked and signed the moment it is written, so a bare claim
    inside it can be answered only by APPENDING a retraction the 400-byte window will never see.
    Anything regenerated can simply be fixed instead. If a future entry appears here, it needs
    the same argument in writing — that is what this assertion asks for.
    """
    assert set(GATE.EXEMPT_NAMES) == set(_IMMUTABLE_ONLY), (
        f"EXEMPT_NAMES is {sorted(GATE.EXEMPT_NAMES)}. Adding an exemption means claiming the "
        f"file cannot be repaired. Document why, then update this test deliberately."
    )


def test_the_blocklist_parses_to_real_rules() -> None:
    """A blocklist that parses to zero rules is a gate that cannot fail.

    This has happened here: the file's own regexes contain alternation, an earlier parser split
    on '|', every pattern failed to compile, and the guard against unenforced rules was itself
    unenforceable on its first run.
    """
    rules = GATE.load_rules()
    assert len(rules) >= 5, f"only {len(rules)} rules parsed from the blocklist"
    assert all(r.pattern.pattern for r in rules)


def test_a_bare_assertion_is_caught_and_a_disclosed_one_is_not(tmp_path: Path) -> None:
    """The gate's actual behaviour, both directions.

    Satisfied by DISCLOSURE, never by silence: the withdrawn number must remain quotable inside
    its own retraction, or the rule would push this project toward hiding mistakes.
    """
    rules = GATE.load_rules()

    bare = tmp_path / "bare.json"
    bare.write_text('{"claim": "net Sharpe 0.3403 over 5,996 days, a validated sleeve."}')
    assert GATE.scan(tmp_path, rules), "a bare assertion of a withdrawn number must be caught"

    bare.unlink()
    disclosed = tmp_path / "disclosed.json"
    disclosed.write_text(
        '{"claim": "CORRECTION: we published net Sharpe 0.3403; that figure is WITHDRAWN and its '
        'artifact records verdict KILLED."}'
    )
    assert not GATE.scan(tmp_path, rules), (
        "a withdrawn number quoted inside its own retraction must PASS — the check is satisfied "
        "by disclosure, not by deletion"
    )


def test_local_nonclaim_collision_cannot_launder_a_sharpe_assertion(tmp_path: Path) -> None:
    """A same-digit metric may pass, but it cannot exempt another field nearby."""
    rules = GATE.load_rules()

    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text('{"gross_mean": 0.3403301010612419, "sharpe": 2.5034942434773373}')
    assert not GATE.scan(tmp_path, rules), (
        "the K30 gross-mean observation is not the withdrawn AlphaVintage Sharpe claim"
    )

    unrelated.write_text(
        '{"gross_mean": 0.3403301010612419, "net_sharpe": 0.3403, '
        '"claim": "validated sleeve"}'
    )
    violations = GATE.scan(tmp_path, rules)
    assert violations, "a local gross_mean exclusion must not excuse a nearby net Sharpe claim"
    assert len(violations) == 1, "only the net Sharpe use should remain a violation"
    assert violations[0][1].pattern.pattern == r"0\.3403"
