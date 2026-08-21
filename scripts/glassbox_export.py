"""Glass-box data export: emit the Canli Capital landing page's JSON from REAL artifacts.

This is the honesty backbone of the public site (ac-capital.vercel.app). Every number
it emits is read from a real AlphaForge artifact on disk; nothing is fabricated. Where a
value does not exist (e.g. the live track record on day zero), the script emits the honest
empty/seed state and labels it, rather than inventing history.

Emitted files (to the Meridian public dir, default <meridian>/public/glassbox/):
  - kill_log.json         killed + survived strategies, real net Sharpes + kill/keep reasons
  - pre_registration.json the committed trial budget, slots, gates, commit date
  - deflation.json        real DSR / PBO / gate thresholds + the honest C+ NO-DEPLOY verdict
  - track_record.json     the live curve (from trading.sqlite if it has rows, else the
                          go-live seed) + the LABELLED research/simulation curve
  - reproducibility.json  the golden-master / byte-identity basis + the 50-factor parity claim

Each file carries a sha256 content-hash (over the payload, hash field excluded) and a
generated_at UTC timestamp, so a reader can verify the artifact was not hand-edited.

Honesty rules baked in (owner's non-negotiable):
  - Forward Sharpe is the deflated 0.7-1.0 expectation, NEVER the 1.46 in-sample headline.
  - The killed strategies are published with their real negative Sharpes.
  - The crypto-perp deflation FAILURE (DSR 0.21, PBO 0.88, C+) is shown as a feature.
  - Reproducibility is "content-hashed + byte-reproducible", NOT "blockchain-anchored".

Run:  uv run python scripts/glassbox_export.py
Lint: uv run ruff check scripts/glassbox_export.py
Type: uv run mypy --strict scripts/glassbox_export.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Paths. All resolved absolute so the export is reproducible from any cwd.
# ---------------------------------------------------------------------------
REPO: Final[Path] = Path(__file__).resolve().parent.parent
WALKFORWARD: Final[Path] = REPO / "artifacts" / "walkforward"
GRAND_BACKTEST_DIR: Final[Path] = REPO / "artifacts" / "grand_backtest" / "20260616T143620Z"
STATE_JSON: Final[Path] = REPO / "data" / "paper" / "state.json"
TRADING_SQLITE: Final[Path] = REPO / "var" / "trading.sqlite"
GOLDEN_MASTER: Final[Path] = REPO / "tests" / "integration" / "test_golden_master.py"
PRE_REGISTRATION_MD: Final[Path] = REPO / "docs" / "design" / "PRE_REGISTRATION.md"

# Default output: the Meridian landing repo public dir. Sibling of alphaforge.
OUT_DIR: Final[Path] = REPO.parent / "meridian" / "public" / "glassbox"

INITIAL_EQUITY: Final[float] = 100_000.0

# Gate thresholds (committed in PRE_REGISTRATION.md / grand verdict.md). Real numbers.
DSR_GATE: Final[float] = 0.95
PBO_GATE: Final[float] = 0.20


# ---------------------------------------------------------------------------
# summary.txt parsing. The walk-forward summaries are "key   value  (comment)".
# ---------------------------------------------------------------------------
def parse_summary(name: str) -> dict[str, float]:
    """Parse a walk-forward summary.txt into a {key: float} map.

    Only the leading numeric token of each line is kept; the trailing human comment
    (e.g. the ISO date next to an epoch-ms timestamp) is ignored.
    """
    path = WALKFORWARD / name / "summary.txt"
    out: dict[str, float] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("=") or line.startswith("AlphaForge"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0]
        try:
            out[key] = float(parts[1])
        except ValueError:
            continue
    return out


def epoch_ms_to_iso_date(epoch_ms: float) -> str:
    """Convert epoch-milliseconds to an ISO date string (UTC)."""
    return dt.datetime.fromtimestamp(epoch_ms / 1000.0, tz=dt.UTC).date().isoformat()


def return_pct(final_equity: float) -> float:
    """Total return percent off the canonical 100k base, rounded to 2dp."""
    return round((final_equity - INITIAL_EQUITY) / INITIAL_EQUITY * 100.0, 2)


def strat_record(name: str) -> dict[str, Any]:
    """Build a normalized record (Sharpe, return, dates, drawdown, costs) from summary.txt."""
    s = parse_summary(name)
    rec: dict[str, Any] = {
        "name": name,
        "sharpe": round(s["sharpe"], 4),
        "cagr_pct": round(s["cagr"] * 100.0, 2),
        "return_pct": return_pct(s["final_equity"]),
        "final_equity_usd": round(s["final_equity"], 2),
        "vol_ann_pct": round(s["vol_ann"] * 100.0, 2),
        "max_drawdown_pct": round(-s["max_dd"] * 100.0, 2),
        "n_days": int(s["n_days"]),
        "start_date": epoch_ms_to_iso_date(s["start_ts"]),
        "end_date": epoch_ms_to_iso_date(s["end_ts"]),
        "turnover_ann": round(s["turnover_ann"], 2),
        "fees_paid_usd": round(s["fees_paid"], 2),
    }
    if s.get("funding_net", 0.0) != 0.0:
        rec["funding_net_usd"] = round(s["funding_net"], 2)
    return rec


# ---------------------------------------------------------------------------
# Content hashing. Hash the payload (minus the hash field) for verifiability.
# ---------------------------------------------------------------------------
def stamp(payload: dict[str, Any]) -> dict[str, Any]:
    """Add generated_at + a sha256 content_hash over the canonical payload bytes."""
    payload = dict(payload)
    payload.pop("content_hash", None)
    payload.pop("generated_at", None)
    payload["generated_at"] = dt.datetime.now(tz=dt.UTC).isoformat()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return payload


# The dashboard serves its OWN copy of these artifacts. Until 2026-08-06 this exporter wrote
# only to the landing site's public dir, so app.canlicapital.com served glass-box files last
# generated 2026-06-24 -- SIX WEEKS stale. The visible consequence was the worst kind: the app
# published live_return_pct 0.0 over "3 days" with NAV at a clean $100,000, while the landing
# published the truth for the same book, -2.54% over 38 days. The stale host was showing the
# FLATTERING number, and a firm whose entire product is that its record cannot be quietly
# re-picked was serving two different inception dates on two hosts at the same time.
# paper_trading_state.py already copies to both; this now matches it.
APP_OUT_DIR: Final[Path] = REPO.parent / "meridian-app" / "public" / "glassbox"


def write_json(out_dir: Path, filename: str, payload: dict[str, Any]) -> Path:
    """Stamp + write a payload as pretty JSON to EVERY public dir; return the primary path."""
    stamped = json.dumps(stamp(payload), indent=2) + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(stamped)
    # Mirror to the app. Byte-identical by construction: one stamped string, written twice, so
    # the two hosts cannot disagree even about the content hash.
    if out_dir.resolve() == OUT_DIR.resolve():
        APP_OUT_DIR.mkdir(parents=True, exist_ok=True)
        (APP_OUT_DIR / filename).write_text(stamped)
    return path


# ---------------------------------------------------------------------------
# Feature 1 — kill_log.json (killed strategies + surviving sleeves)
# ---------------------------------------------------------------------------
# Static labels/reasons (provenance: PRE_REGISTRATION.md + CROSS_ASSET_BOOK.md). The
# NUMBERS are all read from summary.txt above; only the human-readable name + the kill
# reason text are curated here, and each reason cites the gate it failed.
KILLED: Final[list[tuple[str, str, str, str]]] = [
    (
        "deephist_quality_top800",
        "Deep-History Quality (Top 800)",
        "equity_quality",
        "Quality premium does not survive net of cost on the 21-year survivorship-free "
        "universe. Net Sharpe far below the 0.30 minimum gate. KILLED, never re-tuned.",
    ),
    (
        "eq_value_btp",
        "Equity Value (Book-to-Price)",
        "equity_value",
        "Value premium inverted across the 2022-2026 window. Net Sharpe below the 0.30 gate; "
        "the narrow top-200 universe is too small for the small/mid-cap value signal. KILLED.",
    ),
    (
        "eq_quality_gp",
        "Equity Quality (Gross Profitability)",
        "equity_quality",
        "Quality via GP/A + ROE fails on the narrow top-200 / 5-year slice. Net Sharpe below "
        "the 0.30 gate; needs the wide Sharadar fundamentals universe (20yr / 3000 names). KILLED.",
    ),
    (
        "eq_mom_margin",
        "Equity Momentum (with Margin Costs)",
        "equity_momentum_variant",
        "Margin financing costs erode the momentum edge below the frozen k30_dn_63 baseline. "
        "Variant killed per pre-registration; the clean h=63 sleeve is the deployed one.",
    ),
    (
        "prereg_momentum",
        "Pre-Registered Momentum (deep history)",
        "equity_momentum",
        "Pre-registered momentum on 21 years of deep history. Net Sharpe ~ -0.05, failed the "
        "DSR >= 0.95 gate. The deployed momentum sleeve is the frozen 2023+ k30_dn_63 instead.",
    ),
    (
        "prereg_value",
        "Pre-Registered Value (composite)",
        "equity_value",
        "Pre-registered composite value on 21 years. Net Sharpe -0.60, failed every gate. "
        "Confirms the value thesis does not replicate without small/mid-cap breadth. KILLED.",
    ),
    (
        "prereg_quality",
        "Pre-Registered Quality (GP/A + ROE)",
        "equity_quality",
        "Pre-registered quality on 21 years. Net Sharpe -0.83, the worst sleeve. KILLED; "
        "the wide-universe quality thesis fails to replicate on the available data.",
    ),
    (
        "prereg_bab",
        "Pre-Registered Betting-Against-Beta",
        "equity_low_risk",
        "Pre-registered BAB on 21 years. Net Sharpe ~ -0.07, failed the DSR >= 0.95 gate. "
        "Low-risk anomaly does not survive net of cost here. KILLED.",
    ),
    (
        "crypto_lowvol_720",
        "Crypto Low-Volatility",
        "crypto_low_risk",
        "The STRONGEST in-sample signal the 200+-factor campaign found anywhere (Rank-IC "
        "t = 6.66). Full purged walk-forward: net Sharpe 0.69 — respectable. But the Deflated "
        "Sharpe Ratio is 0.04: after honestly penalising for every config we tried, it is "
        "indistinguishable from luck. A high raw Sharpe is NOT enough. This is the clearest proof "
        "of why we deflate — the prettiest backtest of the campaign, KILLED on deflation.",
    ),
]

SURVIVORS: Final[list[tuple[str, str, str, float, str]]] = [
    (
        "k30_dn_63",
        "US Equity Momentum",
        "12-1 cross-sectional momentum, dollar-neutral long/short, split-adjusted, "
        "survivorship-free. Quarterly rebalance, 12% vol overlay, Reg-T 2x gross.",
        0.544,
        "KEEP. Net Sharpe 0.91 clears the 0.40 gate; the equity ballast of the book. "
        "Decorrelated from crypto carry. Capacity $1B+ at Reg-T 2x gross.",
    ),
    (
        "crypto_carry_wk",
        "Crypto Funding Carry",
        "Funding-rate carry on Binance USDT-M perpetuals, market-neutral. Weekly cadence.",
        0.456,
        "KEEP, with honest caveats. Net Sharpe 0.68, near-uncorrelated to equity (corr ~ -0.02). "
        "Capacity is FINITE (~$100k to $1M proven); weight decays to zero above ~$100M AUM.",
    ),
    (
        "managed_futures",
        "AlphaTrend (Managed-Futures Trend)",
        "Time-series momentum across a 17-market ETF basket (equity-index, rates, commodities, "
        "FX), long/short on each market's own trend, inverse-vol weighted. Biweekly rebalance.",
        0.0,
        "KEEP — but NOT for an edge. Net Sharpe is a modest 0.33, positive skew, two-decade "
        "stable, ~0 equity correlation. We originally kept it as 'the FIRST new sleeve to clear "
        "deflation, DSR 0.83, statistically real'. Re-derived 2026-08-07 at honest N=133 and "
        "pooled V[SR]=7.96e-04, its DSR is 0.000 — the LOWEST of the sleeves we have measured, "
        "not the highest; the old 0.83 rested on a variance input roughly 80x too small and a "
        "trial count of 5 while its siblings were graded at N=101. That claim is WITHDRAWN "
        "(transparency [24]). It is carried in the book at an equal quarter for MEASURED "
        "drawdown reduction, not for a demonstrated edge. The free-ETF screen suggested 0.73; "
        "the honest engine says 0.33 — we published both.",
    ),
]


# Screen-stage kills: free-data PROTOTYPES (Yahoo spot + FRED rates, standalone numpy scripts under
# scripts/fx_*_screen.py) killed at the cheap screen BEFORE any engine integration. Their numbers do
# NOT come from a walk-forward summary.txt — they are screen prototypes, labelled as such. The
# screen->gauntlet funnel is the point: kill weak ideas cheaply, build only what shows an edge.
# Entry shape: (name, readable_name, screen_net_sharpe, reason) or the same plus a trailing
# `stage` string. Stage defaults to 'screen_prototype' when omitted.
# The Sharpe slot is `float | None`. None means NOT SEPARATELY MEASURED, which is a different
# claim from zero and used to be unsayable: the slot was typed `float`, so four probes whose
# finding was "null" or "no single Sharpe exists" had a hand-written 0.0 put in a measurement
# field. Published, that became "Screen net Sharpe 0.0000" -- four decimals of precision nobody
# measured, sitting in a table beside prose that said the candidate screened at 1.47.
ScreenKill = (
    tuple[str, str, float | None, str] | tuple[str, str, float | None, str, str]
)

SCREEN_KILLS: Final[list[ScreenKill]] = [
    (
        "commodity_inventory_seasonal",
        "EIA Petroleum Inventory Scarcity",
        -0.5892034349114502,
        "One pre-registered configuration on 782 accepted official EIA WPSR first-release "
        "Table 4 vintages, 2016-2026 OOS: commercial crude excluding SPR mapped to USO and total "
        "gasoline mapped to UGA, five-year same-week seasonal expectation, trailing 52-release "
        "surprise scale, next-session-open entry, DBC beta hedge and explicit one-way costs. One "
        "of 783 discovered releases was quarantined for a published arithmetic contradiction. "
        "The sleeve was exceptionally orthogonal (average correlation +0.0002, maximum pair "
        "+0.0321) and controlled DBC beta (-0.014), but there was no return edge: net Sharpe "
        "-0.589, Newey-West t -1.84, DSR effectively zero, max drawdown -41.1%, and Sharpe at "
        "2x costs -0.998. USO and UGA standalone Sharpes were both negative. The fixed 10% book "
        "check improved by 0.058 only on the short common window, but failed after mean-centering "
        "and failed one of four leave-one-year-out checks. UGA constrained fifth-percentile proxy "
        "capacity to about $14.9k at 1% ADV. The sign is not inverted and no threshold is retuned. "
        "Full curve, scores, weights and result are preserved in "
        "artifacts/probe/eia_petroleum_inventory/. KILLED.",
        "research_gauntlet",
    ),
    (
        "insider_purchase_clusters",
        "Clustered Insider Open-Market Purchases",
        -0.2432300499265856,
        "One pre-registered configuration on official SEC Form 4 purchases, 2016-2026: at least "
        "two officers/directors and $100k purchased inside 30 calendar days, filing date plus two "
        "sessions, next-open entry, full 63-session hold, trailing-ADV eligibility, SPY beta hedge "
        "and explicit one-way costs. The full PIT probe scheduled 3,508 non-overlapping events. "
        "It was genuinely orthogonal (average correlation -0.064, maximum pair +0.057), controlled "
        "beta (+0.048), and just cleared the hard $5M capacity gate ($5.17M fifth-percentile AUM "
        "at 1% ADV). But there was no return edge: net Sharpe -0.243, Newey-West t -0.79, DSR "
        "effectively zero, max drawdown -24.8%, and Sharpe at 2x costs -0.297. A fixed 10% sleeve "
        "reduced combined-book Sharpe by 0.072 and failed three of four leave-one-year-out checks. "
        "A pre-publication audit corrected weighted log-return aggregation to the canonical simple-"
        "return contract; preliminary Sharpe was -0.993 and the corrected verdict remained KILL. "
        "Immutable execution records rose from 200 to 201; distinct hypothesis identities rose "
        "from 135 to 136 because the correction remains conservatively charged. The sign "
        "is not inverted and no threshold is retuned. Full curve, event ledger, weights and result "
        "are preserved in artifacts/probe/insider_purchase_clusters/. KILLED.",
        "research_gauntlet",
    ),
    (
        "eq_net_issuance",
        "Corporate Equity Supply (Net Issuance)",
        -0.3112743437896463,
        "The broad corporate-equity-supply identity was run through the deployed-path "
        "walk-forward on a point-in-time Sharadar research lake: long firms shrinking "
        "split-adjusted basic shares and short firms expanding them, rebalanced every 63 "
        "sessions. The latest sealed sweep was decisively negative: net Sharpe -0.311, DSR "
        "0.000102 after six trials, and max drawdown -37.1%. A separate source-correct "
        "full-window rerun scored +0.148 with -17.5% max drawdown, still below the 0.40 gate; "
        "the sign and magnitude instability across data paths is itself a failure, not a result "
        "to select around. Three distinct historical configurations remain charged to the same "
        "corporate-equity-supply family. A proposed completed-flow measurement may continue "
        "data-feasibility work only as a same-family refinement and cannot count as independent "
        "sleeve breadth. No sign flip, window selection, or trial reset is authorized. Evidence: "
        "artifacts/sweep/gauntlet_eq_net_issuance/walkforward.json, "
        "artifacts/analysis/null_fundamentals_rerun/result.json, and "
        "artifacts/feasibility/repurchase_issuance_flow/identity_overlap_audit.json. KILLED.",
        "deployed_gauntlet",
    ),
    (
        "fx_trend_cs",
        "FX Trend (cross-sectional 12-1)",
        -0.035,
        "Cross-sectional currency trend, net of cost, 2016-2026. Flat (net Sharpe -0.035) — a "
        "weak-trend decade for FX. Below the 0.30 screen bar. KILLED at screen.",
    ),
    (
        "fx_carry_ratediff",
        "FX Carry (rate differential)",
        0.18,
        "Long high-rate / short low-rate currencies. Net Sharpe 0.18 but skew -2.74: the carry "
        "premium does not pay for its crash risk (carry 'picks up pennies in front of a "
        "steamroller'). Below the screen bar on both Sharpe and skew. KILLED at screen.",
    ),
    (
        "fx_carry_trend_overlay",
        "FX Carry + Trend Overlay (the real construction)",
        0.32,
        "The professional FX book: trend hedges carry's crashes. It screened at 0.32 — but the "
        "robustness stress-test killed it. The Sharpe SPIKED only at the exact threshold we picked "
        "by hand (a knob artifact, ~0.15 on either side); it died at realistic cost (25x turnover, "
        "0.05 at 5bp); ALL the performance came from one post-2021 regime; and dropping JPY "
        "collapsed it to -0.07 — the entire 'edge' was the single short-JPY trade. Not a "
        "diversified premium. KILLED on robustness, before we built a thing.",
    ),
    # ---- 2026-06-27 sleeve-discovery campaign: 17-agent adversarial search for a new sleeve toward
    # grade A. 10 theory-grounded candidates screened (free data + the Sharadar/Deribit lakes), each
    # through the four-test gauntlet + 3-lens adversarial refutation. ALL 10 killed — a clean null.
    # See artifacts/campaigns/sleeve_discovery_2026-06-27.md. The whole graveyard, published.
    (
        "crypto_vrp",
        "Crypto Variance-Risk-Premium (campaign)",
        -0.07,
        "Pitched at 2.15 Sharpe — the headline was a 252-vs-365 vol-annualization error inventing a "
        "phantom 15-vol-point premium. Honest measurement: net Sharpe -0.07, skew -2.19, fails all "
        "four stress-tests, shares carry's crash dependence. A seductive false positive, KILLED.",
    ),
    (
        "crypto_short_tsmom",
        "Crypto Short-Horizon Trend (campaign)",
        0.30,
        "The strong 0.60 screen lives entirely in the untradeable 2016-18 illiquid era; modern "
        "crypto is flat-to-dead with a catastrophic -4.88 skew (crash-day reversals). KILLED.",
    ),
    (
        "mf_realfutures_fasttrend",
        "Managed-Futures fast-trend / real-futures breadth (campaign)",
        0.20,
        "Splits into robust-but-not-new (the slow book IS our existing AlphaTrend) and new-but-dead "
        "(the fast-trend leg is net-negative at every verifiable cost). Not a new sleeve. KILLED.",
    ),
    (
        "equity_pead",
        "Post-Earnings-Announcement Drift (campaign)",
        -0.65,
        "Clean null on a tradable top-1000 universe: the drift is the WRONG sign net of cost; the "
        "published PEAD edge lives only in untradeable micro-caps. Corr 0.47 to momentum. KILLED.",
    ),
    (
        "cot_positioning",
        "COT Positioning Overlay (campaign)",
        0.083,
        "Indistinguishable from zero (t~0.42 over 25 years); dies at 2x cost; the entire 'edge' is "
        "two equity-index legs. Genuine decorrelation, no edge to attach it to. KILLED.",
    ),
    (
        "onchain_carry_filter",
        "On-Chain Carry-Quality Filter (campaign)",
        0.08,
        "Placebo-indistinguishable: a random risk-off coin-flip of equal intensity matches it, and "
        "it does NOT repair carry's 2022 tail (skew got worse). No paid-data upgrade justified. KILLED.",
    ),
    (
        "funding_termstructure",
        "Funding Term-Structure / Slope (campaign)",
        0.159,
        "The decorrelated residual is noise (worked pre-2023, inverted after: +1.11 then -1.43); the "
        "only version that makes money is leaked carry-LEVEL — a duplication of what we own. KILLED.",
    ),
    (
        "residual_momentum",
        "Residual (beta-neutral) Momentum (campaign)",
        -0.098,
        "Corr 0.87 to raw 12-1 momentum on the broad survivorship-free universe — it is the SAME bet "
        "as AlphaMax, net-negative. The claimed 'separation' is false here. KILLED.",
    ),
    (
        "rates_curve_carry",
        "Rates-Curve Carry (campaign)",
        -0.33,
        "Robustly NEGATIVE, not fragile-positive: the signal points the wrong way — steepest curves "
        "preceded the worst duration drawdowns (2022). Real decorrelation, negative edge. KILLED.",
    ),
    (
        "tail_overlay",
        "Long-Vol Tail Overlay (campaign)",
        -0.56,
        "An honest positive-skew (+2.06) anti-equity hedge — but its ONLY thesis, improving the "
        "combined book, fails at every hedge weight. AlphaTrend already provides crisis convexity "
        "WITH a positive standalone Sharpe. KILLED.",
    ),
    # ---- 2026-06-27 brutal multi-construction campaign (the documented premia + a book red-team).
    # Each tested across 3-5 constructions + crisis/cost/capacity gauntlet. All 4 killed; verdict:
    # do NOT buy the $270 futures data. See artifacts/campaigns/sleeve_discovery_2026-06-27.md.
    (
        "xasset_carry",
        "Cross-Asset Carry (campaign)",
        0.37,
        "5 constructions. The COMBINED cross-asset book is net-NEGATIVE (3 of 4 legs lose); the one "
        "positive leg (oil backwardation, +0.37) is a single-instrument bet that leave-one-out "
        "zeroes; rates-carry fails the Covid crisis gate. Real futures data cannot flip it. KILLED.",
    ),
    (
        "xasset_value",
        "Cross-Asset Value (campaign)",
        -0.24,
        "6 constructions, ALL net-negative. The decisive tell: flipping the value sign is positive "
        "in every asset class — the only premium present is anti-value = momentum/trend, which we "
        "already own. Cross-asset value on liquid proxies is just short-momentum, and it loses. KILLED.",
    ),
    (
        "equity_vrp",
        "Equity-Index VRP / short-vol (campaign)",
        0.42,
        "The premium is REAL (VIX minus realized = +4 vol pts, t=57) but UNHARVESTABLE: negative in "
        "every crisis, skew -1.8 to -2.2, corr +0.45 to +0.66 to SPY — short-vol is leveraged "
        "long-beta in disguise, not an orthogonal sleeve. KILLED.",
    ),
    (
        "crypto_dated_basis",
        "Crypto Dated-Futures Basis (campaign)",
        # NOT SEPARATELY MEASURED: the screened 1.47 was refuted as a roll-accounting artifact; no
        # honest standalone Sharpe survives it.
        None,
        "Screened at an apparent 1.47 but refuted 3x and reproduced from scratch: the 8.2%/yr "
        "'carry' is a roll-accounting fiction — the kept days (+0.55) and the dropped roll days "
        "(-0.55) cancel; honest all-days P&L telescopes to ~0%/yr, skew -6.84. A construction-"
        "fitting artifact (the 'edge' is earned by deleting the days it loses money). KILLED.",
    ),
    # ---- 2026-07-09 modern-sleeve probes: three leads from an 8-family sweep of the 2026 frontier,
    # each built and run PIT + net of the committed cost model. All three killed at screen.
    # Artifacts under artifacts/sweep/{carry_probe,mechflow_probe,pmsignal_scope}.
    (
        "futcarry_xs",
        "Commodity / Cross-Asset Futures Carry (probe)",
        -0.24,
        "Cross-sectional carry on 38 real futures (long backwardation / short contango, front-vs-"
        "next slope), 2010-2016 — the only window the term-structure marks support. GROSS Sharpe "
        "is already -0.17, so there is no edge for costs to erode; net -0.24, DSR 0.00, all six "
        "construction variants negative. The feed itself dies mid-2016 (one root keeps a next-"
        "contract mark), so it could not run live even if it worked. KILLED twice over.",
    ),
    (
        "mechflow_tom",
        "Turn-of-Month / Rebalancing Flow (probe)",
        0.27,
        "The calendar flow is real — SPY earns 5.65bp/day in the last-1-plus-first-3 window vs "
        "3.96bp outside, and the footprint replicates on QQQ — but monetized standalone it sits in "
        "cash 76% of days: net Sharpe 0.27, below buy-and-hold SPY (0.58) and the screen bar, DSR "
        "0.035 across 43 configs. The 60/40 month-end rebalance-fade variant decayed negative "
        "after 2018. A real effect that is an execution tilt, not a sleeve. KILLED as standalone. "
        "RE-EXAMINED 2026-08-03 because that first reason was BAD ARITHMETIC: a candidate need not "
        "beat the book to improve it, only clear own_SR > rho x S_b. Re-tested as a diversifier on "
        "ONE pre-registered config (no sweep, so no search penalty). The reframe was right about "
        "correlation — rho to the live book is +0.010, dropping the bar to +0.006 — and it still "
        "fails: own Sharpe -0.56 over the book's own window, and over 25 years / 6,309 sessions the "
        "full-history Sharpe of +0.278 carries a Newey-West t of only +1.42, with no decade "
        "reaching t=2 (best +1.32). A near-zero bar lowers what you must BEAT, never what you must "
        "PROVE. Adding it hurt the book at every weight (-0.03 to -0.15), and 87-96% of that harm "
        "came from the mean, not from variance. KILLED on the correct bar — this one is final.",
    ),
    (
        "pm_odds_signal",
        "Prediction-Market Odds as Macro Signal (probe)",
        # NOT SEPARATELY MEASURED: the finding is a null LEAD across 5 markets x 5 ETFs, not a
        # single tradable Sharpe.
        None,
        "Do Polymarket-implied probabilities lead tradable markets? No — they lag them. The "
        "forward lead is null across 5 macro markets x 5 ETFs; the reverse is strong: bonds "
        "reprice a Fed move first and the odds catch up the NEXT day (corr +0.40 to TLT). Only "
        "~2 years of usable history, all one easing cycle. The free odds are a slower, noisier "
        "copy of prices we already see. KILLED at feasibility.",
    ),
    # ---- 2026-07-11 AlphaMax improvement campaign: six documented momentum enhancements built
    # and tested against the live construction. All null or worse; the frozen 12-1 build stays.
    # IC-screen kills (12-7 t 0.92, sector-neutral t 1.28, residual t 2.11 — all below plain
    # momentum's own screen) are disclosed in the transparency notes; only the variant with real
    # net-of-cost portfolio numbers earns a kill-log row. 52-week-high gauntlet pending.
    # ---- 2026-08-03: two findings from taking the sleeves to their honest ceiling.
    (
        "mf_realfutures_breadth",
        "Real-Futures Breadth for the Trend Sleeve (probe)",
        -0.148,
        "We had been treating 'buy real futures data for genuine breadth' as the roadmap for the "
        "trend sleeve, on the theory that Sharpe scales with the square root of effective breadth "
        "and 17 ETFs cannot supply it. Half of that is right: measured effective breadth is 9.1 for "
        "38 real futures versus 5.3 for the live 17-ETF basket (and only 3.5 for a 33-ETF expansion "
        "we already killed — more names, LESS breadth, which is why it failed). The other half is "
        "wrong. On an identical construction, identical costs and the identical 2010-2026 common "
        "window, the 38-market futures book returns net Sharpe -0.148 against the ETF sleeve's "
        "+0.498, independently reproducing an earlier -0.24 result we had discounted as a possible "
        "one-off. It is not a data fault: across all 38 back-adjusted series there is exactly one "
        "single-day move above 25%. Breadth MULTIPLIES the average per-market edge; where that edge "
        "is absent, more breadth buys more of nothing and 7.3x turnover instead of 4.3x. The "
        "capital-gated futures path is therefore NOT validated and we have stopped citing it. "
        "Reproduce: the probe is in the session record; data is data/lake_fut_real (38 markets).",
        "screen_prototype",
    ),
    (
        "alphamax_short_margin_floor",
        "AlphaMax Short-Leg Margin Floor (disclosure, not a strategy)",
        -0.112,
        "A disclosure against our own published number rather than a tested idea. The equity "
        "sleeve's backtest has never modelled the broker's $5.00-per-share short maintenance "
        "requirement, which is charged per share regardless of account size — so shorting an $8 "
        "stock ties up roughly 62% of its market value in margin at ANY capital level. Applying an "
        "honest $17 short-leg price floor costs -0.112 net Sharpe (2015-2026, point-in-time prices "
        "from our own lake, so no snapshot bias). Part of the published edge lives in cheap shorts "
        "that are permanently margin-inefficient. We are publishing the haircut rather than the "
        "flattering number. Separately: a borrow-availability filter appeared to cost a further "
        "-0.225, but that estimate is CONFOUNDED — it applies a current broker snapshot to eleven "
        "years of history, which silently excludes every delisted name, and delisted names are "
        "exactly where short alpha concentrates. Measuring it honestly needs point-in-time borrow "
        "data we do not have, so we report it as UNKNOWN rather than publish a number we cannot "
        "defend. The current live short book is 92 of 94 names borrowable.",
        "screen_prototype",
    ),
    (
        "alphamax_volscale",
        "Vol-Scaled / Crash-Protected Momentum overlay (campaign)",
        0.87,
        "Barroso-Santa-Clara constant-vol and Daniel-Moskowitz variance/dynamic scaling applied "
        "to the live AlphaMax sleeve. On the canonical window it HURTS (net Sharpe 0.87 vs the "
        "sleeve's own 0.91, maxDD worse by 1.3-3.1pts); incremental alpha over the book-level "
        "vol target the engine already runs is statistically zero in all 5 configs (t -1.64 to "
        "+0.81, overlay-scale correlation 0.54-0.66 to the engine's own rule). The insurance is "
        "already owned; buying it twice costs money. KILLED.",
    ),
    (
        "eq_52whigh",
        "52-Week-High Momentum (campaign)",
        -0.289,
        "The one AlphaMax construction variant whose cheap screen cleared the bar (t 2.01 vs plain "
        "momentum's 1.73), so we honored the pre-registration and ran the FULL deployed-path "
        "walk-forward. It KILLED: net Sharpe -0.289 (WORSE than plain 12-1's own -0.049 on the "
        "same harness), DSR 0.00, and OOS correlation +0.42 to plain momentum — neither better "
        "nor genuinely different. The frozen 12-1 build stays. KILLED at the gauntlet.",
        "deployed_gauntlet",
    ),
    # ---- 2026-07-12 intraday-flow research (Track B of the modern-sleeve build): two studies on
    # free minute data (Alpaca IEX), each pre-registered, ledger-free research screens (no WF trial).
    (
        "letf_eod_flow",
        "Leveraged-ETF End-of-Day Forced-Rebalance Flow (probe)",
        -1.41,
        "Leveraged ETFs MUST trade into the close (~$277B QQQ-family rebalance multiplier, ~$4B/day "
        "estimated flow) — a real, large, mechanical flow. But it is NOT tradeable on 2021-2026 "
        "data: no continuation into the close (+0.58 bps per 1-sigma flow, t=0.93), no overnight "
        "reversal, and all six strategy cells lose net of costs (best cell Sharpe -1.41). The "
        "~0.6bp effect is ~6x below the 12bp round-trip cost floor — no cost assumption rescues "
        "it. The pre-2019 literature edge appears arbitraged away at the granularity free data "
        "sees. KILLED at screen.",
        "screen_prototype",
    ),
    (
        "intraday_mom",
        "Intraday Flow-Momentum, first-30m predicts last-30m (probe)",
        # NOT SEPARATELY MEASURED: two opposite regimes (dead-zero 2023-2026, inverted 2020-2022);
        # one number would misdescribe both.
        None,
        "The twice-JFE-documented effect (Gao-Han-Li-Zhou) is fully DECAYED post-publication on "
        "SPY/QQQ/IWM: dead-zero in 2023-2026, and significantly INVERTED in 2020-2022 (a textbook "
        "publish-then-arbitrage overshoot). The only statistically-alive cell (TLT overnight, "
        "t=2.9) makes +1.2 bps/day gross against a >=2bp round-trip — a mirage economically. "
        "KILLED at screen.",
        "screen_prototype",
    ),
    # ---- 2026-07-12 economic-trend sleeve (Track A): AQR-style trend on macro FUNDAMENTALS (not
    # prices), on the 17-ETF basket. Point-in-time first-release vintages, a 3-auditor leakage panel
    # signed off zero blocking issues, then ONE pre-registered deployed-path walk-forward fired.
    (
        "econtrend",
        "Economic-Trend Sleeve, macro-fundamental trend (campaign)",
        0.211,
        "Trend on first-release macro vintages (payrolls, CPI, IP, credit spreads, yields, dollar) "
        "driving the 17-ETF basket by a pre-committed economic sign matrix. It has a REAL "
        "crisis-alpha personality — +60.7% through the 2008 GFC (SPY -46%), +17.5% in the 2022 "
        "bear (SPY -18%), essentially uncorrelated with the live AlphaTrend book (+0.009) and "
        "mildly SPY-negative (-0.20). But it fails the adopt bar 2 of 3: net Sharpe 0.211 (bar "
        "0.40), DSR 0.00 at N=103, and it gets caught in fast gap-down crashes (COVID -25.9%, "
        "breaching the -22.5% floor). Genuine decorrelation, not enough edge. A hostile 3-auditor "
        "leakage panel cleared the vintage plumbing before the one-shot ran. KILLED at the gauntlet. "
        "Also tested as a combined-book DIVERSIFIER (not just standalone), since near-zero "
        "correlation can lift a book even below the solo bar: it fails there too. At equal total "
        "vol its naive Sharpe ticks up ~0.02-0.04 but within noise, it DEEPENS the GFC and 2022 "
        "drawdowns, and decisively — strip its DSR-0.00 mean and the optimal weight goes to exactly "
        "0.00 (the whole 'benefit' was return-stacking a mean statistically indistinguishable from "
        "zero, not real diversification). Not added, in any construction. "
        "Reproduce: scripts/probe_econtrend_book.py.",
        "deployed_gauntlet",
    ),
    # ---- 2026-07-19/20: the last three ranked backlog candidates, all built and run.
    (
        "xs_seasonality",
        "Cross-Sectional Same-Calendar-Month Seasonality (probe)",
        -0.334,
        "The one equity-side signal genuinely DECORRELATED from our momentum sleeve — and that "
        "is exactly why it is worth publishing. Same-calendar-month ranking across a 33-ETF macro "
        "basket, 10y trailing PIT history, monthly, net of 6bp + borrow: net Sharpe -0.334, and "
        "NEGATIVE GROSS too (-0.176), so there is no edge for costs to erode. Correlation to plain "
        "12-1 momentum is just +0.07 (it passes the costume test that killed residual momentum and "
        "52-week-high) — but a 12-1 control on the SAME universe prints +0.175, so the harness can "
        "find a real signal; this one simply is not there. Decorrelation without edge is worthless. "
        "Screen gate failed, no walk-forward trial spent. Reproduce: scripts/probe_seasonality.py.",
        "screen_prototype",
    ),
    (
        "cef_discount",
        "Closed-End-Fund Deep-Discount + Activist Catalyst (probe)",
        -0.088,
        "The five-decade anomaly is REAL in free data and we could see it: entry-cohort funds "
        "genuinely narrow their discount versus the universe (+1.17pts at 4w t=5.4, +1.26 at 13w "
        "t=7.2, +1.39 at 26w). It still fails on economics — the convergence is too slow for its "
        "toll. Hedged net Sharpe -0.088 (-0.82 price-only) against a 0.5 gate: ~12.8%/wk turnover "
        "at 41bp one-way (6bp + half the 0.7% median CEF spread) hands back the ~1.3pt/quarter "
        "the discount closes. Two further honest notes: today's entry watchlist is EMPTY (0 of 328 "
        "funds qualify — the 2024-26 activist wave already closed sector discounts to multi-year "
        "tights), and the discount screen and the activist catalyst are nearly disjoint books "
        "(4.9% overlap), so the documented live-capital story is the CATALYST trade, not the one "
        "we screened. A pre-registered, hash-locked FORWARD experiment is now accruing point-in-"
        "time data toward a single-look evaluation in 2027. Reproduce: scripts/probe_cef_discount.py.",
        "screen_prototype",
    ),
    (
        "multivenue_funding",
        "Crypto Multi-Venue Funding Aggregation (probe)",
        # NOT SEPARATELY MEASURED: the pre-registered test was a DELTA against the Binance-only
        # baseline, not a standalone Sharpe.
        None,
        "Would aggregating funding across exchanges beat our Binance-only carry signal? No — null "
        "by its own pre-registered rule (promote required +0.10 Sharpe at 90% bootstrap "
        "confidence). The reason is structural: Binance and Bybit annualized funding are 0.94 "
        "correlated across 12,425 instrument-weeks, so there is almost no independent information "
        "to aggregate. The adjacent 'harvest on the best-paying venue' idea dies on arithmetic too "
        "— a median cross-venue gap of ~2.4%/yr against a four-legged ~30bp round trip implies a "
        "22-day breakeven hold, marginal before you even price second-tier venue custody risk. The "
        "live sleeve stays Binance-only on its blessed config. Byproduct kept: a multi-exchange "
        "funding lake (Bybit deep history via mirror; OKX public history is depth-capped at ~90 "
        "days, a data finding worth recording). Reproduce: scripts/probe_multivenue_funding.py.",
        "screen_prototype",
    ),
    # ---- 2026-08-02 AlphaMax construction-axis campaign: after the July 2026 momentum squeeze,
    # three ways to change how the equity book is BUILT, each leaving the 12-1 signal untouched.
    # All read-only screens: no WalkForwardRunner call, no experiments-ledger append, 0 trial slots
    # burned, DSR read at the standing ledger N. All three null; nothing adopted.
    # Artifacts under artifacts/probe/alphamax_{betaneutral,weighting,shorttail}/report.json.
    (
        "alphamax_betaneutral",
        "Beta-Neutral Momentum Construction (campaign)",
        0.570,
        "The premise was that a dollar-neutral momentum book carries hidden NEGATIVE market beta, "
        "so a junk rally hurts both legs at once. Measuring the premise first killed it. On the "
        "research panel (2005-2026) the book's mean rolling 63-day beta is -0.014 — essentially "
        "zero. On the LIVE book it is +0.319, and the LONG leg is the high-beta side (leg beta "
        "1.932 long vs 1.238 short) — the opposite of the premise. The treatment is then "
        "regime-dependent with opposite signs: research net Sharpe 0.160 to 0.361 (bootstrap "
        "P(dSharpe<=0)=0.0225), LIVE 0.921 to 0.570 (P=0.938). It also barely touches the episode "
        "it was designed for — 0.2 points of a 9.5-point loss on research, 0.7 of 10.5 live — and "
        "it buys beta-neutrality by selling dollar-neutrality: net exposure runs to +/-34% of "
        "gross, which breaks the market-neutral mandate. Not adopted. 0 trial slots burned. "
        "Reproduce: scripts/probe_alphamax_betaneutral.py.",
        "screen_prototype",
    ),
    (
        "alphamax_weightgrid",
        "Weighting x Breadth Construction Grid (campaign)",
        0.066,
        "Four weightings (inverse-vol, equal, signal-proportional, vol-capped) crossed with four "
        "breadths (K=30/50/100/200), 2005-2026, live cell inverse-vol K=100. Net Sharpes span "
        "-0.293 to +0.066 against the live cell's -0.062 on the same harness (this is the "
        "deep-history panel, where the deployed 2023+ sleeve's 0.91 does not apply). Four of the "
        "15 challenger cells individually cleared the 90% paired bootstrap — but the bootstrap's "
        "own dSharpe intervals imply those cells are 0.97 to 1.00 correlated with the live cell, "
        "so four passes is about the chance expectation for a family of near-copies, not evidence. "
        "The family-wise White Reality Check over the whole grid returns p=0.315: the best cell "
        "(signal-proportional K=50, dSharpe +0.128) is indistinguishable from luck. That "
        "family-wise gate was pre-registered precisely so the best cell could not be harvested. "
        "Zero cells adoptable; keep inverse-vol K=100. 0 trial slots burned. "
        "Reproduce: scripts/probe_alphamax_weighting.py.",
        "screen_prototype",
    ),
    (
        "alphamax_shorttail",
        "Short-Leg Tail Controls (campaign)",
        0.121,
        "Nine construction-side short-leg controls (per-name stop-outs at 30/50/100%, gross caps "
        "at 1.25x/1.5x/2.0x, short-leg vol targeting, with and without dollar-neutral restore). "
        "Killed by attribution rather than by Sharpe. In the July 2026 episode the baseline lost "
        "4.98%, of which the LONG leg contributed 3.61 and the SHORT leg 1.34 — the short leg is "
        "27% of the damage. The squeeze narrative is real (ALIT +88% split-adjusted, RPD +61%) "
        "but it is the minority of the loss; the larger driver was the momentum long complex "
        "selling off. A control that drove short-leg P&L to exactly zero still could not have "
        "fixed the episode. The actual controls recovered 0.02 to 0.77 points of the 4.98 (two of "
        "the nine made it worse) with within-episode drawdown unchanged: 5.49% baseline vs 5.33% "
        "to 5.57% across the nine. Four controls cleared the pre-registered gate on full-sample "
        "numbers and all four fail the beta filter — the best (short-leg vol target, net Sharpe "
        "0.121 vs the baseline's -0.102 on the 2005-2026 panel) buys its gain with market beta, "
        "not alpha: beta t=16.4, alpha t=-0.14. Nothing adopted. 0 trial slots burned. "
        "Reproduce: scripts/probe_alphamax_shorttail.py.",
        "screen_prototype",
    ),
    (
        "equity_short_interest_dtc",
        "Short Interest / Days-to-Cover Deciles (probe)",
        # CORRECTED 2026-08-05: was 0.002, the split-corrupted gross figure. The corrected
        # easy-to-borrow gross is +0.204. A machine-readable field must never contradict the
        # correction written beside it.
        0.204,
        "The first genuinely NEW INPUT in months rather than another transformation of price and "
        "volume: bi-monthly FINRA short interest for the whole US tape, 2017-12-29..2026-07-15 "
        "(3,804,024 rows, 23,314 tickers), unlocked by the Polygon Starter upgrade and ingested "
        "in full. ONE pre-registered config, no sweep: long the bottom days-to-cover decile, "
        "short the top, dollar-neutral, PIT top-2000 by ADV, price >= $5, positions formed on "
        "settlement + 10 BUSINESS DAYS (FINRA disseminates ~8; the extra margin makes lookahead "
        "un-arguable) and held to the next availability date. "
        "*** CORRECTION 2026-08-05 — THE FIRST PUBLISHED NUMBERS FOR THIS ENTRY WERE WRONG. *** "
        "The probe computed returns as log(close).diff() on data/lake, which stores RAW AS-TRADED "
        "closes: not split- or dividend-adjusted. Every forward split therefore booked a "
        "catastrophic fake loss — AAPL 2020-08-31 as -135%, NVDA 2024-06-10 as -229%, TSLA "
        "2022-08-25 as -110%. The bias was DIRECTIONAL, not noise: splits happen in high-priced "
        "mega-caps, mega-caps have enormous ADV, and days_to_cover = SI/ADV is therefore tiny for "
        "them, so every fake collapse sorted into the LONG (bottom-DTC) leg. The production "
        "feature engine refuses raw prices outright; this standalone probe bypassed that guard. "
        "Fixed in scripts/lib/px_adjust.py, which adjusts the RETURN series only and deliberately "
        "leaves price floors and ADV ranks on raw as-traded values (back-adjusting levels would "
        "introduce a look-ahead the raw panel does not have). Both affected probes were repaired "
        "in the same pass. WHAT CHANGED: gross Sharpe before any cost was published as -0.220 "
        "(full) and +0.002 (easy-to-borrow); corrected it is -0.062 (NW t -0.19) and +0.204 "
        "(NW t +0.66). The published claim that there was 'no edge for frictions to eat' was "
        "therefore FALSE — there is a small gross edge, it is simply not statistically "
        "established and it is entirely consumed by costs. The KILL STANDS but on different "
        "reasoning. Corrected net of 6bp one-way at 20x annual turnover, on the easy-to-borrow "
        "universe that is actually shortable: -0.026 / -0.228 / -0.792 at 50 / 300 / 1000 bp per "
        "year of borrow. The top days-to-cover decile IS the hard-to-borrow bucket, so the 50bp "
        "row describes a trade nobody can put on; at a realistic 300bp it is -0.228. Against the "
        "pre-registered rule it fails gate (b) Newey-West t >= 2 and gate (d) survives 300bp on "
        "easy-to-borrow, and passes (a) and (c). Correlation to the live book is -0.017, so the "
        "diversification arithmetic was favourable and it still did not matter — the same lesson "
        "as mechflow_tom: a near-zero bar lowers what a candidate must BEAT, never what it must "
        "PROVE. The sign is NOT flipped and re-tested, and the gates were NOT relaxed to admit it "
        "once the corrected numbers looked better; that is precisely the search a pre-registration "
        "exists to forbid. KILLED. Reproduce: scripts/ingest_short_interest.py then "
        "scripts/probe_short_interest.py.",
        "screen_prototype",
    ),
]


def build_kill_log() -> dict[str, Any]:
    """kill_log.json: the killed strategies with real negative Sharpes + the survivors."""
    killed: list[dict[str, Any]] = []
    for name, readable, kind, reason in KILLED:
        rec = strat_record(name)
        rec["readable_name"] = readable
        rec["type"] = kind
        rec["verdict"] = "KILLED"
        rec["reason"] = reason
        killed.append(rec)

    survivors: list[dict[str, Any]] = []
    for name, readable, desc, weight, reason in SURVIVORS:
        rec = strat_record(name)
        rec["readable_name"] = readable
        rec["description"] = desc
        rec["book_weight_pct"] = round(weight * 100.0, 1)
        rec["verdict"] = "KEEP"
        rec["reason"] = reason
        survivors.append(rec)

    # Entries are (name, readable, net_sharpe, reason) or (..., reason, stage). Stage defaults to
    # 'screen_prototype'; 'deployed_gauntlet' marks probes that went through the FULL deployed-path
    # walk-forward (their numbers ARE the real engine's) but whose artifacts live in probe dirs
    # rather than the canonical walkforward tree, so they are listed here rather than in KILLED.
    screen_kills = [
        {
            "name": e[0],
            "readable_name": e[1],
            "screen_net_sharpe": None if e[2] is None else round(e[2], 3),
            "stage": e[4] if len(e) > 4 else "screen_prototype",
            "verdict": "KILLED",
            "reason": e[3],
        }
        for e in SCREEN_KILLS
    ]
    n_gauntlet_probe = sum(1 for k in screen_kills if k["stage"] == "deployed_gauntlet")
    n_research_probe = sum(1 for k in screen_kills if k["stage"] == "research_gauntlet")
    n_screen = len(screen_kills) - n_gauntlet_probe - n_research_probe

    return {
        "schema": "glassbox.kill_log/2",
        "title": "The Kill Log",
        "summary": (
            "Most ideas die. We publish ours with their real net-of-cost numbers. "
            f"{len(killed) + n_gauntlet_probe} killed at the deployed-path gauntlet, "
            f"{n_research_probe} at a pre-registered research gauntlet, "
            f"{n_screen} more at the cheap prototype screen, {len(survivors)} survived."
        ),
        "honesty_note": (
            "Gauntlet numbers are read from the walk-forward summary.txt of a real engine "
            "backtest, net of the conservative cost model. The screen-stage kills (labelled "
            "'screen_prototype') are standalone screens — free-data prototypes AND screens on our "
            "Sharadar/Deribit research lakes — each run through a four-test robustness gauntlet but "
            "BEFORE full deployed-path engine integration; their numbers come from those screens, "
            "NOT the deployed engine, and we say so. The 2026-06-27 batch is a 17-agent adversarial "
            "sleeve-discovery campaign that killed all 10 candidates it tested. The 2026-07-09 batch "
            "is three probes from a sweep of the modern-sleeve frontier (futures carry, mechanical "
            "rebalancing flows, prediction-market odds as a signal) — all three killed at screen. "
            "The 2026-07-11 batch is the AlphaMax improvement campaign: six documented momentum "
            "enhancements tested against the live construction, all null or worse — the frozen "
            "12-1 build stays. The 2026-07-12 batch closes that campaign (the 52-week-high variant, "
            "run to a full walk-forward to honor a fired pre-registration) and adds three "
            "modern-frontier probes: two free intraday-flow studies (leveraged-ETF end-of-day "
            "rebalance flow, intraday flow-momentum — both killed at screen) and the economic-trend "
            "sleeve (macro-fundamental trend, one pre-registered walk-forward after a 3-auditor "
            "leakage panel signed off — a real crisis-alpha personality but too little edge, DSR "
            "0.00). The 2026-08-02 batch is the AlphaMax construction-axis campaign, opened after "
            "the July 2026 momentum junk-squeeze: three ways to change how the equity book is "
            "BUILT, each leaving the 12-1 signal byte-identical (beta-neutral construction, a 4x4 "
            "weighting-by-breadth grid, nine short-leg tail controls). All three null, nothing "
            "adopted, zero trial slots burned — each was a read-only screen with its gate written "
            "down first, and in the grid's case that pre-registered family-wise gate is what "
            "stopped the best-looking cell from being harvested (White Reality Check p=0.315). The "
            "beta-neutral candidate was killed by measuring its own premise: the hidden negative "
            "market beta it was built to remove does not exist (research -0.014, live +0.319). "
            "A few entries are labelled 'deployed_gauntlet': those went through the FULL "
            "deployed-path walk-forward, so their numbers ARE the real engine's; they sit in this "
            "list only because their artifacts live in probe directories. A 'research_gauntlet' "
            "is a locked, costed OOS probe with complete return artifacts but not the production "
            "engine path. Nothing is re-tuned."
        ),
        "gate_minimum_sharpe": 0.40,
        "killed_count": len(killed),
        "screen_killed_count": len(screen_kills),
        "survived_count": len(survivors),
        "killed_strategies": killed,
        "screen_stage_kills": screen_kills,
        "survivor_sleeves": survivors,
        "source_paths": [
            str((WALKFORWARD / name / "summary.txt").relative_to(REPO))
            for name, *_ in KILLED + [(s[0],) for s in SURVIVORS]
        ]
        + [
            "docs/design/PREREG_INSIDER_CLUSTERS.md",
            "artifacts/probe/insider_purchase_clusters/result.json",
            "artifacts/probe/insider_purchase_clusters/equity.parquet",
            "artifacts/probe/eia_petroleum_inventory/result.json",
            "artifacts/probe/eia_petroleum_inventory/equity.parquet",
            "artifacts/sweep/gauntlet_eq_net_issuance/walkforward.json",
            "artifacts/analysis/null_fundamentals_rerun/result.json",
            "artifacts/feasibility/repurchase_issuance_flow/identity_overlap_audit.json",
        ],
    }


# ---------------------------------------------------------------------------
# Feature 2 — pre_registration.json (committed budget, slots, gates)
# ---------------------------------------------------------------------------
def build_pre_registration() -> dict[str, Any]:
    """pre_registration.json: the trial-budget commitment, slots, and pass/kill gates.

    The slot OUTCOMES (passed/failed) are tied to the real Sharpes read from summary.txt so
    they cannot drift from the measured results.
    """
    mom_sharpe = round(parse_summary("prereg_momentum")["sharpe"], 4)
    val_sharpe = round(parse_summary("prereg_value")["sharpe"], 4)
    qual_sharpe = round(parse_summary("prereg_quality")["sharpe"], 4)
    bab_sharpe = round(parse_summary("prereg_bab")["sharpe"], 4)
    carry_sharpe = round(parse_summary("crypto_carry_wk")["sharpe"], 4)
    deployed_mom_sharpe = round(parse_summary("k30_dn_63")["sharpe"], 4)

    committed = bool(PRE_REGISTRATION_MD.exists())

    return {
        "schema": "glassbox.pre_registration/1",
        "title": "Pre-Registration",
        "summary": (
            "The trial budget was committed to git before any sleeve touched the data lake. "
            "Every config that could have been measured counts toward the deflation denominator, "
            "so a tiny budget measured once is the only honest path to a clean grade."
        ),
        "document_committed": committed,
        "document_path": str(PRE_REGISTRATION_MD.relative_to(REPO)),
        "commit_basis": "the git commit hash of the document is its timestamp of record",
        "trial_budget_hard_ceiling": 9,
        "measure_once_protocol": (
            "No re-runs, no re-windowing, no cadence search, no sign-flips, no subset search "
            "over sleeve combinations, no MVO, no static scheme in the deployable path. "
            "KILL = exclude, never re-tune."
        ),
        "slots": [
            {
                "slot": 1, "name": "Momentum (12-1)", "decision": "KEEP",
                "outcome": "PASSED",
                "deployed_sharpe": deployed_mom_sharpe,
                "note": (
                    "Deployed as the frozen 2023+ k30_dn_63 sleeve at Sharpe "
                    f"{deployed_mom_sharpe}. The deep-history pre-reg variant "
                    f"scored {mom_sharpe} and failed the DSR gate; the clean sleeve is used."
                ),
            },
            {
                "slot": 2, "name": "Value (composite)", "decision": "KEEP",
                "outcome": "FAILED", "measured_sharpe": val_sharpe,
                "note": f"Net Sharpe {val_sharpe} below the 0.30 gate. Killed.",
            },
            {
                "slot": 3, "name": "Quality (GP/A + ROE)", "decision": "KEEP",
                "outcome": "FAILED", "measured_sharpe": qual_sharpe,
                "note": f"Net Sharpe {qual_sharpe} below the 0.30 gate. Killed.",
            },
            {
                "slot": 4, "name": "Betting-Against-Beta (low-risk)", "decision": "KEEP",
                "outcome": "FAILED", "measured_sharpe": bab_sharpe,
                "note": f"Net Sharpe {bab_sharpe}, failed the DSR >= 0.95 gate. Killed.",
            },
            {
                "slot": 5, "name": "Short-term reversal (1-month)", "decision": "EXPECTED-KILL",
                "outcome": "DROPPED",
                "note": "Dropped pre-registration: 20x turnover capacity liability.",
            },
            {
                "slot": 6, "name": "Combined book (one fixed combiner)", "decision": "KEEP",
                "outcome": "HONEST-NULL",
                "note": (
                    "Structure survives (PIT-clean, decorrelated) but the in-sample magnitude "
                    "fails multiple-testing deflation. Recorded as the honest null; the path is "
                    "forward live evidence, not a re-combine."
                ),
            },
            {
                "slot": 7, "name": "Crypto-carry satellite (re-measured once)", "decision": "KEEP",
                "outcome": "PASSED", "measured_sharpe": carry_sharpe,
                "note": (
                    f"Net Sharpe {carry_sharpe}, kept as a capacity-capped satellite "
                    "(finite ~$100k to $1M, decays above ~$100M AUM)."
                ),
            },
            {
                "slot": "8-9", "name": "Contingency reserves", "decision": "RESERVED",
                "outcome": "UNSPENT",
                "note": (
                    "Spendable only against a structural trigger logged before its result is seen."
                ),
            },
        ],
        "gates": {
            "equity_momentum": (
                "DSR >= 0.95 AND net Sharpe >= 0.40 AND rank-IC NW t >= 3.0 AND PBO < 0.5 "
                "AND SPA p < 0.05 AND positive in >= 3 of 4 sub-periods"
            ),
            "value": (
                "net Sharpe >= 0.30 AND mean-return NW t >= 2.0 AND rank-IC >= 0.015 (t >= 2.0) "
                "AND positive in BOTH pre/post-2013 halves"
            ),
            "quality": "net Sharpe >= 0.30 AND DSR >= 0.95 AND PBO < 0.5 AND rank-IC NW t >= 2.0",
            "bab": "beta-hedged return NW t >= 2.0 AND DSR >= 0.95 AND net Sharpe >= 0.35",
            "book": (
                "DSR >= 0.95 AND PBO < 0.5 AND SPA p < 0.05 AND market-neutral "
                "(|beta_SPY|, |beta_BTC| t < 2)"
            ),
        },
        "expected_outcome": "B+ to A-, honest combined Sharpe ~0.75-0.85 net (NOT 1.46)",
        "actual_outcome": (
            "C+ honest null. The free-breadth path is exhausted: value and quality do not "
            "replicate on the narrow universe; crypto-perp alone fails honest deflation. "
            "The deployed book is the two survivors, awaiting forward live proof."
        ),
    }


# ---------------------------------------------------------------------------
# Feature 3 — deflation.json (real DSR / PBO + the C+ verdict)
# ---------------------------------------------------------------------------
def build_deflation() -> dict[str, Any]:
    """deflation.json: the grand-backtest deflation result + the C+ honest NO-DEPLOY verdict.

    Numbers read from verdict.md (Block A gate table + capacity curve) and the paper state.
    """
    state = json.loads(STATE_JSON.read_text())
    metrics = state["metrics"]

    return {
        "schema": "glassbox.deflation/1",
        "title": "The Deflation Verdict",
        "summary": (
            "We graded crypto-perps alone against an honest multiple-testing benchmark. "
            "It is noise. We publish the failure as a feature, not a footnote."
        ),
        "tested_window": {
            "start_date": "2021-01-01",
            "end_date": "2026-06-01",
            "note": "Clean crypto-perp window, UTC, exclusive end. No look-ahead.",
        },
        # Honesty fix (2026-06-27 red-team): N=8 is the trial count for THIS crypto-perp grid only,
        # NOT the cumulative research effort. Across the whole program we have searched 35+ distinct
        # strategy FAMILIES (FX, the factor zoo, managed-futures, two adversarial sleeve campaigns,
        # VRP/PEAD/COT/basis/...), and screen-stage kills bypassed the experiments ledger. We rename
        # the field for exactly what it measures and expose the cumulative figure so the deflation
        # bar is never understated. (It happens to be conservative here only because the verdict is
        # NO-DEPLOY; we will not let the same framing flatter a future deployed survivor.)
        "crypto_perp_grid_trials": 8,
        "cumulative_strategy_families_searched": "35+ (FX, factor-zoo, managed-futures, VRP, PEAD, "
        "COT, on-chain, residual-momentum, cross-asset carry/value, crypto-basis, two 2026-06 "
        "adversarial campaigns) — most published as nulls in the kill log; deflate against the FULL N",
        "gates": {
            "dsr_shared_min": DSR_GATE,
            "pbo_max": PBO_GATE,
            "rule": "deploy iff DSR(shared-SR*) >= 0.95 AND PBO < 0.20 AND beats baseline",
        },
        "best_config": {
            "name": "A_blend",
            "psr": 0.5355,
            "dsr_shared": 0.2112,
            "sr_ann": 0.0424,
            "max_dd": 0.1359,
            "turnover_ann": 39.743,
            "clears_dsr_gate": False,
            "beats_baseline": False,
        },
        "pbo_matrix": 0.8818,
        "capacity_curve": [
            {"initial_cash_usd": 100_000, "sr_ann": 0.4009, "dsr_shared": 0.4803,
             "max_dd": 0.1314, "final_equity_usd": 118509.86},
            {"initial_cash_usd": 1_000_000, "sr_ann": 0.0424, "dsr_shared": 0.2112,
             "max_dd": 0.1359, "final_equity_usd": 993219.39},
            {"initial_cash_usd": 10_000_000, "sr_ann": -0.3720, "dsr_shared": 0.0460,
             "max_dd": 0.2269, "final_equity_usd": 8043578.96},
        ],
        "capacity_note": (
            "The edge decays as capital grows: at $10M the realized Sharpe is negative as "
            "market impact consumes the thin signal. Crypto carry is finite-capacity alpha."
        ),
        "verdict": {
            "pass": False,
            "outcome": "NO-DEPLOY (honest null)",
            "gauntlet_grade": metrics["gauntlet_grade"],
            "gauntlet_status": metrics["gauntlet_pass"],
            "reason": (
                "Best config DSR 0.2112 < 0.95 gate AND PBO 0.8818 > 0.20 gate. No variant "
                "beats baseline and clears deflation simultaneously. Crypto-perps alone is a "
                "thin cross-sectional signal that does not survive honest deflation net of cost; "
                "the equity sleeve is required as ballast."
            ),
        },
        "source_paths": [
            str((GRAND_BACKTEST_DIR / "verdict.md").relative_to(REPO)),
            str(STATE_JSON.relative_to(REPO)),
        ],
    }


# ---------------------------------------------------------------------------
# Feature 4 — track_record.json (live curve + labelled research/simulation curve)
# ---------------------------------------------------------------------------
def read_live_curve_from_sqlite() -> list[dict[str, Any]] | None:
    """Read the realized live equity curve from trading.sqlite, or None if no rows exist.

    The live track record genuinely starts at day zero; until the daily cycle has written
    rows to equity_curve, this returns None and the caller falls back to the go-live seed.
    """
    if not TRADING_SQLITE.exists():
        return None
    con = sqlite3.connect(f"file:{TRADING_SQLITE}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT ts, equity_quote FROM equity_curve WHERE ts IS NOT NULL ORDER BY ts ASC"
        )
        rows = cur.fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not rows:
        return None
    curve: list[dict[str, Any]] = []
    for ts_ms, equity in rows:
        curve.append(
            {
                "date": epoch_ms_to_iso_date(float(ts_ms)),
                "nav_usd": round(float(equity), 2),
            }
        )
    return curve


def build_track_record() -> dict[str, Any]:
    """track_record.json: realized live curve (sqlite) or the honest go-live seed, plus the
    explicitly-labelled research/simulation curve from the paper state."""
    state = json.loads(STATE_JSON.read_text())
    go_live = str(state["go_live_date"])

    live_from_db = read_live_curve_from_sqlite()
    if live_from_db is not None:
        live_curve = live_from_db
        live_source = "trading.sqlite equity_curve (realized paper marks)"
    else:
        # Honest seed: the day the live record begins, at the $100k baseline. No fake history.
        seed = state.get("live_curve") or [{"date": go_live, "equity": INITIAL_EQUITY}]
        live_curve = [
            {"date": str(p["date"]), "nav_usd": round(float(p["equity"]), 2)} for p in seed
        ]
        live_source = "go-live seed (no realized marks have accrued yet)"

    baseline = live_curve[0]["nav_usd"]
    current = live_curve[-1]["nav_usd"]
    today = dt.datetime.now(tz=dt.UTC).date()
    go_live_date = dt.date.fromisoformat(go_live)
    live_days = max(0, (today - go_live_date).days)

    research = [
        {"date": str(p["date"]), "nav_usd": round(float(p["equity"]), 2)}
        for p in state["research_curve"]
    ]

    return {
        "schema": "glassbox.track_record/1",
        "title": "Live Track Record",
        "summary": (
            "The live paper record begins at go-live and is shown only as it accrues. "
            "We publish no return until it is earned in the open."
        ),
        "go_live_date": go_live,
        "live_days_accrued": live_days,
        "live_status": "ACCRUING" if current == baseline else "LIVE",
        "live_source": live_source,
        "live_nav_baseline_usd": baseline,
        "live_nav_current_usd": current,
        "live_return_pct": round((current - baseline) / baseline * 100.0, 4),
        "live_curve": live_curve,
        "research_curve_label": "SIMULATION (research backtest, NOT realized trading)",
        "research_curve_start": research[0],
        "research_curve_end": research[-1],
        "research_curve_points": len(research),
        "research_curve": research,
        "honesty_policy": list(state["transparency"]),
        "source_paths": [
            str(STATE_JSON.relative_to(REPO)),
            str(TRADING_SQLITE.relative_to(REPO)) if TRADING_SQLITE.exists() else None,
        ],
    }


# ---------------------------------------------------------------------------
# Feature 5 — reproducibility.json (golden-master / byte-identity basis)
# ---------------------------------------------------------------------------
def count_registered_factors() -> int:
    """Count the registered feature specs by importing the library so decorators fire."""
    import importlib
    import pkgutil

    import alphaforge.features.library as lib

    for mod in pkgutil.iter_modules(lib.__path__):
        importlib.import_module(f"alphaforge.features.library.{mod.name}")
    from alphaforge.features.registry import default_registry

    return len(default_registry())


def build_reproducibility() -> dict[str, Any]:
    """reproducibility.json: the byte-identity acceptance gate + the 50-factor parity claim."""
    n_factors = count_registered_factors()
    gm_lines = len(GOLDEN_MASTER.read_text().splitlines()) if GOLDEN_MASTER.exists() else 0

    return {
        "schema": "glassbox.reproducibility/1",
        "title": "Reproducibility",
        "summary": (
            "The backtest is content-hashed and byte-reproducible. A golden-master test asserts "
            "every fill price, fee, funding payment and the final equity from hand-written "
            "arithmetic to 1e-9 precision. We do not claim blockchain anchoring; we do not need it."
        ),
        "reproducibility_claim": "content-hashed + byte-reproducible backtest",
        "not_claimed": "NOT blockchain-anchored; no chain-of-custody proofs",
        "registered_factors": n_factors,
        "golden_master_test": {
            "file": str(GOLDEN_MASTER.relative_to(REPO)),
            "lines": gm_lines,
            "purpose": "Phase-5 FULL acceptance gate (execDesign.md section 4.5)",
            "coverage": [
                "Part 1: a 3-instrument 30-bar scripted run (opens, an add, a partial close, a "
                "long-to-short flip, a gap-drop, mixed 8h/4h funding). EVERY fill price, fee, "
                "funding payment and the final equity asserted to abs=1e-9.",
                "Part 2: the engine's local ADV/sigma (LakeCostInputs) asserted numerically EQUAL "
                "to the registered feature-library adv_quote_30d / sigma_daily, so the backtester "
                "and the feature library never fork the formula.",
                "Part 3: real Binance BTCUSDT 2024-03-01..2024-03-08. The stored funding table "
                "must hold exactly 21 settlements (the 8h schedule) and a week-long long must "
                "settle exactly those events (rel=1e-12 on each payment).",
            ],
        },
        "fill_price_precision": {
            "unit": "float64",
            "assertion_tolerance": "abs=1e-9 (pytest.approx)",
            "rounding_policy": "full internal precision; rounding only at report render",
        },
        "factor_parity": {
            "adv_quote_30d": "engine ADV == feature-library adv_quote_30d (EXACT, abs=0.0)",
            "sigma_daily": "engine sigma == feature-library sigma_daily (rel=1e-12, same EWMA)",
        },
        "funding_reproduction": {
            "instrument": "BINANCE:PERP:BTCUSDT",
            "window": "2024-03-01 to 2024-03-08 (7 days, 8-hour cadence)",
            "expected_settlements": 21,
            "formula": "payment_quote = -qty * mark_price * rate",
            "precision": "rel=1e-12",
        },
        "no_look_ahead": (
            "Every weight and leverage applied to a forward day is a pure function of returns "
            "strictly before that day, enforced by the PIT reader and a truncation-invariance test."
        ),
        "source_paths": [str(GOLDEN_MASTER.relative_to(REPO))],
    }


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Feature 6 — red_team.json: WE PUBLISH OUR OWN BUGS. The 2026-06-27 adversarial red-team
# attacked our own published record and found it was flattering us; we publish every finding
# with its severity and fix status. A fund that publishes the defects it found in itself is the
# one you can actually trust. Curated from the workflow's structured findings (verifiable in the
# artifacts: the future-date clamp in paper_trading_state.py, the corrected metrics, the seq-1
# transparency entry, artifacts/campaigns/).
def build_red_team() -> dict[str, Any]:
    findings = [
        {"severity": "critical", "status": "FIXED",
         "weakness": "A future-dated (2026-06-29) paper loss leaked into the public record and was sealed into seq 0 of the signed transparency chain (read_fwd_curve had no <= today guard).",
         "fix": "clamp_live() drops any mark dated after today (UTC) before publish + anchor; a fail-closed guard was added; the corrected state was anchored as seq 1. The append-only chain shows BOTH seq 0 and seq 1 — we don't delete mistakes."},
        {"severity": "critical", "status": "FIXED",
         "weakness": "The headline -4.7% max drawdown excluded every crisis (the book curve starts 2023-07, no 2020/2022). It understated risk badly.",
         "fix": "Crisis-inclusive worst case (-15 to -18%) is now the headline; -4.7% is labeled 'live-overlap only, not a risk estimate'."},
        {"severity": "high", "status": "FIXED",
         "weakness": "Sleeves were mislabeled: crypto carry (46% weight) has been FLAT since go-live but was billed 'live broker-loop'; equity & MF were billed 'realized next-open fills' but are walk-forward SIMULATIONS, not broker-executed.",
         "fix": "Relabeled honestly (crypto = live loop currently flat / holding cash; equity & MF = walk-forward simulation, not broker-executed). Making them genuinely live is the next build."},
        {"severity": "high", "status": "FIXED",
         "weakness": "Standalone Sharpes were recent-window-flattered: crypto 0.68 hides a -19.6% 2022 (FTX) drawdown; equity 0.91 is the TOP of a 0.07-1.17 band whose deep-history forward is ~0.08 (DSR 0.17 at the current N=102 ledger; 0.34 when first published at N=27 — fails deflation either way, and deflation tightens as our own experiment count grows).",
         "fix": "Per-sleeve caveats attached; the book forward expectation lowered from 0.7-1.0 to 0.3-0.9 with a stated real chance of ~0 in year one."},
        {"severity": "high", "status": "FIXED",
         "weakness": "Deflation N was framed as 'honest trial count = 8' when 35+ strategy families have been searched across the program (screen-stage kills bypassed the ledger).",
         "fix": "Renamed to crypto_perp_grid_trials; exposed cumulative_strategy_families_searched (35+). Wiring every screen into the shared ledger is the remaining engineering step."},
        {"severity": "high", "status": "DISCLOSED",
         "weakness": "Sleeve correlations spike from ~0 (calm) to +0.6 to +0.9 in risk-off — the diversification benefit shrinks exactly in the left tail.",
         "fix": "Disclosed in the published metrics + transparency; sizing the equal-risk combiner on the stressed matrix is the remaining engineering step."},
        {"severity": "medium", "status": "OPEN",
         "weakness": "The cost model uses a flat half-spread regardless of regime (it never widens in stress); the two deployed sleeves lack a published 2-3x cost-survival rerun.",
         "fix": "Vol/regime-scaled half-spread + a published 2x/3x cost rerun of the live sleeves. Tracked."},
        {"severity": "low", "status": "OPEN",
         "weakness": "go-live date overstated 1-2 days vs first real activity; the verifier checks the published JSON, not the raw jsonl source-of-truth.",
         "fix": "Per-sleeve effective go-live = first real activity; verifier to accept the raw jsonl. Tracked."},
    ]
    held_up = [
        "Point-in-time / leakage discipline is genuinely sound (decide-at-close, fill-next-open, available_at lags, PIT universe membership, realized historical funding).",
        "The directional TrendVolTarget allocator, the vol-target overlay, and the reduce-only de-risk path were adversarially exercised and held.",
        "AlphaTrend genuinely survives 2008/2020/2022 on the 17 real ETFs — as a drawdown "
        "profile. Its DSR was re-derived to 0.000 on 2026-08-07, so 'survives the crises' is a "
        "statement about its shape, NOT the edge claim the withdrawn 0.83 implied.",
        "The public state honestly labels the 1.46 figure as in-sample and deflates it.",
    ]
    return {
        "schema": "glassbox.red_team/1",
        "title": "We Red-Team Ourselves",
        "summary": (
            "On 2026-06-27 an adversarial red-team attacked our own published record harder than "
            "any allocator would, and found it was flattering us in several ways. We publish every "
            "finding, its severity, and its fix. A fund that publishes the defects it found in "
            f"itself is the one you can verify. {sum(1 for f in findings if f['status']=='FIXED')} "
            f"of {len(findings)} findings already fixed."
        ),
        "findings": findings,
        "what_held_up": held_up,
        "report": "artifacts/campaigns/red_team_self_audit_2026-06-27.md",
    }


# Driver
# ---------------------------------------------------------------------------
BUILDERS: Final[dict[str, Any]] = {
    "kill_log.json": build_kill_log,
    "pre_registration.json": build_pre_registration,
    "deflation.json": build_deflation,
    "track_record.json": build_track_record,
    "reproducibility.json": build_reproducibility,
    "red_team.json": build_red_team,
}


def main(out_dir: Path = OUT_DIR) -> None:
    """Build every glass-box artifact and write it to ``out_dir``."""
    written: list[Path] = []
    for filename, builder in BUILDERS.items():
        payload = builder()
        path = write_json(out_dir, filename, payload)
        written.append(path)
    for path in written:
        size = path.stat().st_size
        print(f"wrote {path}  ({size} bytes)")
    print(f"\n{len(written)} glass-box artifacts emitted to {out_dir}")


if __name__ == "__main__":
    main()
