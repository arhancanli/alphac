from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "external_publication_registry.json"
VISUAL_RECEIPT = ROOT / "artifacts" / "audit" / "archival_publication_visual_inspection.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(document: dict) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def test_all_archival_papers_are_hash_bound_machine_validated_and_visually_inspected() -> None:
    sleeves = json.loads(REGISTRY.read_text())["sleeves"]
    receipt = json.loads(VISUAL_RECEIPT.read_text())
    records = {record["registry_key"]: record for record in receipt["papers"]}

    assert receipt["content_hash"] == _content_hash(receipt)
    assert receipt["status"] == "PASS_INTERNAL_VISUAL_INSPECTION_NOT_INDEPENDENT_REVIEW"
    assert receipt["author_and_project_lead"] == "Arhan Canli"
    assert receipt["papers_inspected"] == len(sleeves) == 16
    assert receipt["pages_inspected"] == 80
    assert receipt["pages_reinspected_in_this_revision"] == 8
    assert receipt["pages_carried_forward_unchanged"] == 72
    assert set(records) == {item["key"] for item in sleeves}

    for item in sleeves:
        bundle_dir = (ROOT / item["bundle_manifest"]).parent
        manifest = json.loads((bundle_dir / "bundle_manifest.json").read_text())
        validation = json.loads((bundle_dir / "pdf_validation.json").read_text())
        pdf = bundle_dir / "paper.pdf"
        record = records[item["key"]]

        assert validation["passes"] is True
        assert validation["status"] == "PASS_MACHINE_PDF_VALIDATION"
        assert validation["registry_key"] == item["key"]
        assert validation["render_environment"]["latex_compilation_validated"] is False
        assert validation["source_bindings"]["bibliography"]["references.bib"]["sha256"] == _sha256(
            bundle_dir / "references.bib"
        )
        assert validation["source_bindings"]["paper_markdown"]["sha256"] == _sha256(
            bundle_dir / "paper.md"
        )
        assert validation["source_bindings"]["static_site_paper_html"][
            "declared_markdown_sha256"
        ] == _sha256(bundle_dir / "paper.md")
        assert validation["source_bindings"]["static_site_paper_html"][
            "matches_paper_markdown"
        ] is True
        assert manifest["archival_assets"]["pdf"]["sha256"] == _sha256(pdf)
        assert record["pdf_sha256"] == _sha256(pdf)
        assert record["pdf_validation_sha256"] == _sha256(bundle_dir / "pdf_validation.json")
        assert record["pages_inspected"] == validation["pages"]
        expected_basis = (
            "REINSPECTED_CURRENT_PDF_2026_08_25"
            if item["key"] == "alphavintage_macro_surprise"
            else "CARRIED_FORWARD_BYTE_IDENTICAL_PDF_FROM_PRIOR_RECEIPT"
        )
        assert record["inspection_basis"] == expected_basis
        assert (bundle_dir / "archival_visual_inspection_receipt.json").read_bytes() == (
            VISUAL_RECEIPT.read_bytes()
        )

        reader = PdfReader(pdf)
        assert len(reader.pages) == validation["pages"]
        assert reader.metadata.title == item["title"]
        assert reader.metadata.author == "Arhan Canli"
        assert "Arhan Canli" in "\n".join(page.extract_text() or "" for page in reader.pages)


def test_latex_and_html_sources_are_present_without_overstating_latex_compilation() -> None:
    sleeves = json.loads(REGISTRY.read_text())["sleeves"]
    for item in sleeves:
        bundle_dir = (ROOT / item["bundle_manifest"]).parent
        latex = (bundle_dir / "paper.tex").read_text()
        html = (bundle_dir / "paper.html").read_text()

        assert "\\markdownInput{paper.md}" in latex
        assert "not peer reviewed" in latex.lower()
        assert "Arhan Canli" in html
        assert "not peer reviewed" in html.lower()
        assert "References" in html
