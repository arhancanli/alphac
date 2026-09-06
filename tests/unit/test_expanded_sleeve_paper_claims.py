"""Bind key numeric claims in the expanded sleeve records to governed artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
MAIN_GLASSBOX = ROOT.parent / "meridian" / "public" / "glassbox"
APP_GLASSBOX = ROOT.parent / "meridian-app" / "public" / "glassbox"


def _json(relative: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((ROOT / relative).read_text()))


def _paper(relative: str) -> str:
    return (ROOT / relative).read_text()


def test_crypto_defensive_record_quotes_family_and_reopening_evidence() -> None:
    paper = _paper("docs/research/CRYPTO_DEFENSIVE_LINEAGE.md")
    family = _json("artifacts/research/crypto_defensive_family.json")
    reopening = _json("artifacts/analysis/lowvol720_reopen/result.json")

    for identity in family["identities"]:
        result = identity["result"]
        assert identity["hypothesis_key"] in paper
        assert f"{result['annualized_sharpe']:.4f}" in paper
        assert f"{result['skew']:.4f}" in paper
        assert f"{result['kurtosis']:.4f}" in paper
    assert f"{reopening['candidate_sharpe_reproduced']:.4f}" in paper
    assert f"{reopening['candidate_sharpe_published']:.4f}" in paper
    assert f"{reopening['gates']['K1_book_corr']['rho_at_chosen_lag']:.4f}" in paper
    assert f"{reopening['gates']['K4_contribution']['analytic']['contribution']:.4f}" in paper
    assert reopening["K5_venue_reality"].startswith("OUTSTANDING")
    assert "zero sleeves" in paper


def test_lowvol720_reopen_result_public_mirrors_match_governed_source() -> None:
    """Give the exported receipt a named guard, not only host-mirror coverage."""
    source = ROOT / "artifacts/analysis/lowvol720_reopen/result.json"
    export_name = "lowvol720_reopen_result.json"

    assert (MAIN_GLASSBOX / export_name).read_bytes() == source.read_bytes()
    assert (APP_GLASSBOX / export_name).read_bytes() == source.read_bytes()


def test_crypto_reversal_record_quotes_both_immutable_identities() -> None:
    paper = _paper("docs/research/CRYPTO_REVERSAL_LINEAGE.md")
    family = _json("artifacts/research/crypto_reversal_family.json")

    assert family["summary"]["distinct_hypothesis_identities"] == 2
    for identity in family["identities"]:
        result = identity["result"]
        assert identity["hypothesis_key"] in paper
        assert f"{result['annualized_sharpe']:.4f}" in paper
        assert f"{result['skew']:.4f}" in paper
        assert f"{result['kurtosis']:.4f}" in paper
        assert f"{result['observations']:,}" in paper
    assert "new, selected momentum hypothesis" in paper
    assert "zero sleeves" in paper


def test_energy_inventory_record_quotes_preregistered_probe() -> None:
    paper = _paper("docs/research/ENERGY_INVENTORY_LINEAGE.md")
    family = _json("artifacts/research/energy_inventory_family.json")
    probe = _json("artifacts/probe/eia_petroleum_inventory/result.json")
    metrics = probe["metrics"]

    assert f"{family['identities'][0]['result']['annualized_sharpe']:.4f}" in paper
    assert f"{metrics['net_sharpe']:.4f}" in paper
    assert f"{metrics['newey_west_t']:.4f}" in paper
    assert f"{abs(metrics['max_drawdown']) * 100:.2f}%" in paper
    assert f"{metrics['turnover_ann']:.2f}x" in paper
    assert f"{metrics['net_sharpe_at_2x_costs']:.4f}" in paper
    assert f"${metrics['capacity']['p05_usd_at_1pct_adv']:,.0f}" in paper
    assert probe["verdict"] == "KILL"
    assert "Five of thirteen" in paper


def test_insider_record_quotes_correction_and_current_snapshot_boundary() -> None:
    paper = _paper("docs/research/EQUITY_INSIDER_ACTIVITY_LINEAGE.md")
    family = _json("artifacts/research/equity_insider_family.json")
    probe = _json("artifacts/probe/insider_purchase_clusters/result.json")
    metrics = probe["metrics"]

    for identity in family["identities"]:
        result = identity["result"]
        assert identity["hypothesis_key"] in paper
        assert f"{result['annualized_sharpe']:.4f}" in paper
        assert f"{result['skew']:.4f}" in paper
        assert f"{result['kurtosis']:.4f}" in paper
    assert f"{metrics['net_sharpe']:.4f}" in paper
    assert f"{metrics['newey_west_t']:.4f}" in paper
    assert f"{abs(metrics['max_drawdown']) * 100:.2f}%" in paper
    assert f"{probe['book']['delta_sharpe']:.4f}" in paper
    assert probe["ledger_reconciliation"]["relation"] == "OOS_EXTENSION_NOT_EXACT_REPRODUCTION"
    assert "five additional observations" in paper


def test_equity_low_beta_record_quotes_both_summary_only_identities() -> None:
    paper = _paper("docs/research/EQUITY_LOW_BETA_LINEAGE.md")
    family = _json("artifacts/research/equity_low_beta_family.json")

    for identity in family["identities"]:
        result = identity["result"]
        assert identity["hypothesis_key"] in paper
        assert f"{result['annualized_sharpe']:.4f}" in paper
        assert f"{result['skew']:.4f}" in paper
        assert f"{result['kurtosis']:.4f}" in paper
        assert f"{result['observations']:,}" in paper
    assert "maximum drawdown" in paper
    assert "not established" in paper.lower()
    assert "zero sleeves" in paper
