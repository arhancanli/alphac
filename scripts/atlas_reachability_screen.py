"""Screen the twenty untouched atlas families on obtainability, before any of them is worked on.

WHY THIS EXISTS. C1 established that a family sitting one gate from feasibility can be unreachable
by any amount of extraction work, because the shortfall is in what the documents contain. This
asks the same question one step earlier and for the whole atlas: not "can the detector be fixed?"
but "does the record this identity needs exist, and can we get it?"

Twenty families are `NOVEL_ATLAS` with no return data opened. Writing a protocol against one of
them without asking this first is how the three near-miss families happened — three times, by
hand, each time discovering at the end what a screen would have said at the start.

THE DECISIVE ARITHMETIC, and it needs no judgement at all. The admission contract in force
requires `minimum_oos_observations` daily observations of a candidate's own return series. A
source that offers fewer years than that cannot supply them, however good the extraction is and
however real the effect. So any family whose best source has a MEASURED history shorter than the
contract's minimum is out of reach today on arithmetic, not opinion — and the screen computes that
from the contract and from the lake rather than from a typed number.

WHAT IS MEASURED AND WHAT IS JUDGED — stated per field rather than in a disclaimer, because a
screen that blurs the two is worse than no screen.

  MEASURED    the history of every source this repo already holds, re-derived from the lake on
              each run; the contract minimum, read from the contract in force; the family list,
              derived from the atlas; the verdict, computed from those.
  JUDGED      who holds a record we do NOT hold, and whether an as-of version of it was preserved
              at all. Each such field carries `evidence_status` and a `how_to_verify` naming the
              concrete check that would settle it. None of them is presented as measured.

Reads the atlas, the contract and the lake read-only. Registers no hypothesis, opens no return
data, authorises no candidate: 0 trials.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ATLAS = REPO / "artifacts" / "discovery" / "sleeve_atlas.json"
CONTRACT = REPO / "config" / "sleeve_admission_contract.json"
FEASIBILITY = REPO / "artifacts" / "feasibility"
OUTPUT = REPO / "artifacts" / "analysis" / "atlas_reachability_screen" / "result.json"

TRADING_DAYS_PER_YEAR = 252

# Verdicts, ordered best to worst. The order IS the ranking the item asks for.
HELD = "OBTAINABLE_FROM_DATA_THIS_REPO_ALREADY_HOLDS"
PUBLIC = "OBTAINABLE_PUBLICLY_NEEDS_A_NEW_PIPELINE"
EXTRACTION = "HELD_BUT_BLOCKED_ON_EXTRACTION_QUALITY"
VENDOR = "VENDOR_ONLY_AN_OWNER_SPENDING_DECISION"
SHORT = "HISTORY_TOO_SHORT_FOR_THE_ADMISSION_CONTRACT"
MARKS = "RECORD_OBTAINABLE_BUT_THE_MARKS_ARE_NOT_EXECUTABLE"
NO_PIT = "NO_POINT_IN_TIME_RECORD_WAS_EVER_PRESERVED"

RANK = [HELD, PUBLIC, EXTRACTION, VENDOR, SHORT, MARKS, NO_PIT]

MEANING = {
    HELD: (
        "The record this identity needs is already in this repo's lake, with enough history for "
        "the contract. Nothing has to be bought and no new pipeline has to be built."
    ),
    PUBLIC: (
        "The record exists and is public. The cost is engineering, which is the cheapest kind of "
        "blocker this programme has."
    ),
    EXTRACTION: (
        "The documents are held and the shortfall is in reading them. C1's harness applies "
        "directly here: ask what a PERFECT detector would reach BEFORE writing a protocol."
    ),
    VENDOR: (
        "The record exists and is licensed. This is not an engineering question and it is not "
        "mine to answer — it is a spending decision with a number attached."
    ),
    SHORT: (
        "The best source offers less history than the admission contract's minimum observations. "
        "The family cannot produce an admissible sleeve today no matter how good the idea is. "
        "It becomes screenable only by waiting, or by buying history."
    ),
    MARKS: (
        "The prices are assessed, indicated or broker-quoted rather than transacted. A backtest "
        "on them measures a price nobody could have traded, which is a more expensive kind of "
        "wrong than a null: it produces a number, and the number is not about trading."
    ),
    NO_PIT: (
        "The as-of state was never archived — only the current or restated version survives. No "
        "amount of money or engineering recovers it. Forward collection from today is the only "
        "route, which means the clock starts now and the contract's minimum sets the wait."
    ),
}


# ------------------------------------------------------------------------------------------
# MEASURED. Every source below is re-derived from the lake on each run rather than transcribed,
# so a claim about our own coverage cannot go stale while still reading as current.
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Held:
    name: str
    first: str
    last: str
    span_years: float
    n: int
    measured_from: str


def _span_years(first: str, last: str) -> float:
    from datetime import date

    def d(s: str) -> date:
        parts = [int(p) for p in s.split("-")]
        while len(parts) < 3:
            parts.append(1)
        return date(*parts)

    return round((d(last) - d(first)).days / 365.25, 2)


def _measure_edgar() -> Held | None:
    idx = REPO / "data" / "raw" / "sec_active_ownership_13d" / "indexes"
    if not idx.is_dir():
        return None
    quarters = sorted(p.name.split(".")[0] for p in idx.glob("*.idx.gz"))
    if not quarters:
        return None
    q_to_month = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}
    first = f"{quarters[0][:4]}-{q_to_month[quarters[0][-2:]]}"
    last = f"{quarters[-1][:4]}-{q_to_month[quarters[-1][-2:]]}"
    return Held(
        "edgar_quarterly_indexes", first, last, _span_years(first, last), len(quarters),
        "data/raw/sec_active_ownership_13d/indexes/*.idx.gz",
    )


def _measure_funding() -> Held | None:
    root = REPO / "data" / "lake" / "funding"
    if not root.is_dir():
        return None
    years = sorted({p.name.split("=")[1] for p in root.glob("*/year=*")})
    if not years:
        return None
    return Held(
        "crypto_perp_funding_multivenue", years[0], years[-1],
        _span_years(years[0], years[-1]), len(years),
        "data/lake/funding/*/year=*",
    )


def _measure_macro(series: str) -> Callable[[], Held | None]:
    def measure() -> Held | None:
        meta = REPO / "data" / "lake_macro_vintage" / "meta.json"
        if not meta.is_file():
            return None
        for row in json.loads(meta.read_text())["series"]:
            if row["series"] == series:
                return Held(
                    f"fred_vintage_{series}", row["first_obs"], row["last_obs"],
                    _span_years(row["first_obs"], row["last_obs"]), row["n_obs"],
                    "data/lake_macro_vintage/meta.json",
                )
        return None

    return measure


def _measure_short_interest() -> Held | None:
    root = REPO / "data" / "lake_shortint"
    if not root.is_dir():
        return None
    dates = sorted(
        p.name.split("=")[1].replace(".parquet", "")
        for p in root.glob("settlement_date=*")
    )
    if not dates:
        return None
    return Held(
        "finra_short_interest", dates[0], dates[-1], _span_years(dates[0], dates[-1]), len(dates),
        "data/lake_shortint/settlement_date=*.parquet",
    )


def _measure_deribit() -> Held | None:
    root = REPO / "data" / "deribit" / "snapshots"
    if not root.is_dir():
        return None
    dates = sorted(
        p.name.replace("snap_", "").replace(".jsonl", "")
        for p in root.glob("snap_*.jsonl")
    )
    if not dates:
        return None
    return Held(
        "deribit_option_snapshots", dates[0], dates[-1],
        _span_years(dates[0], dates[-1]), len(dates),
        "data/deribit/snapshots/snap_*.jsonl",
    )


SOURCES: dict[str, Callable[[], Held | None]] = {
    "edgar_quarterly_indexes": _measure_edgar,
    "crypto_perp_funding_multivenue": _measure_funding,
    "finra_short_interest": _measure_short_interest,
    "deribit_option_snapshots": _measure_deribit,
    "fred_breakeven_10y": _measure_macro("T10YIE"),
    "fred_breakeven_5y": _measure_macro("T5YIE"),
    "fred_treasury_10y": _measure_macro("DGS10"),
}


# ------------------------------------------------------------------------------------------
# JUDGED. Everything below is a claim about a record this repo does NOT hold. Each carries the
# check that would settle it, because an unverified claim with no route to verification is just
# an opinion wearing a schema.
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Screen:
    family: str
    required_record: str
    source: str
    status: str
    reason: str
    held_source: str | None = None
    documented_history_years: float | None = None
    documented_history_basis: str | None = None
    how_to_verify: str | None = None
    related_artifact: str | None = None
    marks_are_indicative: bool = False
    extraction_gated: bool = False
    notes: list[str] = field(default_factory=list)


SCREENS: tuple[Screen, ...] = (
    Screen(
        family="analyst_revision_drift",
        required_record="contributor-level analyst estimates as they stood on each past date",
        source="I/B/E/S, FactSet or Visible Alpha estimate history",
        status=VENDOR,
        reason=(
            "The consensus is republished, not versioned: the freely available number is today's "
            "view of the past. Only a vendor's own archive preserves who said what and when, and "
            "those archives are themselves restated when brokers merge or are backfilled."
        ),
        how_to_verify="Ask any vendor for the as-of contributor detail and its restatement policy.",
    ),
    Screen(
        family="merger_arbitrage",
        required_record="deal terms, amendments and outcomes as known at each date",
        source="EDGAR",
        status=EXTRACTION,
        reason=(
            "Already screened, and the answer is not an extraction one: the 0.80 prior-8-K gate "
            "blends two filing populations that do not share the obligation it tests. Do not "
            "re-derive it here."
        ),
        held_source="edgar_quarterly_indexes",
        related_artifact="artifacts/analysis/reachability_harness/result.json",
    ),
    Screen(
        family="tender_offer_spread",
        required_record="SC TO and recommendation documents by acceptance time",
        source="EDGAR",
        status=EXTRACTION,
        reason=(
            "A feasibility probe already exists and returned DATA_GATED on extraction quality. "
            "C1's harness applies before any protocol is written: compute what a perfect detector "
            "would reach first."
        ),
        held_source="edgar_quarterly_indexes",
        related_artifact="artifacts/feasibility/tender_offer_spread/result.json",
        extraction_gated=True,
    ),
    Screen(
        family="index_reconstitution_flow",
        required_record="index announcements, float factors and weights as published on the day",
        source="S&P, FTSE Russell or MSCI index services",
        status=VENDOR,
        reason=(
            "The announcement archive and the float/weight vintages ARE the index provider's "
            "product. Beyond the fee there is a redistribution restriction, which bears directly "
            "on a programme whose whole asset is publishing what it measured."
        ),
        how_to_verify=(
            "Read one index provider's licence for whether derived research may be published."
        ),
        notes=["The licence question is unusual here: it constrains publication, not just cost."],
    ),
    Screen(
        family="active_ownership_escalation",
        required_record="13D and 13D/A state, and Item 4 language, at acceptance time",
        source="EDGAR",
        status=EXTRACTION,
        reason=(
            "The filings are held. The existing 13D probes fail on extraction quality — header "
            "completeness, contemporaneous ticker resolution and Item 4 extraction rate — not on "
            "obtainability."
        ),
        held_source="edgar_quarterly_indexes",
        related_artifact="artifacts/analysis/data_gate_unblocks/result.json",
        extraction_gated=True,
        notes=[
            "Atlas id and feasibility id differ (active_ownership_escalation vs "
            "active_ownership_13d*). The link is a JUDGEMENT that they name the same mechanism.",
        ],
    ),
    Screen(
        family="securities_lending_supply",
        required_record="historical borrow fee, availability, locates and recalls per name per day",
        source="S&P Global Securities Finance or DataLend",
        status=VENDOR,
        reason=(
            "The identity is priced off the FEE. This repo holds FINRA short interest, which is a "
            "different quantity — the size of the position, not its cost — and substituting it "
            "would be measuring something the identity does not name."
        ),
        held_source="finra_short_interest",
        how_to_verify="Price one securities-finance feed with daily history.",
        notes=[
            "The held proxy is the trap: it is available, it correlates, and it is not the "
            "variable. A screen that reported 'we have short interest' would have passed a "
            "family whose mechanism we cannot price.",
        ],
    ),
    Screen(
        family="credit_equity_relative_value",
        required_record="point-in-time issuer mapping, bond prices and corporate actions",
        source="TRACE plus a reference-data vendor",
        status=PUBLIC,
        reason=(
            "TRACE is public, but disseminated sizes are CAPPED, so the public print record is "
            "systematically the small trades. The issuer-to-equity mapping and terms are vendor. "
            "Public enough to screen, truncated enough that the truncation must be modelled."
        ),
        how_to_verify=(
            "Confirm the current dissemination caps and whether the academic TRACE file lifts "
            "them for history."
        ),
        notes=["The record exists and is biased by construction — model the cap or do not use it."],
    ),
    Screen(
        family="fallen_angel_flow",
        required_record="rating action timestamps and index eligibility at each rebalance",
        source="Moody's/S&P rating histories plus an index provider's eligibility rules",
        status=VENDOR,
        reason=(
            "Both legs are licensed, and the second leg has the same publication restriction as "
            "index_reconstitution_flow."
        ),
        how_to_verify="Price a rating-history file and check the index rulebook's licence.",
    ),
    Screen(
        family="municipal_taxable_basis",
        required_record="MSRB trade prints, call schedules, tax status and reference data",
        source="MSRB EMMA plus municipal reference data",
        status=PUBLIC,
        reason=(
            "Trade prints are publicly disclosed. Call schedules and tax treatment — which is "
            "where this identity's whole basis lives — are reference data and mostly vendor."
        ),
        how_to_verify=(
            "Check whether EMMA's historical bulk file carries call and tax fields or only prints."
        ),
    ),
    Screen(
        family="dealer_gamma_pressure",
        required_record="open interest, trades and the option surface as they stood on each date",
        source="Alpaca expired-contract chain (held route) or OPRA history (vendor)",
        status=HELD,
        reason=(
            "The free route exists and is documented in this repo: expired contracts ARE "
            "enumerable with status=inactive and their daily bars retrievable. Its coverage "
            "begins around 2024, which the contract arithmetic below then rules on."
        ),
        documented_history_years=2.5,
        documented_history_basis=(
            "scripts/ingest_options_chain.py (verified there, not re-run here)"
        ),
        how_to_verify=(
            "Re-run the contract enumeration for a 2019 expiry and see whether it returns rows."
        ),
        notes=[
            "This entry exists because a wrong 'impossible' was published here once already: the "
            "chain was called unreconstructable on a query missing one parameter. The screen "
            "records the corrected route AND its length rather than either error.",
        ],
    ),
    Screen(
        family="swap_spread_dislocation",
        required_record="swap curve, deliverable Treasuries and funding, as of each date",
        source="a rates vendor; the free H.15 swap series was discontinued",
        status=VENDOR,
        reason=(
            "The Treasury leg is held from 1962. The swap leg is not: the free constant-maturity "
            "swap series stopped publishing, so the post-discontinuation curve is vendor-only. "
            "Half an identity is not an identity."
        ),
        held_source="fred_treasury_10y",
        how_to_verify="Check H.15 for a swap series with observations after its discontinuation.",
    ),
    Screen(
        family="inflation_breakeven_relative_value",
        required_record="TIPS breakevens, inflation swaps, CPI vintages and carry, point-in-time",
        source="FRED breakeven series already in this repo's vintage lake",
        status=HELD,
        reason=(
            "The breakeven leg is held daily and is an unrevised market quantity, so it is "
            "point-in-time by construction rather than by careful handling. The inflation-SWAP "
            "leg is vendor, so the swap-versus-breakeven formulation is not reachable — the "
            "breakeven-versus-realised one is."
        ),
        held_source="fred_breakeven_10y",
        notes=[
            "The best result in this screen, and it is narrower than it looks: what is held "
            "supports one formulation of the identity and not the other. Saying which is the "
            "difference between a screen and an encouragement.",
        ],
    ),
    Screen(
        family="mortgage_convexity_pressure",
        required_record=(
            "pool-level mortgage universe, durations and the rate surface, point-in-time"
        ),
        source="eMBS, Bloomberg or a dealer analytics feed",
        status=VENDOR,
        reason=(
            "Pool-level history and prepayment models are licensed products with no public "
            "analogue."
        ),
        how_to_verify="Price one pool-level history feed.",
    ),
    Screen(
        family="cross_currency_basis",
        required_record="FX forwards, OIS curves and fixings as of each date",
        source="an FX/rates vendor",
        status=VENDOR,
        reason=(
            "The basis is the residual of two curves. Spot is free; the forward points and the "
            "OIS curves that make the identity are not."
        ),
        how_to_verify="Check whether any free source carries forward points with a stable history.",
    ),
    Screen(
        family="fx_option_risk_reversal",
        required_record="FX option surfaces, forwards and calendars, point-in-time",
        source="an OTC FX options vendor",
        status=VENDOR,
        reason=(
            "OTC surfaces are composed from dealer contributions. Beyond the licence, the quotes "
            "are indicative — a composite is not an executable price."
        ),
        marks_are_indicative=True,
        how_to_verify="Ask a vendor whether the historical surface is composite or executable.",
    ),
    Screen(
        family="carbon_allowance_carry",
        required_record="contract rules, registry state and the futures curve, point-in-time",
        source="ICE settlement history plus the public EU transaction log",
        status=VENDOR,
        reason=(
            "The registry leg is public. The curve leg — which is what a carry identity trades — "
            "is exchange settlement data and licensed."
        ),
        how_to_verify="Check the exchange's redistribution terms for settlement history.",
    ),
    Screen(
        family="freight_derivative_dislocation",
        required_record="route assessments, contract terms and quotes, point-in-time",
        source="Baltic Exchange assessments",
        status=MARKS,
        reason=(
            "The route rates are ASSESSED by a reporting panel, not transacted. A backtest on "
            "them measures a panel's opinion of a rate. The licence is the smaller problem."
        ),
        marks_are_indicative=True,
        how_to_verify=(
            "Compare a month of assessments against cleared FFA settlement prices and see how "
            "far apart they are."
        ),
    ),
    Screen(
        family="crypto_liquidation_pressure",
        required_record="forced-liquidation events, trades and book snapshots, historically",
        source="exchange real-time streams (this repo already collects several venues)",
        status=NO_PIT,
        reason=(
            "The venues publish forced liquidations as a real-time stream and, at most, a short "
            "rolling window. The historical event record was never archived by the venue, so it "
            "cannot be bought or scraped after the fact — only collected forward from today."
        ),
        held_source="crypto_perp_funding_multivenue",
        how_to_verify=(
            "Query each collected venue for liquidations older than its rolling window and see "
            "whether anything comes back."
        ),
        notes=[
            "The one family here where the collector we already run is the answer — but only "
            "starting now. The contract's minimum is therefore a WAIT, and the wait is the "
            "finding.",
        ],
    ),
    Screen(
        family="catastrophe_bond_event_risk",
        required_record="trigger definitions, event notices and executable secondary marks",
        source="broker indication sheets",
        status=MARKS,
        reason=(
            "Secondary marks are weekly broker indications on a thin market. The triggers and "
            "event notices are obtainable; the prices to trade against are not."
        ),
        marks_are_indicative=True,
        how_to_verify="Compare indication sheets against actual secondary trade confirmations.",
    ),
    Screen(
        family="sovereign_cds_fx_dislocation",
        required_record="sovereign CDS curves, NDF/FX and credit events, point-in-time",
        source="a credit-derivatives vendor",
        status=VENDOR,
        reason="Sovereign CDS history is licensed with no public analogue at curve granularity.",
        how_to_verify="Price a sovereign CDS history file.",
    ),
)


def _untouched_families(atlas: dict[str, Any]) -> list[str]:
    """DERIVED, never listed. A family added to the atlas must appear here and fail the screen."""
    return sorted(
        f["id"]
        for f in atlas["families"]
        if f["lineage_classification"] == "NOVEL_ATLAS"
        and not (f.get("return_outcome") or {}).get("return_data_opened")
    )


def _verdict(screen: Screen, held: dict[str, Held], min_years: float) -> tuple[str, dict[str, Any]]:
    """Apply the contract arithmetic FIRST where a history is known, then the obtainability class.

    Order matters and is deliberate: a source we hold with two years of history is not 'obtainable
    from data we already hold' in any sense that helps, because the sleeve it could produce cannot
    be admitted. Reporting it as held would be true and useless.
    """
    years: float | None = None
    basis: str | None = None
    if screen.documented_history_years is not None:
        years, basis = screen.documented_history_years, screen.documented_history_basis
    elif screen.held_source and screen.held_source in held:
        source = held[screen.held_source]
        years, basis = source.span_years, f"MEASURED from {source.measured_from}"

    arithmetic = {
        "history_years": years,
        "history_basis": basis,
        "contract_minimum_years": min_years,
        "meets_contract_history": None if years is None else years >= min_years,
    }
    if years is not None and years < min_years and screen.status in (HELD, PUBLIC, EXTRACTION):
        return SHORT, arithmetic
    return screen.status, arithmetic


def main() -> int:
    atlas = json.loads(ATLAS.read_text())
    contract = json.loads(CONTRACT.read_text())
    min_obs = contract["thresholds"]["minimum_oos_observations"]
    min_years = round(min_obs / TRADING_DAYS_PER_YEAR, 2)

    expected = _untouched_families(atlas)
    screened = sorted(s.family for s in SCREENS)
    if screened != expected:
        raise AssertionError(
            "the screen does not cover exactly the untouched atlas families — unscreened: "
            f"{sorted(set(expected) - set(screened))}, screened but not untouched: "
            f"{sorted(set(screened) - set(expected))}"
        )

    held = {name: h for name, measure in SOURCES.items() if (h := measure()) is not None}

    rows = []
    for screen in SCREENS:
        verdict, arithmetic = _verdict(screen, held, min_years)
        rows.append(
            {
                "family": screen.family,
                "required_record": screen.required_record,
                "best_source": screen.source,
                "verdict": verdict,
                "what_the_verdict_means": MEANING[verdict],
                "reason": screen.reason,
                "obtainability_evidence_status": (
                    "MEASURED_FROM_THIS_REPO"
                    if screen.held_source and screen.status in (HELD, EXTRACTION)
                    else "JUDGEMENT_NOT_VERIFIED_THIS_RUN"
                ),
                "how_to_verify": screen.how_to_verify,
                "related_artifact": screen.related_artifact,
                "marks_are_indicative": screen.marks_are_indicative,
                "extraction_gated": screen.extraction_gated,
                "notes": screen.notes,
                **arithmetic,
            }
        )

    rows.sort(key=lambda r: (RANK.index(r["verdict"]), r["family"]))
    by_verdict: dict[str, list[str]] = {}
    for row in rows:
        by_verdict.setdefault(row["verdict"], []).append(row["family"])

    engineering = sum(len(by_verdict.get(v, [])) for v in (HELD, PUBLIC, EXTRACTION))
    result = {
        "schema": "canli.alphac-atlas-reachability-screen.v1",
        "claim_boundary": (
            "Screens obtainability only. Opens no return data, registers no hypothesis identity, "
            "runs no backtest, and claims nothing about any family's edge, sign, correlation or "
            "capacity. 0 trials."
        ),
        "what_is_measured": (
            "The family list, derived from the atlas rather than listed. The contract minimum, "
            "read from the contract in force. The history of every source this repo holds, "
            "re-derived from the lake on this run. The verdict, computed from those."
        ),
        "what_is_judged": (
            "Who holds a record this repo does NOT hold, and whether an as-of version of it was "
            "preserved at all. Every such row is stamped JUDGEMENT_NOT_VERIFIED_THIS_RUN and "
            "carries the concrete check that would settle it. None is presented as measured."
        ),
        "contract": {
            "minimum_oos_observations": min_obs,
            "trading_days_per_year": TRADING_DAYS_PER_YEAR,
            "minimum_history_years": min_years,
            "why_it_is_decisive": (
                "A candidate's return series cannot be longer than the source that produces it. A "
                "source with less history than this cannot supply an admissible sleeve however "
                "good the idea, so the arithmetic is applied BEFORE any judgement about the idea."
            ),
        },
        "sources_held": {
            name: {
                "first": h.first,
                "last": h.last,
                "span_years": h.span_years,
                "partitions": h.n,
                "measured_from": h.measured_from,
            }
            for name, h in sorted(held.items())
        },
        "families_screened": len(rows),
        "by_verdict": by_verdict,
        "headline": (
            f"{engineering} of {len(rows)} untouched families are blocked on engineering. The "
            f"other {len(rows) - engineering} are blocked on money, on a record that was never "
            "preserved, or on prices nobody could trade — none of which more work closes."
        ),
        "verdict_meanings": MEANING,
        "ranking": RANK,
        "families": rows,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"  contract minimum: {min_obs} obs = {min_years} years")
    print(f"  sources held and measured: {len(held)}")
    for name, h in sorted(held.items()):
        print(f"    {name:34} {h.first} .. {h.last}  {h.span_years:>6.2f}y  ({h.n} partitions)")
    print()
    for verdict in RANK:
        families = by_verdict.get(verdict, [])
        if families:
            print(f"  {verdict}  ({len(families)})")
            for fam in families:
                print(f"      {fam}")
    print(f"\n  {result['headline']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
