"""An imported identity is decided only if its own packet says so; nothing is invented.

WHY. The seriality guard blocks new reservations until every forward-epoch identity has a
complete, decided packet. The 118 identities measured in the second checkout had complete
packets there and no decision here. The import writes one KILL closure per identity, but only
when the packet's own decision statement says not-admitted or retrospective/development (the
admission contract can never admit a retrospective measurement as it is). A packet that says
neither is refused, a packet whose content hash does not verify is refused, and the resulting
closure carries the packet's statement verbatim so the mapping is auditable.

Pure: builds a two-tree fixture in a temporary directory; reads no return.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from alphaforge.validation.trial_reservation import _observed_content_hash

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "import_external_identity_packets", REPO / "scripts" / "import_external_identity_packets.py"
)
assert _SPEC is not None and _SPEC.loader is not None
MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MOD)

KEY = "abcdef0123456789"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet(statement: str, evidence_rel: str, evidence_sha: str) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema": MOD.PACKET_SCHEMA,
        "hypothesis_key": KEY,
        "config_hash": "0011223344556677",
        "research_family_key": "test_family",
        "label": "a test arm",
        "complete": True,
        "missing_sections": [],
        "packet_status": "COMPLETE_ACCOUNTING_FINAL_INCOMPLETE_NOT_ADMITTED",
        "required_sections": {
            "admission_or_kill_decision": {
                "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
                "statement": statement,
                "evidence": [{"path": evidence_rel, "sha256": evidence_sha}],
            }
        },
    }
    packet["content_hash"] = _observed_content_hash(packet)
    return packet


def _trees(tmp_path: Path, statement: str) -> tuple[Path, Path]:
    external = tmp_path / "external"
    repo = tmp_path / "repo"
    evidence_rel = "artifacts/analysis/study_1/reservation.json"
    evidence = external / evidence_rel
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({"hypothesis_identity": KEY}), encoding="utf-8")
    packet = _packet(statement, evidence_rel, _sha(evidence))
    packet_path = external / MOD.IDENTITY_PACKET_DIR / f"{KEY}.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    (repo / MOD.IDENTITY_PACKET_DIR).mkdir(parents=True)
    (repo / "config").mkdir()
    (repo / "config" / "trial_accounting_reviews.json").write_text("{}", encoding="utf-8")
    return external, repo


def test_a_retrospective_development_packet_is_imported_with_a_kill_closure(
    tmp_path: Path,
) -> None:
    external, repo = _trees(
        tmp_path, "Retrospective standalone baseline, not untouched OOS or combined qualification."
    )
    row = MOD.import_identity(
        KEY, external=external, repo=repo, imported_on="2026-09-14T00:00:00+00:00"
    )
    assert row["disposition"] == "KILL"
    assert row["evidence_files_copied"] == 1
    packet = json.loads((repo / MOD.IDENTITY_PACKET_DIR / f"{KEY}.json").read_text())
    assert packet["content_hash"] == _observed_content_hash(packet)
    decision = packet["required_sections"]["admission_or_kill_decision"]
    assert decision["status"] == "VERIFIED_FINAL_DEVELOPMENT_CLOSURE_KILL"
    closure_rel = decision["evidence"][-1]["path"]
    closure = json.loads((repo / closure_rel).read_text())
    assert closure["content_hash"] == _observed_content_hash(closure)
    assert closure["decision"]["disposition"] == "KILL"
    assert closure["decision"]["admitted"] is False
    assert closure["decision"]["external_disposition"] == (
        "PACKET_STATEMENT_RETROSPECTIVE_DEVELOPMENT_MEASUREMENT"
    )
    assert closure["decision"]["statement"].startswith("Retrospective standalone baseline")
    assert closure["decision"]["construction_retained_for_a_new_identity"] is False
    assert (repo / "artifacts/analysis/study_1/reservation.json").is_file()


def test_a_packet_that_says_neither_not_admitted_nor_retrospective_is_refused(
    tmp_path: Path,
) -> None:
    external, repo = _trees(tmp_path, "Candidate outperformed every gate and is ready to trade.")
    with pytest.raises(ValueError, match="says neither"):
        MOD.import_identity(
            KEY, external=external, repo=repo, imported_on="2026-09-14T00:00:00+00:00"
        )
    assert not (repo / MOD.IDENTITY_PACKET_DIR / f"{KEY}.json").exists()


def test_a_tampered_external_packet_is_refused(tmp_path: Path) -> None:
    external, repo = _trees(tmp_path, "Known-history combined portfolio development experiment.")
    path = external / MOD.IDENTITY_PACKET_DIR / f"{KEY}.json"
    packet = json.loads(path.read_text())
    packet["label"] = "edited after sealing"
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        MOD.import_identity(
            KEY, external=external, repo=repo, imported_on="2026-09-14T00:00:00+00:00"
        )


def test_evidence_that_differs_between_trees_is_refused(tmp_path: Path) -> None:
    external, repo = _trees(tmp_path, "Retrospective diagnostic, not synchronized executable NAV.")
    here = repo / "artifacts/analysis/study_1/reservation.json"
    here.parent.mkdir(parents=True)
    here.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="differs between trees"):
        MOD.import_identity(
            KEY, external=external, repo=repo, imported_on="2026-09-14T00:00:00+00:00"
        )


def test_the_retained_construction_is_flagged_not_hidden(tmp_path: Path) -> None:
    external, repo = _trees(
        tmp_path,
        "All frozen development criteria passed. Retain for further testing only. "
        "Full admission evaluation is INCOMPLETE_NOT_ADMITTED.",
    )
    study = external / "artifacts/analysis/study_1/development_closure.json"
    study.write_text(
        json.dumps(
            {
                "schema": "alphac.development-comparison-closure.v1",
                "hypothesis_identity": None,
                "disposition": "RETAIN_FOR_FURTHER_TESTING",
                "admitted": None,
            }
        ),
        encoding="utf-8",
    )
    row = MOD.import_identity(
        KEY, external=external, repo=repo, imported_on="2026-09-14T00:00:00+00:00"
    )
    closure = json.loads((repo / row["closure"]).read_text())
    assert closure["decision"]["disposition"] == "KILL"
    assert closure["decision"]["external_disposition"] == "RETAIN_FOR_FURTHER_TESTING"
    assert closure["decision"]["construction_retained_for_a_new_identity"] is True
    assert (
        closure["lineage"]["study_development_closure"]["disposition"]
        == "RETAIN_FOR_FURTHER_TESTING"
    )


def test_forward_identities_without_packets_is_empty_in_this_repository() -> None:
    """The repository must never regress to an undecided forward identity (workspace)."""
    if not (REPO / "var" / "experiments.jsonl").exists():
        pytest.skip("the canonical ledger lives in the working tree")
    missing = MOD.forward_identities_without_packets(REPO)
    assert missing == [], missing[:5]


def test_the_reviews_record_matches_the_closures_on_disk() -> None:
    reviews = json.loads((REPO / "config" / "trial_accounting_reviews.json").read_text())
    events = reviews.get("external_packet_import", [])
    assert len(events) == 1
    event = copy.deepcopy(events[0])
    assert event["identities_imported"] == event["closures_written"] == 118
    assert event["dispositions"] == ["KILL"]
    assert event["remaining_forward_identities_without_packet"] == 0
    assert event["union_count_changed"] is False
    assert event["authorization"].startswith("Arhan Canli, owner, 2026-09-14")
