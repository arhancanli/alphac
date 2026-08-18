"""Emit deterministic crowding-risk and stressed-capacity engineering evidence."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

from alphaforge.risk.crowding import (
    CrowdingObservation,
    CrowdingPolicy,
    assess_crowding,
)

REPO: Final[Path] = Path(__file__).resolve().parent.parent
SOURCE: Final[Path] = REPO / "src" / "alphaforge" / "risk" / "crowding.py"
PRETRADE: Final[Path] = REPO / "src" / "alphaforge" / "risk" / "pretrade.py"
TESTS: Final[Path] = REPO / "tests" / "unit" / "test_crowding.py"
PRETRADE_TESTS: Final[Path] = REPO / "tests" / "unit" / "test_pretrade.py"
OUTPUT: Final[Path] = REPO / "artifacts" / "engineering" / "crowding_risk_contract.json"
TS: Final[int] = 1_700_000_000_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy() -> CrowdingPolicy:
    return CrowdingPolicy(
        max_institutional_ownership_frac=0.85,
        max_short_interest_frac_float=0.25,
        max_borrow_utilization=0.90,
        max_absolute_fund_flow_frac_aum=0.10,
        daily_liquidation_participation=0.10,
        stressed_adv_haircut=0.50,
        max_stressed_liquidation_days=5.0,
    )


def observation(**changes: float | None) -> CrowdingObservation:
    values: dict[str, float | None] = {
        "institutional_ownership_frac": 0.50,
        "short_interest_frac_float": 0.10,
        "borrow_utilization": 0.50,
        "absolute_fund_flow_frac_aum": 0.02,
    }
    values.update(changes)
    return CrowdingObservation(
        instrument_id="XUSE:CASH:XYZUSD",
        observed_ts=TS,
        available_at=TS,
        valid_from=TS,
        valid_until=TS + 1,
        institutional_ownership_frac=values["institutional_ownership_frac"],
        short_interest_frac_float=values["short_interest_frac_float"],
        borrow_utilization=values["borrow_utilization"],
        absolute_fund_flow_frac_aum=values["absolute_fund_flow_frac_aum"],
    )


def scenario(name: str, row: CrowdingObservation, notional: float) -> dict[str, object]:
    result = assess_crowding(
        row,
        policy(),
        decision_ts=TS,
        resulting_signed_notional=notional,
        adv_quote=1_000_000.0,
    )
    return {
        "name": name,
        "status": result.status.value,
        "reasons": list(result.reasons),
        "liquidation_days": result.liquidation_days,
        "stressed_liquidation_days": result.stressed_liquidation_days,
    }


def build_contract() -> dict[str, object]:
    locked_policy = policy()
    payload: dict[str, object] = {
        "schema": "alphaforge.crowding-risk-contract.v1",
        "classification": "engineering capability; not return or admission evidence",
        "status": "PRETRADE_INTEGRATED_NO_HISTORICAL_COVERAGE",
        "trial_accounting": {
            "market_data_opened": False,
            "returns_evaluated": False,
            "hypotheses_spent": 0,
        },
        "policy": {
            "max_institutional_ownership_frac": locked_policy.max_institutional_ownership_frac,
            "max_short_interest_frac_float": locked_policy.max_short_interest_frac_float,
            "max_borrow_utilization": locked_policy.max_borrow_utilization,
            "max_absolute_fund_flow_frac_aum": (
                locked_policy.max_absolute_fund_flow_frac_aum
            ),
            "daily_liquidation_participation": locked_policy.daily_liquidation_participation,
            "stressed_adv_haircut": locked_policy.stressed_adv_haircut,
            "max_stressed_liquidation_days": locked_policy.max_stressed_liquidation_days,
        },
        "deterministic_stress_scenarios": [
            scenario("liquid_uncrowded_long", observation(), 10_000.0),
            scenario(
                "missing_required_flow",
                observation(absolute_fund_flow_frac_aum=None),
                10_000.0,
            ),
            scenario(
                "ownership_saturation",
                observation(institutional_ownership_frac=0.90),
                10_000.0,
            ),
            scenario(
                "short_squeeze",
                observation(short_interest_frac_float=0.30, borrow_utilization=0.95),
                -10_000.0,
            ),
            scenario("stressed_liquidation", observation(), 300_000.0),
        ],
        "implemented": [
            "PIT availability and validity for ownership, short-interest, borrow, and flow inputs",
            "coverage-aware unassessable verdict instead of imputation",
            "separate observable limit reasons without a blended crowding score",
            "base and ADV-haircut stressed liquidation days",
            "shared pre-trade rejection for new risk with reduce-only exemption",
        ],
        "not_implemented": [
            "historical institutional ownership point-in-time ingestion",
            "historical fund-flow ownership mapping to every traded security",
            "cross-manager factor-position overlap or prime-broker crowding data",
            "empirical calibration of thresholds to unwind losses",
            "portfolio-level correlated liquidation and market-depth feedback",
        ],
        "claim_boundary": (
            "The gate and stress arithmetic are implemented. Historical candidates remain "
            "unassessable until every required PIT input is supplied; this artifact is not a "
            "claim that current or historical portfolios passed the crowding gate."
        ),
        "source_sha256": {
            "crowding": sha256(SOURCE),
            "pretrade": sha256(PRETRADE),
            "crowding_tests": sha256(TESTS),
            "pretrade_tests": sha256(PRETRADE_TESTS),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return payload


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_contract(), indent=2) + "\n")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
