from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_headlines_match_the_dated_forward_evidence_artifact() -> None:
    readme = (ROOT / "README.md").read_text()
    evidence = json.loads(
        (ROOT / "artifacts" / "engineering" / "forward_evidence_maturity.json").read_text()
    )
    record = evidence["record"]
    drawdown = evidence["drawdown_evidence"]
    diversification = evidence["diversification_evidence"]
    minus_sign = chr(0x2212)

    assert f"**Evidence snapshot:** {evidence['generated_at'][:10]}." in readme
    assert f"**{record['daily_return_observations']} daily returns**" in readme
    assert f"**{minus_sign}{abs(record['cumulative_return']):.5%}**" in readme
    assert f"**{drawdown['realized_live_max_drawdown']:.5%}**" in readme
    assert (
        f"**{drawdown['current_composition_conservative_expected_max_drawdown']:.3%} expected / "
        f"{drawdown['current_composition_conservative_p95_max_drawdown']:.3%} p95**" in readme
    )
    assert f"**{diversification['average_pairwise_correlation']:+.5f}**" in readme
    assert (
        f"**{diversification['current_sleeves']} / "
        f"{diversification['target_total_sleeves']} planned**" in readme
    )
    assert "Forward Sharpe | **Not reportable**" in readme
    assert "Honest forward Sharpe" not in readme
    assert "Deflated Sharpe (gate 0.95)" not in readme


def test_readme_trial_count_separates_legacy_and_prospective_epochs() -> None:
    readme = (ROOT / "README.md").read_text()
    policy = json.loads((ROOT / "config" / "trial_accounting.json").read_text())
    closure = json.loads(
        (
            ROOT / "artifacts" / "research" / "crypto_carry_portable_v1_admission_closure.json"
        ).read_text()
    )
    legacy = policy["observed_hypothesis_identities"]
    prospective_ordinal = closure["identity"]["reservation_ordinal"]

    assert prospective_ordinal == legacy + 1
    assert f"**{prospective_ordinal} total identities**" in readme
    assert f"{legacy} retired legacy" in readme
    assert f"**{policy['hypothesis_identity_budget']}-identity ceiling**" in readme
