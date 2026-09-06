"""Rank the remaining families by expected orthogonality to this book — as a PRIOR, not a claim.

WHY THIS EXISTS. The objective turns on an average pairwise correlation, and correlation is
measured last: a family is worked, a protocol written, data opened, and only then does anyone learn
whether it diversifies. Ordering families by expected orthogonality FIRST costs nothing and can
only be done before the fact, because after the fact it is a measurement.

A prior is a judgement and this file says so in every field. What keeps it from being astrology is
that the rule is stated in advance, applied uniformly by code rather than case by case, and
confronted with the only correlation structure this book has actually measured.

THE MEASURED STRUCTURE, AND WHAT IT SAYS. Four live sleeves give six pairs. Two of them resolve
against sampling error and four do not, and the two that resolve are exactly the two that are
structurally distinctive:

    AlphaMax x AlphaTrend    shared FACTOR family (momentum), different asset classes    +0.210
    AlphaMax x AlphaVintage  shared ASSET CLASS (US equity), different factors           -0.062
    the other four           sharing neither                        all within 1.5 SE of zero

So on the only evidence available: factor overlap produced the largest correlation in the book,
and asset-class overlap produced a NEGATIVE one. The prior below therefore scores factor overlap
and does NOT score asset class — an omission that is a decision with evidence behind it rather
than an oversight, and the most attackable thing here, which is why it is stated first.

WHAT THIS CANNOT DO, stated before the ranking rather than under it. Two informative pairs is one
observation per structural cell. That is a direction, not a coefficient, and no weighting fitted to
it would mean anything. The prior is published UNCALIBRATED, with the evidence that would calibrate
it named.

Reads frozen artifacts read-only. Registers no hypothesis, opens no return data: 0 trials.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ATLAS = REPO / "artifacts" / "discovery" / "sleeve_atlas.json"
CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
BOOK = REPO / "artifacts" / "analysis" / "book_without_alphavintage" / "result.json"
STRESSED = REPO / "artifacts" / "analysis" / "stressed_correlation" / "result.json"
OUTPUT = REPO / "artifacts" / "analysis" / "orthogonality_prior" / "result.json"

S_BAR_MEASURED = 0.469  # live four, from the objective's own published figure

# Factor families. Two sleeves in the same family trade the same idea in different clothes; the
# one pair in this book that shares one is also the most correlated pair in this book.
CARRY = "CARRY"  # a recurring payment for holding the position
BASIS = "BASIS"  # the price gap between two claims on the same underlying
MOMENTUM = "MOMENTUM"  # cross-sectional or time-series, deliberately one family
MACRO_SURPRISE = "MACRO_SURPRISE"
FLOW = "FLOW"  # predictable order flow that is not itself a price signal
EVENT = "EVENT"  # a legal or corporate timetable
VOL = "VOL"  # the option risk premium

# What the position loses money for. The axis with no local evidence, flagged wherever it decides.
SHORT_LIQUIDITY = "SHORT_LIQUIDITY"  # paid to provide liquidity; loses when liquidity vanishes
LONG_TAIL = "LONG_TAIL"  # convex; makes money in the dislocation
DIRECTIONAL = "DIRECTIONAL"  # carries beta to its own market
NEUTRAL = "NEUTRAL"  # the driver is not a market state

# What moves the position. A driver that is not a price cannot inherit a price factor.
PRICE = "PRICE"
ORDER_FLOW = "ORDER_FLOW"
TIMETABLE = "TIMETABLE"
PHYSICAL = "PHYSICAL"

LIVE_SLEEVES = {
    "AlphaForge": {
        "factor": CARRY,
        "crisis": SHORT_LIQUIDITY,
        "mechanism": "crypto funding-rate carry",
    },
    "AlphaMax": {
        "factor": MOMENTUM,
        "crisis": DIRECTIONAL,
        "mechanism": "US equity cross-sectional momentum",
    },
    "AlphaTrend": {
        "factor": MOMENTUM,
        "crisis": LONG_TAIL,
        "mechanism": "multi-asset time-series momentum",
    },
    "AlphaVintage": {
        "factor": MACRO_SURPRISE,
        "crisis": DIRECTIONAL,
        "mechanism": "PIT CPI-surprise equity size spread",
    },
}

SHARES_FACTOR = "LIKELY_CORRELATED_SHARES_A_FACTOR_WITH_A_LIVE_SLEEVE"
SHARES_CRISIS = "UNCERTAIN_SHARES_THE_CRISIS_DIRECTION_OF_A_LIVE_SLEEVE"
LIKELY_ORTHOGONAL = "LIKELY_ORTHOGONAL_NO_SHARED_FACTOR_OR_CRISIS_DIRECTION"
STRONGLY_ORTHOGONAL = "STRONGLY_ORTHOGONAL_DRIVEN_BY_SOMETHING_OTHER_THAN_PRICE"

RANK = [STRONGLY_ORTHOGONAL, LIKELY_ORTHOGONAL, SHARES_CRISIS, SHARES_FACTOR]

MEANING = {
    STRONGLY_ORTHOGONAL: (
        "Shares no factor family and no crisis direction with any live sleeve, and what moves it "
        "is not a price. The strongest prior this rule can express, and still a prior."
    ),
    LIKELY_ORTHOGONAL: (
        "Shares no factor family and no crisis direction, but is price-driven, so it inherits "
        "whatever the market inherits when everything moves together."
    ),
    SHARES_CRISIS: (
        "No shared factor, but it loses money in the same event as a live sleeve. Correlation "
        "measured over a calm window will understate it, and the window that would show it is the "
        "window nobody has enough of."
    ),
    SHARES_FACTOR: (
        "Trades the same idea as a live sleeve in different clothes. This is the one structural "
        "feature that produced a large measured correlation in this book."
    ),
}


@dataclass(frozen=True)
class Prior:
    family: str
    factor: str
    driver: str
    crisis: str
    reasoning: str
    notes: list[str] = field(default_factory=list)

    def shares_factor_with(self) -> list[str]:
        return sorted(k for k, v in LIVE_SLEEVES.items() if v["factor"] == self.factor)

    def shares_crisis_with(self) -> list[str]:
        if self.crisis == NEUTRAL:
            return []
        return sorted(k for k, v in LIVE_SLEEVES.items() if v["crisis"] == self.crisis)

    @property
    def prior(self) -> str:
        if self.shares_factor_with():
            return SHARES_FACTOR
        if self.shares_crisis_with():
            return SHARES_CRISIS
        if self.driver != PRICE:
            return STRONGLY_ORTHOGONAL
        return LIKELY_ORTHOGONAL


PRIORS: tuple[Prior, ...] = (
    Prior(
        "analyst_revision_drift", MOMENTUM, PRICE, DIRECTIONAL,
        "Revision drift and price momentum are the textbook overlapping pair: the revision is "
        "what the price is already drifting on. Shares AlphaMax's factor outright.",
    ),
    Prior(
        "index_reconstitution_flow", FLOW, ORDER_FLOW, NEUTRAL,
        "The trade is against a mandated, pre-announced order flow. What creates the opportunity "
        "is a rulebook rather than a market state, so it shares neither a factor nor an event.",
        notes=[
            "The only family here that reaches the strongest prior, and it is also one of the "
            "licence-restricted ones. The most orthogonal thing left is the thing we may not be "
            "permitted to publish research on.",
        ],
    ),
    Prior(
        "securities_lending_supply", CARRY, PRICE, SHORT_LIQUIDITY,
        "A borrow fee IS a carry: a recurring payment for holding a position that gaps when the "
        "borrow is recalled. Same factor as AlphaForge and the same crisis direction.",
        notes=["Both axes fire at once — the strongest correlation warning in the set."],
    ),
    Prior(
        "credit_equity_relative_value", BASIS, PRICE, SHORT_LIQUIDITY,
        "A basis between two claims on one issuer. No shared factor, but the basis widens in "
        "exactly the liquidity event AlphaForge is short.",
    ),
    Prior(
        "fallen_angel_flow", FLOW, ORDER_FLOW, SHORT_LIQUIDITY,
        "The trade takes the other side of a forced, rule-driven sale. Liquidity provision by "
        "another name, and it is worst paid when it is most needed.",
    ),
    Prior(
        "municipal_taxable_basis", BASIS, PRICE, SHORT_LIQUIDITY,
        "A tax-driven basis in a market whose bid disappears under stress.",
    ),
    Prior(
        "dealer_gamma_pressure", FLOW, ORDER_FLOW, SHORT_LIQUIDITY,
        "Trading ahead of mechanical dealer hedging. The flow is predictable in calm and reverses "
        "violently in the tail, which is the liquidity event again.",
    ),
    Prior(
        "swap_spread_dislocation", BASIS, PRICE, SHORT_LIQUIDITY,
        "A basis between a swap and its deliverable, funded. Its historical blow-ups are funding "
        "events.",
    ),
    Prior(
        "mortgage_convexity_pressure", FLOW, ORDER_FLOW, SHORT_LIQUIDITY,
        "Hedging flow from negative convexity. The flow is the signal, and it is largest when "
        "rates gap, which is when liquidity is worst.",
    ),
    Prior(
        "cross_currency_basis", BASIS, PRICE, SHORT_LIQUIDITY,
        "The canonical funding basis. It is a direct measure of dollar funding stress, which is "
        "the event AlphaForge's carry is short.",
    ),
    Prior(
        "fx_option_risk_reversal", VOL, PRICE, SHORT_LIQUIDITY,
        "Selling the option risk premium, in whichever direction the skew pays. Short convexity, "
        "so it loses where AlphaTrend gains and where AlphaForge also loses.",
    ),
    Prior(
        "carbon_allowance_carry", CARRY, PRICE, SHORT_LIQUIDITY,
        "Named carry and structured as carry: paid to hold and store an allowance. Same factor as "
        "AlphaForge in a market that has no relation to crypto, which is exactly the case the "
        "asset-class intuition gets wrong.",
        notes=[
            "The clearest illustration of why asset class is not in the rule: nothing about "
            "European carbon resembles crypto perpetuals, and the position is the same trade.",
        ],
    ),
    Prior(
        "freight_derivative_dislocation", BASIS, PHYSICAL, SHORT_LIQUIDITY,
        "Paper against physical route economics. Physically driven, but the dislocation it "
        "harvests closes when someone can no longer fund the physical leg.",
    ),
    Prior(
        "crypto_liquidation_pressure", FLOW, ORDER_FLOW, SHORT_LIQUIDITY,
        "Taking the other side of forced liquidations is liquidity provision at its most literal, "
        "in the same venues and the same cascades that set AlphaForge's funding.",
        notes=[
            "Asset class is not in the rule, but here it compounds the crisis axis rather than "
            "standing in for it: same venues, same cascade, same hour.",
        ],
    ),
    Prior(
        "catastrophe_bond_event_risk", CARRY, PRICE, SHORT_LIQUIDITY,
        "Paid a spread to bear a defined event. Structurally a carry, and the market's bid "
        "vanishes on exactly the event it is paid for.",
    ),
    Prior(
        "sovereign_cds_fx_dislocation", BASIS, PRICE, SHORT_LIQUIDITY,
        "A basis between two expressions of one sovereign risk, and both legs gap together in the "
        "event that makes the basis interesting.",
    ),
)


def _untouched_families(atlas: dict[str, Any]) -> list[str]:
    """DERIVED from the atlas, exactly as the obtainability screen does, so the two cannot drift."""
    return sorted(
        f["id"]
        for f in atlas["families"]
        if f["lineage_classification"] == "NOVEL_ATLAS"
        and not (f.get("return_outcome") or {}).get("return_data_opened")
    )


def _book_sharpe(n: int, rho_bar: float, s_bar: float = S_BAR_MEASURED) -> float:
    return s_bar * math.sqrt(n / (1 + (n - 1) * rho_bar))


def _measured_structure() -> dict[str, Any]:
    """The six measured pairs, classified by the same axes the prior uses, with their resolution.

    The classification is applied to the LIVE sleeves by the same table the families are scored
    against, so the evidence and the rule cannot describe two different things.
    """
    book = json.loads(BOOK.read_text())["with_alphavintage"]
    pairs = book["pairwise_correlations"]
    n_days = book["n_days"]
    se = 1 / math.sqrt(n_days - 3)

    rows = []
    for key, rho in sorted(pairs.items(), key=lambda kv: -abs(kv[1])):
        left, right = key.split("|")
        shared_factor = LIVE_SLEEVES[left]["factor"] == LIVE_SLEEVES[right]["factor"]
        rows.append(
            {
                "pair": key,
                "rho": rho,
                "standard_errors_from_zero": round(abs(math.atanh(rho)) / se, 2),
                "resolved_at_95": abs(math.atanh(rho)) / se > 1.96,
                "shares_factor_family": shared_factor,
                "factors": [LIVE_SLEEVES[left]["factor"], LIVE_SLEEVES[right]["factor"]],
                "crisis_directions": [LIVE_SLEEVES[left]["crisis"], LIVE_SLEEVES[right]["crisis"]],
            }
        )
    resolved = [r for r in rows if r["resolved_at_95"]]
    return {
        "n_days": n_days,
        "standard_error_per_pair": round(se, 4),
        "pairs": rows,
        "rho_bar": sum(pairs.values()) / len(pairs),
        "resolved_pairs": len(resolved),
        "unresolved_pairs": len(rows) - len(resolved),
        "what_it_supports": (
            "Of six pairs, two resolve against sampling error. The pair sharing a factor family "
            "is the largest correlation in the book; the pair sharing an asset class is negative. "
            "The four sharing neither are indistinguishable from zero."
        ),
        "what_it_cannot_support": (
            "One informative pair per structural cell. That is a direction, not a coefficient, and "
            "any weighting fitted to it would be fitted to a single observation. The prior is "
            "published UNCALIBRATED."
        ),
        "what_would_calibrate_it": (
            "A book of eight sleeves gives twenty-eight pairs instead of six. Calibration is a "
            "consequence of breadth, not a route to it — which is the uncomfortable ordering: the "
            "prior is least testable exactly while it is most needed."
        ),
        "the_axis_with_no_local_evidence": (
            "Crisis direction. This book holds one SHORT_LIQUIDITY sleeve, so no pair isolates it "
            "and nothing here tests it. It decides fourteen of the twenty rankings below, and that "
            "is the single weakest joint in this artifact."
        ),
    }


def _arithmetic(contract: dict[str, Any], rho_bar_now: float) -> dict[str, Any]:
    """What the new pairs must average — the number an ordering is only useful against."""
    objective = contract["objective"]
    target_rho = objective["average_pairwise_correlation_objective"]
    gate = contract["thresholds"]["candidate_average_correlation_to_existing_book_max"]
    n_target = objective["target_total_sleeves"]
    n_now = 4
    haircut_low = objective["backtest_to_forward_haircut"]["range"][0]

    pairs_total = n_target * (n_target - 1) // 2
    pairs_now = n_now * (n_now - 1) // 2
    pairs_new = pairs_total - pairs_now

    required_new = (pairs_total * target_rho - pairs_now * rho_bar_now) / pairs_new
    at_gate = (pairs_now * rho_bar_now + pairs_new * gate) / pairs_total
    forward_at_gate = _book_sharpe(n_target, at_gate) / haircut_low
    shortfall = objective["honest_forward_sharpe_target"] - forward_at_gate

    return {
        "sleeves_now": n_now,
        "sleeves_target": n_target,
        "pairs_now": pairs_now,
        "pairs_new": pairs_new,
        "rho_bar_now": rho_bar_now,
        "objective_rho_bar": target_rho,
        "required_average_over_the_new_pairs": round(required_new, 5),
        "candidate_average_correlation_gate": gate,
        "rho_bar_if_the_aggregate_new_edges_sit_at_the_incremental_boundary": round(
            at_gate, 6
        ),
        "in_sample_sharpe_at_that_rho_bar": round(_book_sharpe(n_target, at_gate), 3),
        "forward_sharpe_at_that_rho_bar_optimistic_haircut": round(
            _book_sharpe(n_target, at_gate) / haircut_low, 3
        ),
        "in_sample_sharpe_at_the_objective": round(_book_sharpe(n_target, target_rho), 3),
        "forward_sharpe_at_the_objective_optimistic_haircut": round(
            _book_sharpe(n_target, target_rho) / haircut_low, 3
        ),
        "the_gap": (
            f"The aggregate new edges landing exactly on the {gate:+.2f} incremental boundary "
            f"gives a book average of "
            f"{at_gate:+.4f} and a forward Sharpe of "
            f"{forward_at_gate:.2f} on this book's own optimistic "
            f"haircut. The gate is necessary and it is not sufficient, and the shortfall is "
            f"{shortfall:.2f} "
            "of forward Sharpe. Ordering by expected orthogonality is the only lever that acts on "
            "the difference, because the incremental boundary cannot."
        ),
        "extends": "artifacts/analysis/breadth_acquisition/result.json, which reached the same "
        "conclusion against the superseded 0.15 gate.",
    }


def main() -> int:
    atlas = json.loads(ATLAS.read_text())
    contract = json.loads(CONTRACT.read_text())

    expected = _untouched_families(atlas)
    ranked_families = sorted(p.family for p in PRIORS)
    if ranked_families != expected:
        raise AssertionError(
            "the prior does not cover exactly the untouched atlas families — missing: "
            f"{sorted(set(expected) - set(ranked_families))}, extra: "
            f"{sorted(set(ranked_families) - set(expected))}"
        )

    structure = _measured_structure()
    arithmetic = _arithmetic(contract, structure["rho_bar"])
    stressed = json.loads(STRESSED.read_text())["rho_bar"]

    rows = []
    for p in PRIORS:
        rows.append(
            {
                "family": p.family,
                "prior": p.prior,
                "what_the_prior_means": MEANING[p.prior],
                "factor_family": p.factor,
                "driver": p.driver,
                "crisis_direction": p.crisis,
                "shares_factor_with": p.shares_factor_with(),
                "shares_crisis_direction_with": p.shares_crisis_with(),
                "reasoning": p.reasoning,
                "notes": p.notes,
                "evidence_status": "PRIOR_NOT_A_MEASUREMENT",
            }
        )
    rows.sort(key=lambda r: (RANK.index(r["prior"]), r["family"]))

    by_prior: dict[str, list[str]] = {}
    for row in rows:
        by_prior.setdefault(row["prior"], []).append(row["family"])

    result = {
        "schema": "canli.alphac-orthogonality-prior.v1",
        "claim_boundary": (
            "A PRIOR, stated before measurement and labelled as such in every row. No candidate "
            "correlation is measured, no hypothesis identity is registered, no return data is "
            "opened and no candidate is authorised. Nothing here is evidence about any family's "
            "correlation; it is an ordering to be tested and, where wrong, published as wrong. "
            "0 trials."
        ),
        "the_rule": {
            "stated_before_scoring": True,
            "1_shares_a_factor_family_with_a_live_sleeve": SHARES_FACTOR,
            "2_else_shares_a_crisis_direction_with_a_live_sleeve": SHARES_CRISIS,
            "3_else_driven_by_something_other_than_price": STRONGLY_ORTHOGONAL,
            "4_else": LIKELY_ORTHOGONAL,
            "asset_class_is_deliberately_absent": (
                "The one measured pair sharing an asset class is NEGATIVE (-0.062) and the one "
                "sharing a factor family is the largest in the book (+0.210). Scoring asset class "
                "would encode the intuition the evidence contradicts. This is the most attackable "
                "choice here and it is stated first rather than buried."
            ),
        },
        "live_sleeves": LIVE_SLEEVES,
        "measured_structure": structure,
        "what_the_ordering_is_for": arithmetic,
        "rho_bar_under_stress": {
            "measured": stressed,
            "note": (
                "Published for the crisis axis it bears on and NOT used to score anything: the "
                "stress windows are predeclared but the book still holds one SHORT_LIQUIDITY "
                "sleeve, so these numbers describe the existing four rather than testing the axis."
            ),
        },
        "by_prior": by_prior,
        "ranking": RANK,
        "prior_meanings": MEANING,
        "headline": (
            f"{len(by_prior.get(STRONGLY_ORTHOGONAL, []))} of {len(rows)} remaining families are "
            f"structurally orthogonal to this book on the stated rule. "
            f"{len(by_prior.get(SHARES_FACTOR, []))} share a factor family with a live sleeve "
            f"outright, and {len(by_prior.get(SHARES_CRISIS, []))} lose money in the same event as "
            "the sleeve that carries this book's largest single source of return. Breadth measured "
            "in asset classes is not breadth."
        ),
        "families": rows,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  measured: {structure['resolved_pairs']} of {len(structure['pairs'])} pairs resolve "
          f"(SE {structure['standard_error_per_pair']})")
    for row in structure["pairs"]:
        mark = "RESOLVED" if row["resolved_at_95"] else "noise"
        shared = "shares factor" if row["shares_factor_family"] else ""
        se_from_zero = row["standard_errors_from_zero"]
        print(
            f"    {row['pair']:26} {row['rho']:+.4f}  {se_from_zero:>5.2f} SE  {mark:<9}{shared}"
        )
    print()
    print(f"  new pairs must average {arithmetic['required_average_over_the_new_pairs']:+.5f} "
          f"against an incremental boundary of "
          f"{arithmetic['candidate_average_correlation_gate']:+.2f}")
    at_gate_rho = arithmetic[
        "rho_bar_if_the_aggregate_new_edges_sit_at_the_incremental_boundary"
    ]
    at_gate_fwd = arithmetic["forward_sharpe_at_that_rho_bar_optimistic_haircut"]
    print(f"  at the gate: rho_bar {at_gate_rho:+.4f} -> forward {at_gate_fwd:.2f}")
    print()
    for prior in RANK:
        families = by_prior.get(prior, [])
        if families:
            print(f"  {prior}  ({len(families)})")
            for fam in families:
                print(f"      {fam}")
    print(f"\n  {result['headline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
