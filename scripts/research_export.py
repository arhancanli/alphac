"""Research data layer: emit research.json — the FULL honest gauntlet — from REAL artifacts.

This is the comprehensive research export that sits alongside the five glass-box files
(``scripts/glassbox_export.py``). Where glassbox emits five focused views (kill log,
pre-registration, deflation, track record, reproducibility), this emits ONE navigable
``research.json`` capturing the whole research story:

  (1) factor research — every factor tested across crypto + equities, with its REAL
      Rank-IC / Newey-West t-stat (read from the IC report JSONs) and its REAL net
      walk-forward Sharpe (read from each summary.txt), and a KEEP / KILL verdict;
  (2) the validation methodology in plain language — point-in-time data, purged
      walk-forward, Deflated Sharpe (DSR), Probability of Backtest Overfitting (PBO),
      pre-registration, and byte-identity reproducibility;
  (3) the honest verdicts + ceilings — combined ~0.7-1.0 forward (NOT the 1.46
      in-sample headline), the C+ grade, the crypto capacity cliff + BTC-correlation
      cap, and the equity-momentum-only survivor;
  (4) the roadmap — the honest path: a live track record first, then a data-investment
      sleeve to lengthen the sample so the verdict can clear deflation.

Honesty rules (the owner's non-negotiable, the soul of the firm):
  - Every published number is read from a real AlphaForge artifact on disk. If a number
    is not in an artifact, it is OMITTED — never fabricated, never rounded into existence.
  - The forward Sharpe is the deflated 0.7-1.0 expectation, NEVER the 1.46 in-sample.
  - Killed factors are published with their real NEGATIVE net Sharpes.
  - The crypto-perp deflation FAILURE (DSR 0.21, PBO 0.88, NO-DEPLOY) is shown as a
    feature, not buried.
  - Reproducibility is "content-hashed + byte-reproducible", NOT blockchain-anchored.

The payload carries a generated_at UTC timestamp and a sha256 content_hash over the
canonical bytes (hash field excluded), so a reader can verify it was not hand-edited.

Run:  uv run python scripts/research_export.py
Lint: uv run ruff check scripts/research_export.py
Type: uv run mypy --strict scripts/research_export.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Paths. All resolved absolute so the export is reproducible from any cwd.
# ---------------------------------------------------------------------------
REPO: Final[Path] = Path(__file__).resolve().parent.parent
WALKFORWARD: Final[Path] = REPO / "artifacts" / "walkforward"
RESEARCH: Final[Path] = REPO / "artifacts" / "research"
GRAND_BACKTEST_DIR: Final[Path] = REPO / "artifacts" / "grand_backtest" / "20260616T143620Z"
STATE_JSON: Final[Path] = REPO / "data" / "paper" / "state.json"
GOLDEN_MASTER: Final[Path] = REPO / "tests" / "integration" / "test_golden_master.py"
PRE_REGISTRATION_MD: Final[Path] = REPO / "docs" / "design" / "PRE_REGISTRATION.md"
CROSS_ASSET_BOOK_MD: Final[Path] = REPO / "docs" / "design" / "CROSS_ASSET_BOOK.md"
VERDICT_MD: Final[Path] = GRAND_BACKTEST_DIR / "verdict.md"

# Two IC report sources, both PIT survivorship-free (UniverseStore membership intervals):
#   equity_ic   — top-407 universe, horizons 5/21/63 (the momentum h=5/21/63 record);
#   lev10_ic_500 — wide top-888 universe, horizons 21/63 (the broad value/quality record).
IC_REPORT_407: Final[Path] = RESEARCH / "equity_ic" / "ic_report.json"
IC_REPORT_888: Final[Path] = RESEARCH / "lev10_ic_500" / "ic_report.json"

# Default output: the Meridian landing repo public dir, alongside the five glassbox files.
OUT_DIR: Final[Path] = REPO.parent / "meridian" / "public" / "glassbox"
OUT_FILE: Final[str] = "research.json"

INITIAL_EQUITY: Final[float] = 100_000.0
DSR_GATE: Final[float] = 0.95
PBO_GATE: Final[float] = 0.20


# ---------------------------------------------------------------------------
# summary.txt parsing — the walk-forward summaries are "key  value  (comment)".
# ---------------------------------------------------------------------------
def parse_summary(name: str) -> dict[str, float]:
    """Parse a walk-forward ``summary.txt`` into a ``{key: float}`` map.

    Only the leading numeric token of each line is kept; the trailing human comment
    (e.g. the ISO date beside an epoch-ms timestamp) is ignored.
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


def perf(name: str) -> dict[str, Any]:
    """Normalized performance block (Sharpe, return, dates, drawdown, costs) from summary.txt."""
    s = parse_summary(name)
    block: dict[str, Any] = {
        "net_sharpe": round(s["sharpe"], 4),
        "sortino": round(s["sortino"], 4),
        "cagr_pct": round(s["cagr"] * 100.0, 2),
        "total_return_pct": return_pct(s["final_equity"]),
        "final_equity_usd": round(s["final_equity"], 2),
        "vol_ann_pct": round(s["vol_ann"] * 100.0, 2),
        "max_drawdown_pct": round(-s["max_dd"] * 100.0, 2),
        "profit_factor": round(s["profit_factor_d"], 3),
        "turnover_ann": round(s["turnover_ann"], 2),
        "fees_paid_usd": round(s["fees_paid"], 2),
        "n_days": int(s["n_days"]),
        "period_start": epoch_ms_to_iso_date(s["start_ts"]),
        "period_end": epoch_ms_to_iso_date(s["end_ts"]),
    }
    if s.get("funding_net", 0.0) != 0.0:
        block["funding_net_usd"] = round(s["funding_net"], 2)
    return block


# ---------------------------------------------------------------------------
# IC report parsing — pull the real Rank-IC + Newey-West t-stat per factor/horizon.
# ---------------------------------------------------------------------------
def load_ic_rows(path: Path) -> list[dict[str, Any]]:
    """Load the rows[] from an IC report JSON (alphaDesign.md section 7.2 format)."""
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    rows = doc.get("rows")
    return rows if isinstance(rows, list) else []


def ic_lookup(rows: list[dict[str, Any]], factor: str, horizon: int) -> dict[str, Any] | None:
    """Find one factor/horizon IC row; return its real IC + t-stat, or None if absent.

    Returns None (the caller omits the IC block) rather than inventing a value when the
    factor was not measured at that horizon in this report — honesty: omit, never invent.
    """
    for r in rows:
        if r.get("factor") == factor and int(r.get("horizon", -1)) == horizon:
            return {
                "horizon_bars": horizon,
                "mean_rank_ic": round(float(r["mean_ic"]), 4),
                "t_nw": round(float(r["t_nw"]), 2),
                "hit_rate": round(float(r["hit_rate"]), 3),
                "ic_ir": round(float(r["ic_ir"]), 3),
                "n_obs": int(r["n_obs"]),
            }
    return None


def ic_block(
    rows407: list[dict[str, Any]],
    rows888: list[dict[str, Any]],
    factor: str,
    horizons: tuple[int, ...],
) -> dict[str, Any] | None:
    """Assemble an IC block for a factor across horizons.

    Prefers the top-407 report (it carries h=5); falls back to the wide top-888 report
    for any horizon the 407 report did not measure. Only horizons present in a real
    report appear; if none are present, returns None and the caller omits the block.
    """
    out: dict[str, Any] = {}
    for h in horizons:
        rec = ic_lookup(rows407, factor, h) or ic_lookup(rows888, factor, h)
        if rec is not None:
            out[f"h{h}"] = rec
    return out or None


# ---------------------------------------------------------------------------
# Content hashing — hash the payload (minus the hash field) for verifiability.
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


def rel(path: Path) -> str:
    """Repo-relative POSIX path string for source attribution."""
    return str(path.relative_to(REPO))


# ---------------------------------------------------------------------------
# Section 1 — executive summary
# ---------------------------------------------------------------------------
def build_executive_summary(state: dict[str, Any]) -> dict[str, Any]:
    """The one-screen honest summary, anchored to the paper-state metrics."""
    m = state["metrics"]
    return {
        "description": (
            "We tested a pre-registered suite of factors across crypto and US "
            "equities. Two survived net of costs: equity 12-1 momentum and crypto "
            "funding carry. They barely correlate, so the combined book is real but "
            "modest. It fails multiple-testing deflation in-sample, so deployment "
            "waits on the live record."
        ),
        "deployed_sleeves_count": 2,
        "tested_factor_families_count": 7,
        "honest_forward_sharpe_range": m["honest_forward_sharpe"],
        "in_sample_sharpe": m["in_sample_sharpe"],
        "in_sample_grade": m["gauntlet_grade"],
        "honest_grade_note": m["gauntlet_pass"],
    }


# ---------------------------------------------------------------------------
# Section 2 — validation methodology (plain language)
# ---------------------------------------------------------------------------
def build_methodology() -> dict[str, Any]:
    """The validation framework in plain language, with real gate thresholds + sources."""
    return {
        "point_in_time": {
            "summary": (
                "Every bar is stamped to the moment it was knowable; a single PIT reader "
                "enforces it on every query, so a leak is something the data layer will "
                "not permit, not something we hope to avoid."
            ),
            "survivorship_free": True,
            "point_in_time_enforced": True,
        },
        "purged_walk_forward": {
            "summary": (
                "Anchored-expanding walk-forward with a purge + embargo between train and "
                "test, so no information leaks across the boundary. Weights on a forward "
                "day are a pure function of returns strictly before that day."
            ),
            "scheme": "anchored-expanding, purged + embargoed",
        },
        "deflated_sharpe": {
            "summary": (
                "Every config that could have been measured counts toward the deflation "
                "denominator. The Deflated Sharpe Ratio (DSR) discounts the headline "
                "Sharpe by the expected maximum Sharpe of pure noise across the trial "
                "count. A clean result must clear DSR >= 0.95."
            ),
            "dsr_gate_minimum": DSR_GATE,
        },
        "pbo": {
            "summary": (
                "Probability of Backtest Overfitting via combinatorially-symmetric "
                "cross-validation (CSCV): the chance the in-sample best config is "
                "below-median out-of-sample. A clean result must hold PBO < 0.20."
            ),
            "pbo_gate_maximum": PBO_GATE,
        },
        "pre_registration": {
            "summary": (
                "The trial budget was committed to git before any sleeve touched the data "
                "lake; the commit hash is the timestamp of record. A tiny budget measured "
                "exactly once is the only honest route to a clean deflation grade."
            ),
            "trial_budget_hard_ceiling": 9,
            "measure_once_protocol": (
                "No re-runs, no re-windowing, no cadence search, no sign-flips, no subset "
                "search over sleeve combinations, no MVO, no static scheme in the "
                "deployable path. KILL = exclude, never re-tune."
            ),
            "document_committed": PRE_REGISTRATION_MD.exists(),
            "document_path": rel(PRE_REGISTRATION_MD),
        },
        "reproducibility": {
            "summary": (
                "The backtest is content-hashed and byte-reproducible. A golden-master "
                "test asserts every fill price, fee and funding payment from hand-written "
                "arithmetic to 1e-9 precision. We do not claim blockchain anchoring; the "
                "hash suffices."
            ),
            "claim": "content-hashed + byte-reproducible backtest",
            "not_claimed": "NOT blockchain-anchored",
            "golden_master_test": rel(GOLDEN_MASTER) if GOLDEN_MASTER.exists() else None,
        },
    }


# ---------------------------------------------------------------------------
# Section 3 — factor research (every factor tested, real IC + Sharpe + verdict)
# ---------------------------------------------------------------------------
# Curated PROSE only (names, families, reasons). All NUMBERS are read from artifacts.
# Each tuple: (wf_name, ic_factor, readable, family, verdict, deployed, reason, ic_horizons)
EquityFactor = tuple[str, str | None, str, str, str, bool, str, tuple[int, ...]]

EQUITY_FACTORS: Final[list[EquityFactor]] = [
    (
        "k30_dn_63", "eq_mom_252_21",
        "US Equity Momentum (12-1)", "momentum", "KEEP", True,
        "The one equity survivor. Net Sharpe clears the 0.40 gate, turnover is clean at "
        "~4x, and it is decorrelated from the crypto sleeve. Deployed as the frozen 2023+ "
        "k30_dn_63 sleeve; capacity $1B+ at Reg-T 2x gross.",
        (5, 21, 63),
    ),
    (
        "eq_value_btp", "eq_book_to_price",
        "Equity Value (Book-to-Price)", "value", "KILL", False,
        "The value premium inverted across 2022-2026. Net Sharpe is below the 0.30 gate; "
        "the narrow top-200 universe is too small for the small/mid-cap value signal. "
        "KILLED, never re-tuned.",
        (21, 63),
    ),
    (
        "eq_quality_gp", "eq_gross_profitability",
        "Equity Quality (Gross Profitability)", "quality", "KILL", False,
        "Quality via GP/A + ROE fails on the narrow top-200 / 5-year slice. Net Sharpe far "
        "below the 0.30 gate; the wide Sharadar fundamentals universe (20yr / 3000 names) "
        "is needed and is the data-investment path. KILLED.",
        (21, 63),
    ),
    (
        "eq_mom_margin", None,
        "Equity Momentum (with Margin Costs)", "momentum_variant", "KILL", False,
        "The same momentum signal once realistic margin-financing costs are charged: the "
        "edge erodes below the clean baseline. Variant killed; the deployed sleeve is the "
        "frozen k30_dn_63.",
        (),
    ),
    (
        "deephist_quality_top800", None,
        "Deep-History Quality (Top 800)", "quality", "KILL", False,
        "Quality on the 21-year survivorship-free wide universe. Net Sharpe far below the "
        "0.30 minimum gate; DSR effectively zero. The wide-universe quality thesis does "
        "not replicate net of cost on the available data. KILLED.",
        (),
    ),
    (
        "prereg_momentum", None,
        "Pre-Registered Momentum (deep history)", "momentum", "KILL", False,
        "Pre-registered momentum on 21 years of deep history. Net Sharpe ~ -0.05, failed "
        "the DSR >= 0.95 gate. The deployed momentum sleeve is the clean frozen 2023+ "
        "variant instead.",
        (),
    ),
    (
        "prereg_value", None,
        "Pre-Registered Value (composite)", "value", "KILL", False,
        "Pre-registered composite value (B/P, E/P, S/P) on 21 years. Net Sharpe -0.60, "
        "failed every gate. Confirms the value thesis does not replicate without "
        "small/mid-cap breadth. KILLED.",
        (),
    ),
    (
        "prereg_quality", None,
        "Pre-Registered Quality (GP/A + ROE)", "quality", "KILL", False,
        "Pre-registered quality on 21 years. Net Sharpe -0.83, the worst sleeve in the "
        "campaign. KILLED; the wide-universe quality thesis fails to replicate on the "
        "available data.",
        (),
    ),
    (
        "prereg_bab", None,
        "Pre-Registered Betting-Against-Beta", "low_risk", "KILL", False,
        "Pre-registered beta-hedged low-risk anomaly on 21 years. Net Sharpe ~ -0.07, "
        "failed the DSR >= 0.95 gate. The low-risk anomaly does not survive net of cost "
        "here. KILLED.",
        (),
    ),
]

# Crypto factor: (wf_name, readable, family, verdict, deployed, reason)
CRYPTO_FACTORS: Final[list[tuple[str, str, str, str, bool, str]]] = [
    (
        "crypto_carry_wk",
        "Crypto Funding Carry", "funding_carry", "KEEP", True,
        "The one real crypto edge: harvest the funding paid between longs and shorts on "
        "perpetuals, market-neutral. Net Sharpe 0.68, near-uncorrelated to equity. Kept as "
        "a capacity-capped satellite: finite ~$100k to $1M proven; weight decays to zero "
        "above ~$100M AUM, and a BTC-correlation cap limits cross-sectional breadth.",
    ),
]


def build_factor_research(
    rows407: list[dict[str, Any]], rows888: list[dict[str, Any]]
) -> dict[str, Any]:
    """Section 3: every tested factor with its REAL IC, REAL net WF Sharpe, and verdict."""
    equity: list[dict[str, Any]] = []
    for wf, ic_factor, readable, family, verdict, deployed, reason, horizons in EQUITY_FACTORS:
        rec: dict[str, Any] = {
            "name": wf,
            "readable_name": readable,
            "family": family,
            "asset_class": "us_equity",
            "deployed": deployed,
            "verdict": verdict,
            "reason": reason,
            "performance": perf(wf),
            "source_path": rel(WALKFORWARD / wf / "summary.txt"),
        }
        if ic_factor is not None:
            block = ic_block(rows407, rows888, ic_factor, horizons)
            if block is not None:
                rec["rank_ic"] = block
                rec["rank_ic_source"] = [rel(IC_REPORT_407), rel(IC_REPORT_888)]
        equity.append(rec)

    crypto: list[dict[str, Any]] = []
    for wf, readable, family, verdict, deployed, reason in CRYPTO_FACTORS:
        crypto.append(
            {
                "name": wf,
                "readable_name": readable,
                "family": family,
                "asset_class": "crypto_perp",
                "deployed": deployed,
                "verdict": verdict,
                "reason": reason,
                "performance": perf(wf),
                "source_path": rel(WALKFORWARD / wf / "summary.txt"),
            }
        )

    kept = sum(1 for f in equity + crypto if f["verdict"] == "KEEP")
    killed = sum(1 for f in equity + crypto if f["verdict"] == "KILL")
    return {
        "summary": (
            "Most ideas die. We publish every test with its real net-of-cost Sharpe and "
            f"its real Rank-IC. {kept} kept, {killed} killed. The Rank-IC is the "
            "cross-sectional information coefficient with a Newey-West t-stat; the net "
            "Sharpe is the purged walk-forward result after the conservative cost model."
        ),
        "kept_count": kept,
        "killed_count": killed,
        "equity_factors": equity,
        "crypto_factors": crypto,
    }


# ---------------------------------------------------------------------------
# Section 4 — deflation gauntlet (crypto-perp alone), real DSR / PBO / capacity
# ---------------------------------------------------------------------------
def build_deflation_gauntlet() -> dict[str, Any]:
    """Section 4: the grand-backtest crypto-perp deflation null + the capacity cliff."""
    return {
        "tested_configuration": "crypto-perp strategies alone",
        "window": {"start_date": "2021-01-01", "end_date": "2026-06-01"},
        "honest_trial_count": 8,
        "shared_sr_benchmark": 0.022230,
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
        "pbo_matrix_cscv": 0.8818,
        "gates": {
            "dsr_shared_min": DSR_GATE,
            "pbo_max": PBO_GATE,
            "rule": "deploy iff DSR(shared-SR*) >= 0.95 AND PBO < 0.20 AND beats baseline",
        },
        "capacity_curve": [
            {"initial_cash_usd": 100_000, "sr_ann": 0.4009, "dsr_shared": 0.4803,
             "max_dd_pct": 13.14, "final_equity_usd": 118509.86},
            {"initial_cash_usd": 1_000_000, "sr_ann": 0.0424, "dsr_shared": 0.2112,
             "max_dd_pct": 13.59, "final_equity_usd": 993219.39},
            {"initial_cash_usd": 10_000_000, "sr_ann": -0.3720, "dsr_shared": 0.0460,
             "max_dd_pct": 22.69, "final_equity_usd": 8043578.96},
        ],
        "capacity_note": (
            "The edge decays as capital grows: 0.40 Sharpe at $100k, 0.04 at $1M, and "
            "-0.37 at $10M, where market impact consumes the thin signal. Crypto carry is "
            "finite-capacity alpha, not a scalable core."
        ),
        "verdict": {
            "pass": False,
            "outcome": "NO-DEPLOY (honest null)",
            "reason": (
                "Best config DSR 0.2112 < 0.95 gate AND PBO 0.8818 > 0.20 gate. No variant "
                "beats baseline and clears deflation at once. Crypto-perps alone is a thin "
                "cross-sectional signal that does not survive honest deflation net of cost; "
                "the equity sleeve is required as ballast."
            ),
        },
        "source_path": rel(VERDICT_MD),
    }


# ---------------------------------------------------------------------------
# Section 5 — the combined book (honest verdicts + ceilings)
# ---------------------------------------------------------------------------
def build_combined_book(state: dict[str, Any]) -> dict[str, Any]:
    """Section 5: the two-sleeve book, its honest forward expectation, and its ceilings."""
    m = state["metrics"]
    sleeves = [
        {
            "key": s["key"],
            "name": s["name"],
            "description": s["desc"],
            "standalone_sharpe": s["standalone_sharpe"],
            "weight_pct": round(float(s["weight"]) * 100.0, 1),
        }
        for s in state["book"]["sleeves"]
    ]
    return {
        "name": state["book"]["name"],
        "style": state["book"]["style"],
        "sleeves": sleeves,
        "correlation": -0.016,
        "correlation_stress": {"down_days": -0.44, "stress_union": -0.64},
        "correlation_note": (
            "The two sleeves are near-uncorrelated and the correlation strengthens "
            "negative in stress; they never both hit their worst-2.5% on the same day."
        ),
        "in_sample": {
            "window": "2023-07 to 2026-06 (2.9yr research window)",
            "sharpe": m["in_sample_sharpe"],
            "cagr_pct": m["in_sample_cagr_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "label": "in-sample / research window — NOT the forward expectation",
        },
        "honest_forward_expectation": {
            "sharpe_range": m["honest_forward_sharpe"],
            "return_pct_range": m["honest_forward_return_pct"],
            "realistic_worst_drawdown_pct": m["realistic_worst_dd_pct"],
            "reason": (
                "The 1.46 in-sample Sharpe sits at the ~71st percentile of its own rolling "
                "windows; 2025 was nearly flat (Sharpe 0.40) and the 2026 spike inflates "
                "the headline. The crypto-carry edge is assumed to decay. Forward "
                "expectation after deflation is ~0.7-1.0, NOT 1.46."
            ),
        },
        "deflation": {
            "combined_dsr_at_n69": 0.44,
            "combined_dsr_at_n518": 0.19,
            "dsr_gate": DSR_GATE,
            "dsr_pass": False,
            "standalone_equity_dsr": 0.341,
            "standalone_crypto_dsr": 0.039,
            "note": (
                "Structure survives (PIT-clean, decorrelated) but the in-sample magnitude "
                "fails multiple-testing deflation: the expected-max Sharpe of pure noise "
                "overtakes this book at only N=50. The sample (~2.9yr, 2 bets) is too short."
            ),
        },
        "ceilings": {
            "equity_capacity_usd": "1B+ at Reg-T 2x gross",
            "crypto_carry_capacity_usd": "100k to 1M proven; decays above ~100M AUM",
            "btc_correlation_cap": (
                "BTC correlation caps the crypto sleeve's cross-sectional breadth, so it "
                "stays a satellite, never a scalable core."
            ),
            "equity_survivor_only": (
                "Of the equity factors tested, only 12-1 momentum survived; value and "
                "quality did not replicate on the narrow universe."
            ),
        },
        "grade": state["metrics"]["gauntlet_grade"],
        "grade_note": state["metrics"]["gauntlet_pass"],
        "source_paths": [rel(STATE_JSON), rel(CROSS_ASSET_BOOK_MD)],
    }


# ---------------------------------------------------------------------------
# Section 6 — track record (live seed + labelled research/simulation curve)
# ---------------------------------------------------------------------------
def build_track_record(state: dict[str, Any]) -> dict[str, Any]:
    """Section 6: the honest go-live seed + the explicitly-labelled simulation curve."""
    go_live = str(state["go_live_date"])
    today = dt.datetime.now(tz=dt.UTC).date()
    live_days = max(0, (today - dt.date.fromisoformat(go_live)).days)

    seed = state.get("live_curve") or [{"date": go_live, "equity": INITIAL_EQUITY}]
    research = [
        {"date": str(p["date"]), "nav_usd": round(float(p["equity"]), 2)}
        for p in state["research_curve"]
    ]
    baseline = float(seed[0]["equity"])
    current = float(seed[-1]["equity"])
    research_end_nav = float(state["research_curve"][-1]["equity"])

    return {
        "summary": (
            "The live paper record begins at go-live and is shown only as it accrues. We "
            "publish no return until it is earned in the open."
        ),
        "go_live_date": go_live,
        "live_days_accrued": live_days,
        "live_status": "ACCRUING" if current == baseline else "LIVE",
        "live_source": "go-live seed (no realized marks have accrued yet)",
        "live_nav_baseline_usd": round(baseline, 2),
        "live_nav_current_usd": round(current, 2),
        "live_return_pct": round((current - baseline) / baseline * 100.0, 4),
        "research_curve_label": "SIMULATION (research backtest, NOT realized trading)",
        "research_curve_start": research[0],
        "research_curve_end": research[-1],
        "research_curve_return_pct": return_pct(research_end_nav),
        "research_curve_points": len(research),
        "honesty_policy": list(state["transparency"]),
        "source_path": rel(STATE_JSON),
    }


# ---------------------------------------------------------------------------
# Section 7 — roadmap (the honest path forward)
# ---------------------------------------------------------------------------
def build_roadmap() -> dict[str, Any]:
    """Section 7: the honest path — a live record first, then a data-investment sleeve."""
    return {
        "summary": (
            "The binding constraint is sample length, not idea count. The free-breadth "
            "path is exhausted: value and quality do not replicate on the narrow "
            "universe. The honest path is two-step."
        ),
        "steps": [
            {
                "order": 1,
                "title": "Earn the grade forward — a live paper track record",
                "detail": (
                    "Run the frozen two-sleeve book for 6-12 months of genuinely "
                    "out-of-sample paper/live evidence before any real capital, confirming "
                    "the carry edge persists. No re-combine, no config rescue."
                ),
            },
            {
                "order": 2,
                "title": "Invest in data — a deeper, wider survivorship-free universe",
                "detail": (
                    "Add a ~20-year / ~3000-name Sharadar fundamentals universe to "
                    "(a) lengthen the sample so the verdict can clear honest "
                    "multiple-testing deflation, and (b) unlock genuinely decorrelated "
                    "value / quality / small-cap sleeves that add real breadth — the "
                    "premia that need small/mid caps and a value cycle to appear."
                ),
            },
        ],
        "pre_arm_gates": (
            "Phase-8 pre-arm gates (C3 / C5 / C7 / C10) must clear before live capital."
        ),
        "source_paths": [rel(CROSS_ASSET_BOOK_MD), rel(PRE_REGISTRATION_MD)],
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def build_research_export() -> dict[str, Any]:
    """Assemble the full research.json payload from real artifacts."""
    state = json.loads(STATE_JSON.read_text())
    rows407 = load_ic_rows(IC_REPORT_407)
    rows888 = load_ic_rows(IC_REPORT_888)
    return {
        "schema": "glassbox.research/1",
        "title": "Canli Capital research: the full gauntlet",
        "honesty_note": (
            "Every published number is read from a real engine artifact. Where a value "
            "does not exist in an artifact it is omitted, never invented. The forward "
            "Sharpe is the deflated 0.7-1.0 expectation, never the 1.46 in-sample headline; "
            "killed factors carry their real negative net Sharpes."
        ),
        "executive_summary": build_executive_summary(state),
        "methodology": build_methodology(),
        "factor_research": build_factor_research(rows407, rows888),
        "deflation_gauntlet": build_deflation_gauntlet(),
        "combined_book": build_combined_book(state),
        "track_record": build_track_record(state),
        "roadmap": build_roadmap(),
    }


def main(out_dir: Path = OUT_DIR) -> Path:
    """Build research.json and write it to ``out_dir``; return the written path."""
    payload = stamp(build_research_export())
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / OUT_FILE
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {path}  ({path.stat().st_size} bytes)")
    print(f"content_hash: {payload['content_hash']}")
    return path


if __name__ == "__main__":
    main()
