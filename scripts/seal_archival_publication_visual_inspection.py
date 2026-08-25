#!/usr/bin/env python3
"""Seal the completed, non-independent visual inspection of archival PDFs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
GLOBAL_RECEIPT: Final = ROOT / "artifacts/audit/archival_publication_visual_inspection.json"
PRIOR_RECEIPT: Final = (
    ROOT / "artifacts/audit/archive/archival_publication_visual_inspection_2026-08-24.json"
)
RECEIPT_NAME: Final = "archival_visual_inspection_receipt.json"
EXPECTED_PAPERS: Final = 16
EXPECTED_PAGES: Final = 80
REINSPECTED_KEYS: Final = frozenset(
    {
        "alphavintage_macro_surprise",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _ro_crate(out: Path, title: str, version: str) -> dict[str, Any]:
    files = sorted(
        str(path.relative_to(out))
        for path in out.rglob("*")
        if path.is_file() and path.name not in {"ro-crate-metadata.json", "SHA256SUMS"}
    )
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": title,
            "version": version,
            "datePublished": "2026-08-23",
            "author": {"@id": "#arhan-canli"},
            "hasPart": [{"@id": name} for name in files],
        },
        {"@id": "#arhan-canli", "@type": "Person", "name": "Arhan Canli"},
    ]
    graph.extend({"@id": name, "@type": "File", "sha256": _sha256(out / name)} for name in files)
    return {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}


def _rewrite_checksums(out: Path) -> None:
    files = sorted(path for path in out.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(out)}\n" for path in files)
    )


def _refresh_readme(out: Path, key: str) -> None:
    readme = out / "README.md"
    text = readme.read_text()
    if key == "alphavintage_macro_surprise":
        old_values: tuple[str, ...] = (
            (
                "Remaining release blockers: archival PDF inspection, LaTeX source, data-licence "
                "resolution, clean-\nenvironment replay, and independent human reproduction. "
                "`SHA256SUMS` binds every released file."
            ),
            (
                "Remaining release blockers: data-licence resolution, full-pipeline\n"
                "clean-environment replay including diversification, and independent human "
                "reproduction. The\npublication-rendering stage adds inspected PDF/HTML/LaTeX "
                "assets;\n`SHA256SUMS` binds every released file."
            ),
            (
                "Remaining release blockers: data-licence resolution, full multi-sleeve\n"
                "end-to-end replay, and independent human reproduction. The publication-"
                "rendering stage adds\ninspected PDF/HTML/LaTeX assets;\n`SHA256SUMS` binds every "
                "released file."
            ),
            (
                "Remaining release blockers: data-licence resolution, the other two\nupstream "
                "reconstructions, full multi-sleeve end-to-end replay, and independent human "
                "reproduction.\nThe publication-rendering stage adds\ninspected PDF/HTML/LaTeX "
                "assets;\n`SHA256SUMS` binds every released file."
            ),
            (
                "Remaining\nrelease blockers: data-licence\nresolution, the other two upstream "
                "reconstructions, full multi-sleeve end-to-end replay, and\nindependent human "
                "reproduction.\nThe publication-rendering stage adds\ninspected PDF/HTML/LaTeX "
                "assets;\n`SHA256SUMS` binds every released file."
            ),
            (
                "Remaining release blockers include data-licence resolution, exact AlphaMax\n"
                "historical-input recovery, full multi-sleeve end-to-end reproduction, and "
                "independent human\nreproduction.\nThe publication-rendering stage adds\n"
                "inspected PDF/HTML/LaTeX assets;\n`SHA256SUMS` binds every released file."
            ),
        )
        new = (
            "Remaining release blockers: data-licence resolution, exact AlphaMax historical-"
            "input recovery, full multi-sleeve end-to-end reproduction, and independent human "
            "reproduction. The bundle includes internally inspected archival PDF/HTML/LaTeX "
            "assets; `SHA256SUMS` binds every released file."
        )
    else:
        new = (
            "and inventory, clean replay, and independent human replication remain unresolved. "
            "The bundle includes a normalized bibliography and internally inspected archival "
            "PDF/HTML/LaTeX assets."
        )
        old_values = (
            (
                "and inventory, bibliography normalization, clean replay, and independent human "
                "replication remain unresolved. Archival PDF/HTML/LaTeX assets and their separate "
                "inspection receipt are added by the publication-rendering stage."
            ),
            (
                "and inventory, clean replay, and independent human replication remain unresolved. "
                "Normalized bibliography and archival PDF/HTML/LaTeX assets, with their separate "
                "inspection receipt, are added by the publication-rendering stages."
            ),
            (
                "and inventory, archival PDF and LaTeX, clean replay, and independent human "
                "replication remain unresolved."
            ),
        )
        if new in text:
            return
        for old in old_values:
            if old in text:
                readme.write_text(text.replace(old, new))
                return
        raise RuntimeError(f"README archival-state text was not recognized for {key}")
    if new in text:
        return
    for old in old_values:
        if old in text:
            readme.write_text(text.replace(old, new))
            return
    raise RuntimeError(f"README archival-state text was not recognized for {key}")


def main() -> int:
    registry = json.loads(REGISTRY.read_text())
    if not PRIOR_RECEIPT.is_file():
        if not GLOBAL_RECEIPT.is_file():
            raise RuntimeError("prior visual-inspection receipt is unavailable")
        PRIOR_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        PRIOR_RECEIPT.write_bytes(GLOBAL_RECEIPT.read_bytes())
    prior_receipt = json.loads(PRIOR_RECEIPT.read_text())
    if prior_receipt.get("content_hash") != _content_hash(prior_receipt):
        raise RuntimeError("prior visual-inspection receipt content hash is invalid")
    prior_records = {record["registry_key"]: record for record in prior_receipt.get("papers", [])}

    records: list[dict[str, Any]] = []
    for item in registry["sleeves"]:
        manifest_path = ROOT / item["bundle_manifest"]
        out = manifest_path.parent
        manifest = json.loads(manifest_path.read_text())
        validation_path = out / "pdf_validation.json"
        validation = json.loads(validation_path.read_text())
        pdf = out / "paper.pdf"
        html = out / "paper.html"
        latex = out / "paper.tex"
        if (
            not validation.get("passes")
            or validation.get("status") != "PASS_MACHINE_PDF_VALIDATION"
        ):
            raise RuntimeError(f"machine validation is not green for {item['key']}")
        if manifest.get("archival_assets", {}).get("pdf", {}).get("sha256") != _sha256(pdf):
            raise RuntimeError(f"manifest PDF hash mismatch for {item['key']}")
        if not html.is_file() or not latex.is_file():
            raise RuntimeError(f"missing archival source for {item['key']}")
        pdf_sha = _sha256(pdf)
        validation_sha = _sha256(validation_path)
        prior: dict[str, Any] | None = None
        if item["key"] in REINSPECTED_KEYS:
            inspection_basis = "REINSPECTED_CURRENT_PDF_2026_08_25"
        else:
            prior = prior_records.get(item["key"])
            if (
                prior is None
                or prior.get("result") != "PASS_INTERNAL_VISUAL_INSPECTION"
                or prior.get("pdf_sha256") != pdf_sha
                or prior.get("pages_inspected") != validation["pages"]
            ):
                raise RuntimeError(f"unchanged-paper carry-forward is not proved for {item['key']}")
            inspection_basis = "CARRIED_FORWARD_BYTE_IDENTICAL_PDF_FROM_PRIOR_RECEIPT"
        record = {
            "registry_key": item["key"],
            "bundle": str(out.relative_to(ROOT)),
            "pages_inspected": validation["pages"],
            "pdf_sha256": pdf_sha,
            "pdf_validation_sha256": validation_sha,
            "inspection_basis": inspection_basis,
            "result": "PASS_INTERNAL_VISUAL_INSPECTION",
        }
        if item["key"] not in REINSPECTED_KEYS:
            assert prior is not None
            record["prior_pdf_validation_sha256"] = prior["pdf_validation_sha256"]
        records.append(record)

    total_pages = sum(record["pages_inspected"] for record in records)
    if len(records) != EXPECTED_PAPERS or total_pages != EXPECTED_PAGES:
        raise RuntimeError(
            f"inspection population mismatch: {len(records)} papers / {total_pages} pages"
        )
    reinspected_pages = sum(
        record["pages_inspected"]
        for record in records
        if record["registry_key"] in REINSPECTED_KEYS
    )
    carried_forward_pages = total_pages - reinspected_pages

    receipt = {
        "schema": "canli.alphac-archival-pdf-visual-inspection.v2",
        "status": "PASS_INTERNAL_VISUAL_INSPECTION_NOT_INDEPENDENT_REVIEW",
        "inspection_date": "2026-08-25",
        "author_and_project_lead": "Arhan Canli",
        "performed_by": "OpenAI Codex-assisted internal publication QA",
        "papers_inspected": len(records),
        "pages_inspected": total_pages,
        "pages_reinspected_in_this_revision": reinspected_pages,
        "pages_carried_forward_unchanged": carried_forward_pages,
        "prior_receipt": {
            "path": str(PRIOR_RECEIPT.relative_to(ROOT)),
            "sha256": _sha256(PRIOR_RECEIPT),
            "content_hash": prior_receipt["content_hash"],
        },
        "method": (
            "The revised eight-page AlphaVintage PDF was rasterized with Apple PDFKit and every "
            "page was examined in order after its source-evidence correction. The other 15 PDFs "
            "are carried forward only because their PDF bytes and page counts exactly match the "
            "prior receipt. Every current PDF independently passes machine validation."
        ),
        "checks": {
            "cover_title_and_metadata_overflow": "PASS",
            "author_attribution": "PASS",
            "claim_boundary_and_not_peer_reviewed_disclosure": "PASS",
            "body_text_clipping_or_overlap": "PASS",
            "tables_and_code_blocks": "PASS",
            "blank_or_near_blank_pages": "PASS",
            "last_page_truncation": "PASS",
            "consistent_a4_visual_system": "PASS",
        },
        "papers": records,
        "claim_boundary": (
            "This is internal presentation QA, not peer review, editorial acceptance, content "
            "validation, accessibility certification, independent replication, or proof that "
            "any strategy result is economically valid."
        ),
    }
    receipt["content_hash"] = _content_hash(receipt)
    _write_json(GLOBAL_RECEIPT, receipt)
    receipt_sha = _sha256(GLOBAL_RECEIPT)

    for item in registry["sleeves"]:
        manifest_path = ROOT / item["bundle_manifest"]
        out = manifest_path.parent
        local_receipt = out / RECEIPT_NAME
        local_receipt.write_bytes(GLOBAL_RECEIPT.read_bytes())
        _refresh_readme(out, item["key"])
        manifest = json.loads(manifest_path.read_text())
        manifest["remaining_blockers"] = item["submission_blockers"]
        manifest["archival_assets"]["pdf"]["visual_inspection"] = {
            "status": "PASS_INTERNAL_VISUAL_INSPECTION_NOT_INDEPENDENT_REVIEW",
            "path": RECEIPT_NAME,
            "sha256": receipt_sha,
        }
        _write_json(manifest_path, manifest)
        metadata = json.loads((out / "paper.json").read_text())
        _write_json(
            out / "ro-crate-metadata.json",
            _ro_crate(out, str(metadata["title"]), str(metadata["version"])),
        )
        _rewrite_checksums(out)

    print(
        f"sealed internal visual inspection for {len(records)} papers / {total_pages} pages; "
        f"receipt sha256:{receipt_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
