from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_sleeve_publication_bundles.py"


def _module():
    spec = importlib.util.spec_from_file_location("sleeve_publication_bundles", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registry_items() -> list[dict]:
    return json.loads((ROOT / "config/external_publication_registry.json").read_text())["sleeves"]


def _evidence(key: str) -> dict:
    catalog = json.loads((ROOT / "config/sleeve_publication_evidence.json").read_text())
    return catalog["sleeves"][key]


def test_builder_covers_every_non_dedicated_lineage(tmp_path: Path) -> None:
    module = _module()
    outputs = module.build_all(tmp_path / "publication")
    assert len(outputs) == 15
    assert {path.parent.name for path in outputs} == {
        item["bundle_slug"]
        for item in _registry_items()
        if item["key"] not in module.DEDICATED_BUILDERS
    }


def test_abstract_limit_preserves_a_complete_sentence() -> None:
    module = _module()
    markdown = "## Abstract\n\n" + ("Complete sentence. " * 150)
    abstract = module._abstract(markdown)
    assert len(abstract) <= 2000
    assert abstract.endswith(".")
    assert not abstract.endswith("sentence")


def test_bundle_is_fail_closed_attributed_and_checksum_bound(tmp_path: Path) -> None:
    module = _module()
    item = next(item for item in _registry_items() if item["key"] == "crypto_momentum")
    out = module.build_one(item, _evidence(item["key"]), tmp_path / "publication")
    paper = json.loads((out / "paper.json").read_text())
    result_manifest = json.loads((out / "data_manifest.json").read_text())
    reproduction = json.loads((out / "reproduction.json").read_text())
    bundle = json.loads((out / "bundle_manifest.json").read_text())

    assert paper["authors"][0]["full_name"] == "Arhan Canli"
    assert paper["peer_reviewed"] is False
    assert paper["external_identifiers"] == []
    trial_accounting = json.loads((out / "trial_accounting.json").read_text())
    assert paper["result_release_complete"] is True
    assert result_manifest["released_result_objects"]
    assert all(
        row["byte_identical_to_source"] for row in result_manifest["released_result_objects"]
    )
    assert reproduction["result_reproduction_commands"]
    assert reproduction["result_reproduction_mapping_complete"] is True
    assert (
        reproduction["isolated_frozen_dependency_replay"]["dependency_environment"]
        == "UV_ISOLATED_FROZEN"
    )
    assert (
        reproduction["isolated_frozen_dependency_replay"][
            "portable_clean_workspace_replay_completed"
        ]
        is False
    )
    assert reproduction["clean_environment_reproduction_completed"] is False
    assert trial_accounting["complete_recorded_union_extracted"] is True
    assert trial_accounting["distinct_recorded_hypothesis_identities"] == 18
    assert bundle["external_submission_claimed"] is False
    assert bundle["remaining_blockers"] == item["submission_blockers"]

    checksums = {}
    for line in (out / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        checksums[name] = digest
    expected = {
        str(path.relative_to(out))
        for path in out.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    assert set(checksums) == expected
    for name, digest in checksums.items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest


def test_bundle_build_is_byte_deterministic(tmp_path: Path) -> None:
    module = _module()
    item = next(item for item in _registry_items() if item["key"] == "equity_quality")
    root = tmp_path / "publication"
    evidence = _evidence(item["key"])
    first_out = module.build_one(item, evidence, root)
    first = {
        str(path.relative_to(first_out)): path.read_bytes()
        for path in first_out.rglob("*")
        if path.is_file()
    }
    second_out = module.build_one(item, evidence, root)
    second = {
        str(path.relative_to(second_out)): path.read_bytes()
        for path in second_out.rglob("*")
        if path.is_file()
    }
    assert first == second


def test_crypto_carry_bundle_carries_the_open_material_correction(tmp_path: Path) -> None:
    module = _module()
    item = next(item for item in _registry_items() if item["key"] == "alphaforge_crypto_carry")
    out = module.build_one(item, _evidence(item["key"]), tmp_path / "publication")
    corrections = (out / "CORRECTIONS.md").read_text()
    assert "OPEN_MATERIAL_CORRECTION_EXTERNAL_SUBMISSION_BLOCKED" in corrections
    assert "current_state_replay_receipt.json" in corrections
    manifest = json.loads((out / "bundle_manifest.json").read_text())
    assert "OPEN_MATERIAL_REPLAY_CORRECTION" in manifest["remaining_blockers"]


def test_alphamax_bundle_carries_the_failed_fresh_vendor_replay(tmp_path: Path) -> None:
    module = _module()
    item = next(item for item in _registry_items() if item["key"] == "alphamax_equity_momentum")
    out = module.build_one(item, _evidence(item["key"]), tmp_path / "publication")
    manifest = json.loads((out / "data_manifest.json").read_text())
    released = {
        row["bundle_path"]: row for row in manifest["released_result_objects"]
    }

    assert "evidence/upstream_replay_manifest.json" in released
    assert "evidence/upstream_clean_workspace.json" in released
    receipt = json.loads((out / "evidence/upstream_clean_workspace.json").read_text())
    assert receipt["status"] == "FAIL_UPSTREAM_STRATEGY_REPLAY_FRESH_VENDOR_INPUTS_DIFFER"
    assert receipt["passes_strategy_reproduction"] is False
