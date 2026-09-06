from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "seal_lighthouse_accessibility_audit.py"
SPEC = importlib.util.spec_from_file_location("seal_lighthouse_accessibility_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def report(route: str, score: float = 1, binary_score: int = 1) -> dict:
    return {
        "fetchTime": "2026-08-23T00:00:00Z",
        "lighthouseVersion": "12.8.2",
        "requestedUrl": f"http://127.0.0.1:3000{route}",
        "finalUrl": f"http://127.0.0.1:3000{route}",
        "categories": {"accessibility": {"score": score, "auditRefs": [{"id": "contrast"}]}},
        "audits": {"contrast": {"scoreDisplayMode": "binary", "score": binary_score}},
    }


def write_reports(tmp_path: Path, *, score: float = 1, binary_score: int = 1) -> list[Path]:
    paths = []
    for index, route in enumerate(MODULE.REQUIRED_ROUTES):
        path = tmp_path / f"lighthouse-{index}.json"
        path.write_text(json.dumps(report(route, score, binary_score)))
        paths.append(path)
    return paths


def write_interaction_audit(tmp_path: Path) -> Path:
    document = {
        "schema": "canli.site-accessibility-interaction-audit.v1",
        "project_lead": "Arhan Canli",
        "tested_at": "2026-08-23T01:00:00+00:00",
        "environment": "LOCAL_PRODUCTION_BUILD",
        "routes": [
            {
                "route": route,
                "passes": True,
                "keyboard": {"passes": True},
                "reflow_320_css_px_and_targets": {"passes": True},
                "reduced_motion": {"passes": True},
                "forced_colors_main_visible": True,
                "browser_errors": [],
            }
            for route in MODULE.REQUIRED_ROUTES
        ],
        "passes": True,
        "claim_boundary": "Automated browser checks; not human certification.",
    }
    document["content_hash"] = MODULE.content_hash(document)
    path = tmp_path / "interaction.json"
    path.write_text(json.dumps(document))
    return path


def test_seals_only_complete_perfect_multi_route_evidence(tmp_path: Path) -> None:
    result = MODULE.seal(
        write_reports(tmp_path), write_interaction_audit(tmp_path), tmp_path / "receipt.json"
    )
    assert result["schema"] == "canli.site-accessibility-audit.v3"
    assert result["accessibility_score"] == 100
    assert result["routes_tested"] == list(MODULE.REQUIRED_ROUTES)
    assert result["binary_checks_passed"] == 4
    assert result["interaction_audit"]["passes"] is True
    assert result["manual_checks_completed"] == []
    assert any("screen-reader" in item for item in result["untested_human_dimensions"])
    assert result["content_hash"] == MODULE.content_hash(result)
    assert "not complete WCAG" in result["claim_boundary"]


@pytest.mark.parametrize(("score", "binary"), [(0.99, 1), (1, 0)])
def test_refuses_any_imperfect_route(tmp_path: Path, score: float, binary: int) -> None:
    paths = write_reports(tmp_path)
    paths[2].write_text(json.dumps(report("/how-it-works", score, binary)))
    with pytest.raises(ValueError):
        MODULE.seal(paths, write_interaction_audit(tmp_path), tmp_path / "receipt.json")


def test_refuses_incomplete_or_duplicate_route_coverage(tmp_path: Path) -> None:
    paths = write_reports(tmp_path)
    with pytest.raises(ValueError, match="route coverage mismatch"):
        MODULE.seal(
            paths[:-1], write_interaction_audit(tmp_path), tmp_path / "receipt.json"
        )
    paths[-1].write_text(json.dumps(report("/dashboard")))
    with pytest.raises(ValueError, match="duplicate Lighthouse route"):
        MODULE.seal(paths, write_interaction_audit(tmp_path), tmp_path / "receipt.json")


def test_refuses_non_local_report(tmp_path: Path) -> None:
    paths = write_reports(tmp_path)
    payload = report("/research")
    payload["finalUrl"] = "https://example.com/research"
    paths[-1].write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="local production host"):
        MODULE.seal(paths, write_interaction_audit(tmp_path), tmp_path / "receipt.json")


def test_refuses_mutated_interaction_evidence(tmp_path: Path) -> None:
    interaction = write_interaction_audit(tmp_path)
    document = json.loads(interaction.read_text())
    document["routes"][0]["passes"] = False
    document["content_hash"] = MODULE.content_hash(document)
    interaction.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="every_route_passes"):
        MODULE.seal(write_reports(tmp_path), interaction, tmp_path / "receipt.json")


def test_research_export_loader_fails_closed_on_receipt_mutation(tmp_path: Path) -> None:
    export_script = SCRIPT.with_name("research_export.py")
    spec = importlib.util.spec_from_file_location(
        "accessibility_research_export_test", export_script
    )
    assert spec is not None and spec.loader is not None
    export = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export)
    receipt = tmp_path / "receipt.json"
    interaction = write_interaction_audit(tmp_path)
    document = MODULE.seal(write_reports(tmp_path), interaction, receipt)
    assert export._load_accessibility_audit(receipt, interaction) == document

    document["manual_checks_completed"] = ["invented screen-reader certification"]
    document["content_hash"] = MODULE.content_hash(document)
    receipt.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="manual_scope_not_invented"):
        export._load_accessibility_audit(receipt, interaction)
