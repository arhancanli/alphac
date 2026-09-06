#!/usr/bin/env python3
# ruff: noqa: E501
"""Build the governed ALPHAC candidate atlas without opening return data.

The atlas is deliberately broader than the active return-testing queue.  A cell is a
family/universe/horizon identity, not an independent discovery claim: all six cells in a
family share one family-wise trial account if they ever reach returns.  At this stage the
builder performs taxonomy and governance work only, so every cell spends zero hypotheses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Any

LINEAGE_CONFIG = Path(__file__).parents[1] / "config" / "sleeve_family_lineage.json"
ADMISSION_CONTRACT = Path(__file__).parents[1] / "config" / "sleeve_admission_contract.json"
LINEAGE_CLASSES = {
    "ACTIVE_FEASIBILITY",
    "DUPLICATE_OVERLAP",
    "NOVEL_ATLAS",
    "RETIRED_KILLED",
    "IDENTITY_REDESIGN_REQUIRED",
}


@dataclass(frozen=True)
class FamilySpec:
    id: str
    asset_group: str
    mechanism: str
    universes: tuple[str, str]
    horizons: tuple[str, str, str]
    point_in_time_data: str
    execution_model: str
    primary_friction: str
    overlap_guard: str
    literature_status: str = "PENDING_SOURCE_REVIEW"
    program_status: str = "ATLAS_ONLY"


def S(
    id: str,
    asset_group: str,
    mechanism: str,
    universes: tuple[str, str],
    horizons: tuple[str, str, str],
    point_in_time_data: str,
    execution_model: str,
    primary_friction: str,
    overlap_guard: str,
    literature_status: str = "PENDING_SOURCE_REVIEW",
    program_status: str = "ATLAS_ONLY",
) -> FamilySpec:
    return FamilySpec(
        id=id,
        asset_group=asset_group,
        mechanism=mechanism,
        universes=universes,
        horizons=horizons,
        point_in_time_data=point_in_time_data,
        execution_model=execution_model,
        primary_friction=primary_friction,
        overlap_guard=overlap_guard,
        literature_status=literature_status,
        program_status=program_status,
    )


FAMILY_SPECS: tuple[FamilySpec, ...] = (
    S(
        "earnings_narrative_change",
        "equity",
        "filing-language change residualized to surprise and momentum",
        ("us_large_mid", "us_small_mid"),
        ("21d", "63d", "126d"),
        "SEC filing acceptance time and immutable text",
        "next eligible open, beta/sector neutral",
        "open spread, delistings, corporate actions",
        "AlphaMax and earnings-event beta",
        "SOURCE_REVIEWED",
        "RETIRED_KILLED",
    ),
    S(
        "analyst_revision_drift",
        "equity",
        "as-of consensus revision diffusion",
        ("us_large_mid", "developed_ex_us"),
        ("21d", "63d", "126d"),
        "contributor-level as-of estimate history",
        "next open after timestamp, sector neutral",
        "timestamp latency, crowding, borrow",
        "earnings surprise and price momentum",
    ),
    S(
        "merger_arbitrage",
        "event_equity",
        "announced cash-deal spread convergence",
        ("us_cash_deals", "developed_cash_deals"),
        ("5d", "21d", "to_resolution"),
        "deal terms, amendments and outcomes as known",
        "deal basket with break-risk cap",
        "break gaps, borrow, partial fills",
        "market beta and generic value",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "tender_offer_spread",
        "event_equity",
        "fixed-price tender convergence",
        ("us_issuer_tenders", "us_third_party_tenders"),
        ("5d", "21d", "to_expiry"),
        "SC TO and recommendation documents by acceptance time",
        "proration-aware event basket",
        "proration, withdrawal, odd-lot constraints",
        "merger arbitrage",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "index_reconstitution_flow",
        "event_equity",
        "forced benchmark demand between announcement and effective date",
        ("us_large_indices", "global_developed_indices"),
        ("1d", "5d", "to_effective"),
        "point-in-time announcements, float and weights",
        "auction-aware long/short basket",
        "closing-auction impact and crowding",
        "ordinary momentum",
    ),
    S(
        "active_ownership_escalation",
        "event_equity",
        "specific Schedule 13D control intent",
        ("us_all_cap", "us_small_mid"),
        ("21d", "63d", "126d"),
        "13D/13D-A state and Item 4 at acceptance time",
        "next-open diversified target basket",
        "gaps, liquidity, amendments",
        "small-cap value and momentum",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "spin_off_dislocation",
        "event_equity",
        "forced selling and information gaps around separations",
        ("us_spinoffs", "developed_spinoffs"),
        ("5d", "63d", "252d"),
        "Form 10/8-K terms and when-issued lineage",
        "parent/stub and child baskets",
        "when-issued liquidity, borrow, basis",
        "size, value and issuance",
        "SOURCE_REVIEWED",
        "IDENTITY_REDESIGN_REQUIRED",
    ),
    S(
        "repurchase_issuance_flow",
        "equity",
        "net corporate equity demand from completed repurchases versus issuance",
        ("us_large_mid", "us_small_mid"),
        ("21d", "63d", "252d"),
        "filing-time shares, offerings and completed repurchases",
        "sector-neutral cross-section",
        "reporting lag, liquidity, borrow",
        "value, profitability and momentum",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "customer_supplier_propagation",
        "equity_network",
        "idiosyncratic shocks propagating through production links",
        ("us_public_network", "global_developed_network"),
        ("5d", "21d", "63d"),
        "point-in-time named relationships and filing times",
        "network-residualized basket",
        "stale links, concentration, open gaps",
        "industry and price momentum",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "securities_lending_supply",
        "equity_short",
        "borrow-fee and utilization changes from constrained supply",
        ("us_easy_to_borrow", "us_hard_to_borrow"),
        ("5d", "21d", "63d"),
        "historical fees, availability, locates and recalls",
        "availability-capped long/short basket",
        "recalls, locate failure, fee jumps",
        "short interest and momentum",
    ),
    S(
        "short_interest_revision",
        "equity_short",
        "publication-aware changes in short positioning",
        ("us_large_mid", "us_small_mid"),
        ("10d", "21d", "42d"),
        "exchange publication dates and settlement lags",
        "beta/sector-neutral basket",
        "borrow availability and squeeze gaps",
        "securities lending and momentum",
    ),
    S(
        "closed_end_fund_discount",
        "fund_relative_value",
        "published NAV discount mean reversion",
        ("us_equity_cef", "us_bond_cef"),
        ("5d", "21d", "63d"),
        "NAV publication time, distributions and reorganizations",
        "discount-ranked hedged basket",
        "stale NAV, spread, leverage events",
        "credit beta and value",
    ),
    S(
        "bond_etf_nav_dislocation",
        "credit",
        "ETF price versus executable underlying-value dislocation",
        ("us_ig_etf", "us_hy_etf"),
        ("intraday", "1d", "5d"),
        "timestamped basket, evaluated prices and TRACE prints",
        "secondary-market ETF execution only",
        "stale marks, AP asymmetry, crisis spreads",
        "credit beta and liquidity beta",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "credit_equity_relative_value",
        "credit",
        "issuer equity-credit dislocation after common-risk neutralization",
        ("us_ig_issuers", "us_hy_issuers"),
        ("5d", "21d", "63d"),
        "PIT issuer mapping, bond prices and corporate actions",
        "liquidity-capped matched issuer basket",
        "TRACE liquidity, borrow, duration hedge",
        "quality, distress and momentum",
    ),
    S(
        "fallen_angel_flow",
        "credit",
        "forced selling around investment-grade downgrades",
        ("us_corporates", "global_developed_corporates"),
        ("5d", "21d", "63d"),
        "rating action timestamps and index eligibility",
        "bond/ETF proxy basket with duration hedge",
        "dealer inventory, index timing, bid-ask",
        "credit momentum and quality",
    ),
    S(
        "municipal_taxable_basis",
        "credit",
        "tax-adjusted municipal versus Treasury/credit dislocation",
        ("us_ig_muni", "us_high_yield_muni"),
        ("5d", "21d", "63d"),
        "MSRB prints, calls, tax and reference data",
        "duration/quality-matched basket",
        "sparse prints, mark staleness, calls",
        "duration and generic credit",
    ),
    S(
        "options_dispersion",
        "equity_options",
        "index versus constituent implied-correlation dispersion",
        ("spx_top50", "spx_sector_baskets"),
        ("7d", "30d", "60d"),
        "historical surfaces and membership at quote time",
        "defined-loss delta-hedged option book",
        "multi-leg spread, impact, gap hedging",
        "short index variance",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "options_skew_carry",
        "equity_options",
        "cross-sectional downside skew compensation",
        ("spx_index", "liquid_single_names"),
        ("7d", "30d", "60d"),
        "quote-level surfaces, dividends and actions",
        "defined-risk verticals with hedge ledger",
        "wing liquidity, jumps, assignment",
        "variance premium and equity beta",
    ),
    S(
        "options_term_structure",
        "equity_options",
        "relative option variance across maturities",
        ("spx_index", "liquid_sector_etfs"),
        ("7d_30d", "30d_60d", "60d_90d"),
        "synchronized surfaces and forward dividends",
        "vega/gamma-balanced calendars",
        "calendar spread fills and gap vega",
        "variance premium and trend",
    ),
    S(
        "dealer_gamma_pressure",
        "equity_options",
        "dealer hedge demand conditional on estimated gamma inventory",
        ("spx_0dte", "liquid_single_names"),
        ("intraday", "1d", "5d"),
        "PIT open interest, trades and surface state",
        "liquidity-window futures/equity execution",
        "latency, impact, inventory-model error",
        "intraday reversal and volatility",
    ),
    S(
        "volatility_futures_curve",
        "volatility",
        "term-structure roll and dislocation with crash budget",
        ("vix_front", "vix_midcurve"),
        ("1d", "5d", "21d"),
        "settlements, rolls, multipliers and quotes",
        "calendar-spread or capped outright book",
        "limit moves, roll crowding, convex loss",
        "equity trend and variance premium",
    ),
    S(
        "treasury_auction_concession",
        "rates",
        "scheduled dealer balance-sheet demand around coupon auctions",
        ("ust_2y_5y", "ust_7y_30y"),
        ("1d", "3d", "5d"),
        "announcement revision and auction lineage",
        "duration-hedged futures/ETF basket",
        "one-tick costs, rolls, event gaps",
        "duration beta and trend",
        "SOURCE_REVIEWED",
        "IDENTITY_REDESIGN_REQUIRED",
    ),
    S(
        "pre_fomc_announcement_drift",
        "rates_event",
        "publication-aware pre-announcement equity drift",
        ("es_futures", "spy_proxy"),
        ("2h", "6h", "1d"),
        "PIT meeting schedule and exact release time",
        "event-window market order simulation",
        "schedule changes, spread, announcement gaps",
        "overnight and market beta",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "swap_spread_dislocation",
        "rates",
        "Treasury-swap relative value and dealer balance-sheet pressure",
        ("usd_2y_5y", "usd_10y_30y"),
        ("5d", "21d", "63d"),
        "PIT swaps, Treasury deliverables and funding",
        "DV01-neutral spread basket",
        "financing, roll, clearing and convexity",
        "duration and auction concession",
    ),
    S(
        "inflation_breakeven_relative_value",
        "rates",
        "inflation compensation versus survey and realized-vintage information",
        ("tips_2y_5y", "tips_5y_10y"),
        ("21d", "63d", "126d"),
        "PIT TIPS, swaps, CPI vintages and carry",
        "duration/carry-neutral breakeven basket",
        "seasonality, index lag, funding",
        "AlphaVintage and duration",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "mortgage_convexity_pressure",
        "rates",
        "rate-volatility-driven mortgage hedge rebalancing",
        ("ust_5y_10y", "agency_mbs_proxy"),
        ("1d", "5d", "21d"),
        "PIT mortgage universe, durations and rate surface",
        "DV01-neutral futures/MBS proxy",
        "convexity jumps, liquidity, model error",
        "rates trend and volatility",
    ),
    S(
        "cross_currency_basis",
        "fx_rates",
        "currency funding-demand dislocation",
        ("g10_short_tenor", "g10_long_tenor"),
        ("5d", "21d", "63d"),
        "PIT forwards, OIS curves and fixings",
        "delta/DV01-matched basis basket",
        "roll, funding, holidays, fixing risk",
        "FX carry and global dollar beta",
    ),
    S(
        "fx_option_risk_reversal",
        "fx_options",
        "cross-sectional compensation in implied downside asymmetry",
        ("g10", "liquid_em"),
        ("7d", "30d", "90d"),
        "PIT surfaces, forwards and calendars",
        "delta-hedged defined-risk structures",
        "wide wings, gap hedging, NDF fixing",
        "FX carry and trend",
    ),
    S(
        "cftc_hedging_pressure",
        "commodity",
        "commercial hedging-pressure risk transfer",
        ("energy_metals", "agriculture_livestock"),
        ("7d", "28d", "84d"),
        "release-lagged COT positions and fixed contract map",
        "sector-neutral futures basket",
        "rolls, limits, crisis spreads",
        "trend and curve carry",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "commodity_calendar_seasonality",
        "commodity",
        "physical-cycle calendar spread behavior",
        ("energy_metals", "agriculture"),
        ("5d", "21d", "63d"),
        "contract-level curves, delivery and roll calendars",
        "matched calendar spreads",
        "delivery squeeze, seasonality decay, limits",
        "curve carry and trend",
    ),
    S(
        "electricity_load_weather_spread",
        "power",
        "forecast error in regional load versus marginal fuel",
        ("pjm_ercot", "miso_isone"),
        ("day_ahead", "7d", "28d"),
        "PIT weather/load forecasts and hub prices",
        "listed power/gas spread basket",
        "nodal basis, extreme weather, thin books",
        "natural-gas trend and seasonality",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "natural_gas_storage_weather",
        "commodity",
        "storage surprise conditional on forecast-vintage weather",
        ("henry_hub", "regional_gas"),
        ("1d", "7d", "28d"),
        "EIA release time and weather forecast vintages",
        "futures/calendar-spread execution",
        "release slippage, revisions, limit moves",
        "energy trend and curve carry",
        "SOURCE_REVIEWED",
        "DUPLICATE_OVERLAP",
    ),
    S(
        "carbon_allowance_carry",
        "environmental",
        "regulatory inventory and convenience yield in allowance curves",
        ("eu_ets", "uk_california"),
        ("5d", "21d", "63d"),
        "PIT contract rules, registry and curve quotes",
        "listed futures spread basket",
        "policy gaps, venue access, roll liquidity",
        "energy prices and commodity carry",
    ),
    S(
        "freight_derivative_dislocation",
        "freight",
        "shipping capacity imbalance in forward freight agreements",
        ("dry_bulk", "tanker_container"),
        ("5d", "21d", "63d"),
        "PIT route assessments, contracts and quotes",
        "cleared FFA basket",
        "assessment timing, sparse liquidity, margin",
        "commodity trend and global growth",
    ),
    S(
        "crypto_liquidation_pressure",
        "crypto",
        "forced deleveraging and order-book recovery",
        ("btc_eth", "liquid_alt_perps"),
        ("15m", "4h", "1d"),
        "exchange trades, liquidations and book snapshots",
        "latency/partial-fill event simulator",
        "outages, queue, impact, clawbacks",
        "funding carry and momentum",
    ),
    S(
        "crypto_cross_venue_basis",
        "crypto",
        "temporary collateral and inventory segmentation across venues",
        ("btc_eth", "stablecoin_pairs"),
        ("1h", "1d", "7d"),
        "synchronized books, fees and transfer state",
        "inventory-prefunded cross-venue book",
        "withdrawal halts, latency, counterparty risk",
        "funding carry",
    ),
    S(
        "stablecoin_dislocation",
        "crypto",
        "institution-eligible USDC secondary-to-primary redemption dislocation",
        ("usdc_usd_centralized", "usdc_usd_onchain"),
        ("intraday", "1d", "to_fiat_settlement"),
        "effective-dated issuer eligibility, terms, venue books, chain and bank state",
        "prefunded purchase, canonical-chain transfer and direct issuer redemption",
        "depeg gaps, blocked redemption, venue/issuer/bank loss and transfer delay",
        "crypto funding, venue credit and banking stress",
        "SOURCE_REVIEWED",
        "ACTIVE_FEASIBILITY",
    ),
    S(
        "crypto_options_surface",
        "crypto_options",
        "relative skew/term compensation with defined loss",
        ("btc_options", "eth_options"),
        ("7d", "30d", "60d"),
        "quote-level surfaces, expiries and DVOL state",
        "delta-hedged defined-risk structures",
        "24/7 gaps, spread, exchange default",
        "crypto variance premium and trend",
    ),
    S(
        "catastrophe_bond_event_risk",
        "insurance_linked",
        "seasonal/event insurance risk transfer",
        ("us_wind_exposed", "global_multi_peril"),
        ("monthly", "quarterly", "annual"),
        "security triggers, event notices and executable marks",
        "diversified security-level basket",
        "mark staleness, trapped collateral, trigger basis",
        "credit beta and climate seasonality",
    ),
    S(
        "sovereign_cds_fx_dislocation",
        "sovereign",
        "local FX versus sovereign credit repricing mismatch",
        ("liquid_em_ig", "liquid_em_hy"),
        ("5d", "21d", "63d"),
        "PIT CDS, NDF/FX, curves and events",
        "beta/duration-neutral matched-country basket",
        "jump risk, capital controls, liquidity",
        "EM carry and global risk beta",
    ),
)


def _slug(value: str) -> str:
    return value.lower().replace("/", "_").replace(" ", "_").replace("-", "_")


def load_lineage_registry(path: Path = LINEAGE_CONFIG) -> dict[str, Any]:
    """Load the governed identity crosswalk and reject incomplete classifications."""
    registry = json.loads(path.read_text())
    specs = {family.id for family in FAMILY_SPECS}
    governed = set(registry.get("families", {}))
    if specs != governed:
        raise ValueError(
            "lineage registry must classify every atlas family exactly; "
            f"missing={sorted(specs - governed)}, extra={sorted(governed - specs)}"
        )
    invalid = {
        family_id: record.get("classification")
        for family_id, record in registry["families"].items()
        if record.get("classification") not in LINEAGE_CLASSES
    }
    if invalid:
        raise ValueError(f"invalid lineage classifications: {invalid}")
    return registry


def build_atlas() -> dict[str, Any]:
    lineage_registry = load_lineage_registry()
    family_return_outcomes = {
        family_id: record["return_outcome"]
        for family_id, record in lineage_registry["families"].items()
        if isinstance(record.get("return_outcome"), dict)
    }
    cells: list[dict[str, Any]] = []
    for family in FAMILY_SPECS:
        lineage = lineage_registry["families"][family.id]
        for universe, horizon in product(family.universes, family.horizons):
            cells.append(
                {
                    "id": f"{family.id}__{_slug(universe)}__{_slug(horizon)}",
                    "family_id": family.id,
                    "asset_group": family.asset_group,
                    "mechanism": family.mechanism,
                    "universe": universe,
                    "horizon": horizon,
                    "point_in_time_data": family.point_in_time_data,
                    "execution_model": family.execution_model,
                    "primary_friction": family.primary_friction,
                    "overlap_guard": family.overlap_guard,
                    "literature_status": family.literature_status,
                    "program_status": family.program_status,
                    "lineage_classification": lineage["classification"],
                    "lineage_aliases": lineage.get("aliases", []),
                    "lineage_evidence": lineage.get("evidence", []),
                    "forward_experiment": lineage.get("forward_experiment"),
                    "screen_state": (
                        "FAMILY_KILLED_EXACT_CELL_UNTESTED"
                        if family.id in family_return_outcomes
                        else "UNSCREENED_NO_RETURN"
                    ),
                    "return_data_opened": False,
                    "return_hypotheses_spent": 0,
                    "family_trial_account": family.id,
                }
            )

    contract_objective = json.loads(ADMISSION_CONTRACT.read_text())["objective"]
    payload: dict[str, Any] = {
        "schema": "canli.alphac-sleeve-atlas.v2",
        "as_of": "2026-08-22",
        # The atlas owns taxonomy, not target-setting. Derive its objective from the admission
        # contract so an old target cannot survive in the candidate funnel after governance has
        # superseded it.
        "objective": {**contract_objective, "targets_are_promises": False},
        "governance": {
            "stage": "taxonomy_before_returns",
            "cells_per_family": 6,
            "family_wise_accounting": True,
            "cell_is_independent_trial": False,
            "return_admission": "prohibited until literature, PIT lineage, execution, overlap and preregistration gates pass",
            "novelty_registry": "config/sleeve_family_lineage.json",
            "novelty_is_performance_evidence": False,
        },
        "summary": {
            "families": len(FAMILY_SPECS),
            "cells": len(cells),
            "asset_groups": len({family.asset_group for family in FAMILY_SPECS}),
            "return_data_opened": 0,
            "return_hypotheses_spent": 0,
            "family_return_data_opened": sum(
                bool(outcome.get("return_data_opened"))
                for outcome in family_return_outcomes.values()
            ),
            "family_return_hypotheses_spent": sum(
                int(outcome["return_hypotheses_spent"])
                for outcome in family_return_outcomes.values()
            ),
            "lineage_classifications": dict(
                sorted(
                    Counter(
                        record["classification"] for record in lineage_registry["families"].values()
                    ).items()
                )
            ),
        },
        "lineage_claim_boundary": lineage_registry["claim_boundary"],
        "current_sleeves": lineage_registry["current_sleeves"],
        "families": [
            {
                **asdict(family),
                "lineage_classification": lineage_registry["families"][family.id]["classification"],
                "lineage_aliases": lineage_registry["families"][family.id].get("aliases", []),
                "lineage_evidence": lineage_registry["families"][family.id].get("evidence", []),
                "forward_experiment": lineage_registry["families"][family.id].get(
                    "forward_experiment"
                ),
                "return_outcome": family_return_outcomes.get(family.id),
            }
            for family in FAMILY_SPECS
        ],
        "cells": cells,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/discovery/sleeve_atlas.json"),
    )
    args = parser.parse_args()
    payload = build_atlas()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                **payload["summary"],
                "content_hash": payload["content_hash"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
