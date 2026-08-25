"""Both public hosts must receive the same files, because the two write blocks are hand-mirrored.

WHY THIS EXISTS. scripts/research_export.py copies the published bundle into two sites, and it
does it with two long hand-written blocks — one addressing `out_dir`/`literature_dir` (the primary
host) and a near-duplicate addressing `app_dir`/`app_literature_dir`. Adding a file means editing
both, and on 2026-08-22 one of them had drifted: `legacy-dsr-restatement.md`, the paper that
restates every Sharpe the deflation correction touched, was written to the app host only. Nothing
could catch it. The file is not linked from research.json, so its absence broke no link, failed no
build, and returned no 404 — the primary site was just missing a paper, silently, for as long as
nobody diffed two directories by hand.

WHAT THIS ASSERTS, and why it is an invariant rather than a list of today's filenames: every write
whose SOURCE is a file (`SOMETHING.read_text()`) is a copy of an artifact, and an artifact copied
to one host must be copied to the other. Writes whose source is a computed value — the stamped
research.json, written under a different variable on each host — are not copies and are excluded
by that rule rather than by an exemption. An exemption list would rot; this does not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

EXPORTER = Path(__file__).parents[2] / "scripts" / "research_export.py"


def _copies(source: str, dirvar: str) -> set[tuple[str, str]]:
    """Every (public name, source expression) pair copied into `dirvar` from a file.

    `literature_dir` is a SUBSTRING of `app_literature_dir`, so the directory variable is anchored
    on the opening paren and a non-identifier boundary. Matching it loosely would make the primary
    host's set silently include the app host's writes, and the comparison below would then pass no
    matter how far the two blocks drifted.
    """
    flat = re.sub(r"\s+", " ", source)
    pattern = (
        r"\(\s*" + re.escape(dirvar) + r"\s*/\s*([^()]+?)\s*\)\.write_text\(\s*"
        r"([A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*)\.read_text\(\)\s*\)"
    )
    return set(re.findall(pattern, flat))


def _copy_loops(source: str) -> list[tuple[str, ...]]:
    """The (source name, public name) tuple lists driving the loop-based copies."""
    flat = re.sub(r"\s+", " ", source)
    return [
        tuple(re.findall(r'"([^"]+)"', body))
        for body in re.findall(r"for source_name, public_name in \((.+?)\):", flat)
    ]


@pytest.fixture(scope="module")
def exporter() -> str:
    return EXPORTER.read_text()


def test_the_parser_finds_the_writes_it_claims_to_compare(exporter: str) -> None:
    """A parser that matched nothing would make every comparison below pass vacuously.

    This is the whole failure mode of a mirror check: the assertion is `A == B`, and the cheapest
    way to satisfy it is for both sides to be empty. Pin a floor on each side so a regex that
    stops matching fails here instead of quietly certifying two empty sets as identical.
    """
    assert len(_copies(exporter, "out_dir")) > 30
    assert len(_copies(exporter, "app_dir")) > 30
    assert len(_copies(exporter, "literature_dir")) > 20
    assert len(_copies(exporter, "app_literature_dir")) > 20
    loops = _copy_loops(exporter)
    assert len(loops) >= 2
    assert len(loops) % 2 == 0


@pytest.mark.parametrize(
    ("primary", "app"),
    [("out_dir", "app_dir"), ("literature_dir", "app_literature_dir")],
)
def test_both_hosts_receive_the_same_copies(exporter: str, primary: str, app: str) -> None:
    on_primary = _copies(exporter, primary)
    on_app = _copies(exporter, app)
    assert on_primary == on_app, (
        f"the two publish blocks have drifted — {sorted(on_primary - on_app)} reach the primary "
        f"host only, {sorted(on_app - on_primary)} reach the app host only. One host is "
        "publishing a document the other is not."
    )


def test_the_loop_driven_copies_carry_the_same_list(exporter: str) -> None:
    loops = _copy_loops(exporter)
    midpoint = len(loops) // 2
    assert loops[:midpoint] == loops[midpoint:], (
        "the two loop-driven copy lists differ, so one host publishes probe outputs the other "
        f"does not: {loops}"
    )


def test_selected_fundamental_support_evidence_is_written_to_both_hosts(exporter: str) -> None:
    """The pending replay's audit evidence must not exist on only one public host."""
    assert exporter.count("for public_name, source in FUNDAMENTAL_SINGLE_SUPPORT_FILES:") == 2
    assert '(out_dir / public_name).write_bytes(source.read_bytes())' in exporter
    assert '(app_dir / public_name).write_bytes(source.read_bytes())' in exporter


def test_prospective_packet_and_alias_are_written_to_both_hosts(exporter: str) -> None:
    """The forward packet must be public without mutating the retired historical index."""
    assert exporter.count('out_trial_packet_dir / "da5f5f47f99f9bd2.json"') == 1
    assert exporter.count('app_trial_packet_dir / "da5f5f47f99f9bd2.json"') == 1
    assert exporter.count('out_trial_packet_dir / "crypto_carry_portable_v1.json"') == 1
    assert exporter.count('app_trial_packet_dir / "crypto_carry_portable_v1.json"') == 1
    assert exporter.count("CRYPTO_CARRY_PORTABLE_PACKET_JSON.read_text()") == 4


def test_replay_support_includes_success_and_infrastructure_outcomes(exporter: str) -> None:
    """A replacement success must not erase the failed attempt that preceded it."""
    assert '"result.json"' in exporter
    assert '"replay_failure.json"' in exporter
    assert '"replay_infrastructure_failure.json"' in exporter
    assert '"replay_infrastructure_failure_environment.json"' in exporter
    assert '"replay_infrastructure_failure_lake_manifest.json"' in exporter


def test_both_blind_review_packets_publish_templates_to_both_hosts(exporter: str) -> None:
    """External reviewers need the same blank, hash-bound handoff on either public host."""
    assert exporter.count('"repurchase_item703_blind_label_packet.json"') == 2
    assert exporter.count('"active_ownership_item4_v3_blind_label_packet.json"') == 2
    assert exporter.count('"reviewer_attestation.json"') >= 4
    assert "app_repurchase_blind_out" in exporter
    assert "repurchase_blind_out" in exporter
    assert exporter.count('"verify_review.py"') == 2
    assert exporter.count("ACTIVE_OWNERSHIP_HANDOFF_ARCHIVE.read_bytes()") == 2
    assert '"blind_review_packets": build_blind_review_packets()' in exporter


def test_a_one_sided_write_is_detected() -> None:
    """Mutation test. The check above is worth nothing unless it can actually fail."""
    mutated = (
        '(out_dir / "a.json").write_text(A_JSON.read_text())\n'
        '(app_dir / "a.json").write_text(A_JSON.read_text())\n'
        '(app_dir / "b.json").write_text(B_JSON.read_text())\n'
    )
    assert _copies(mutated, "out_dir") != _copies(mutated, "app_dir")


def test_a_computed_write_is_not_treated_as_a_copy() -> None:
    """The stamped bundle is written under a different name on each host and is not an artifact."""
    source = "(app_dir / OUT_FILE.name).write_text(stamped)\n"
    assert _copies(source, "app_dir") == set()


def test_the_app_directory_is_not_read_as_the_primary_one() -> None:
    """The substring trap the parser is anchored against, pinned so the anchoring cannot be lost.

    `literature_dir` matches inside `app_literature_dir` on any loose pattern, which would fold
    the app host's writes into the primary host's set and make the mirror check unfailable.
    """
    source = '(app_literature_dir / "x.md").write_text(X_MD.read_text())\n'
    assert _copies(source, "literature_dir") == set()
    assert _copies(source, "app_literature_dir") == {('"x.md"', "X_MD")}
