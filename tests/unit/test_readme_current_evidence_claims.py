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
    # Mirror scripts/sync_readme_forward_evidence.py _percentage: the sign comes from
    # the value, rendered with the typographic minus. The previous form prefixed a
    # minus unconditionally and could only pass while the forward record was negative.
    cumulative = f"{record['cumulative_return']:.5%}".replace("-", chr(0x2212))

    assert f"**Evidence snapshot:** {evidence['generated_at'][:10]}." in readme
    returns = record["daily_return_observations"]
    assert f"**{returns} daily return{'' if returns == 1 else 's'}**" in readme
    assert f"**{cumulative}**" in readme
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
    sharpe = evidence["sharpe_evidence"]
    if sharpe.get("annualized_point_estimate") is None:
        assert "Forward Sharpe | **Not reportable**" in readme
    target = f"{float(sharpe['target']):.4f}".rstrip("0")
    target = target + "0" if target.endswith(".") else target
    assert f"the governing forward target is **{target}**" in readme
    bound = float(drawdown["realized_max_drawdown_bound"])
    assert f"against the owner's realized bound of **{bound:.0%}**" in readme
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
