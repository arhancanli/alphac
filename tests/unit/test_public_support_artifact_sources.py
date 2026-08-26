"""Public support artifacts must remain byte-identical to their authoritative sources."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "research_export_public_support_test", REPO / "scripts/research_export.py"
)
assert _SPEC is not None and _SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = EXPORT
_SPEC.loader.exec_module(EXPORT)

FAMILY_SOURCES = {name: source for name, source, _, _ in EXPORT.FINAL_FAMILY_FILES}

SOURCES = {
    "alphamax_construction_arms.json": EXPORT.ALPHAMAX_CONSTRUCTION_ARMS_JSON,
    "active_ownership_human_gate_audit.json": (
        EXPORT.ACTIVE_OWNERSHIP_HUMAN_GATE_AUDIT_JSON
    ),
    "alphavintage_corrected_result.json": EXPORT.ALPHAVINTAGE_RESULT_JSON,
    "crypto_carry_2022_tail.json": EXPORT.CRYPTO_CARRY_2022_TAIL_JSON,
    "crypto_carry_grand_matrix.json": EXPORT.CRYPTO_CARRY_GRAND_MATRIX_JSON,
    "crypto_carry_selected_walkforward.json": EXPORT.CRYPTO_CARRY_SELECTED_WALKFORWARD_JSON,
    "crypto_defensive_family.json": FAMILY_SOURCES["crypto_defensive_family.json"],
    "crypto_reversal_family.json": FAMILY_SOURCES["crypto_reversal_family.json"],
    "earnings_narrative_change_result.json": EXPORT.NARRATIVE_PROBE_DIR / "result.json",
    "eia_petroleum_inventory_result.json": EXPORT.EIA_PROBE_DIR / "result.json",
    "energy_inventory_family.json": FAMILY_SOURCES["energy_inventory_family.json"],
    "external_publication_readiness.json": EXPORT.EXTERNAL_PUBLICATION_READINESS_JSON,
    "publication_clean_checkout_integrity.json": (
        EXPORT.PUBLICATION_CLEAN_CHECKOUT_INTEGRITY_JSON
    ),
    "archival_publication_visual_inspection.json": (
        EXPORT.ARCHIVAL_PUBLICATION_VISUAL_INSPECTION_JSON
    ),
    "external_publication_registry.json": EXPORT.EXTERNAL_PUBLICATION_REGISTRY_JSON,
    "sleeve_publication_evidence.json": EXPORT.SLEEVE_PUBLICATION_EVIDENCE_JSON,
    "sleeve_publication_replay_verification.json": EXPORT.SLEEVE_PUBLICATION_REPLAY_JSON,
    "sleeve_publication_isolated_replay_verification.json": (
        EXPORT.SLEEVE_PUBLICATION_ISOLATED_REPLAY_JSON
    ),
    "equity_insider_family.json": FAMILY_SOURCES["equity_insider_family.json"],
    "equity_low_beta_family.json": FAMILY_SOURCES["equity_low_beta_family.json"],
    "equity_quality_family.json": EXPORT.EQUITY_QUALITY_FAMILY_JSON,
    "equity_value_investment_family.json": EXPORT.EQUITY_VALUE_FAMILY_JSON,
    "insider_purchase_clusters_result.json": EXPORT.INSIDER_PROBE_DIR / "result.json",
    "macro_economic_trend_family.json": FAMILY_SOURCES["macro_economic_trend_family.json"],
    "pre_fomc_announcement_drift_feasibility.json": EXPORT.PRE_FOMC_FEASIBILITY_RESULT,
    "spin_off_document_schema.json": EXPORT.SPIN_OFF_DOCUMENT_RESULT,
    "spin_off_lineage.json": EXPORT.SPIN_OFF_LINEAGE_RESULT,
    "treasury_auction_concession_feasibility.json": EXPORT.TREASURY_FEASIBILITY_RESULT,
    "treasury_calendar_revision_audit.json": EXPORT.TREASURY_CALENDAR_REVISION_RESULT,
    "treasury_wayback_pdf_schedule_audit.json": EXPORT.TREASURY_WAYBACK_PDF_SCHEDULE_RESULT,
    "treasury_wayback_schedule_audit.json": EXPORT.TREASURY_WAYBACK_SCHEDULE_RESULT,
}


@pytest.mark.workspace_evidence
@pytest.mark.parametrize(("public_name", "source"), sorted(SOURCES.items()))
def test_public_support_artifact_matches_source(public_name: str, source: Path) -> None:
    primary = REPO.parent / "meridian" / "public" / "glassbox" / public_name
    app = REPO.parent / "meridian-app" / "public" / "glassbox" / public_name

    assert source.read_bytes() == primary.read_bytes() == app.read_bytes()
