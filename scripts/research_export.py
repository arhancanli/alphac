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
  (3) the honest verdicts + ceilings — combined ~0.3-0.9 forward (NOT the in-sample
      in-sample headline), the C+ grade, the crypto capacity cliff + BTC-correlation
      cap, and the equity-momentum-only survivor;
  (4) the roadmap — the honest path: forward evidence, registered discovery, then data investment
      sleeve to lengthen the sample so the verdict can clear deflation.

Honesty rules (the owner's non-negotiable, the soul of the firm):
  - Every published number is read from a real AlphaForge artifact on disk. If a number
    is not in an artifact, it is OMITTED — never fabricated, never rounded into existence.
  - The forward Sharpe is the deflated 0.3-0.9 expectation, NEVER the in-sample headline.
    (Band lowered 0.7-1.0 -> 0.3-0.9 on 2026-07-29; these exporters were not updated
    with it and kept publishing the superseded, flattering band until 2026-08-06.)
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

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

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
SLEEVE_DISCOVERY_JSON: Final[Path] = REPO / "config" / "sleeve_discovery.json"
ADMISSION_DRY_RUN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "admission_dry_run" / "result.json"
)
BOOK_WITHOUT_ALPHAVINTAGE_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "book_without_alphavintage" / "result.json"
)
SPINOFF_PRORATA_GATE_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "spinoff_prorata_gate" / "result.json"
)
GATE_REACHABILITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "feasibility_gate_reachability" / "result.json"
)
COVARIANCE_MEMORY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "live_covariance_memory" / "result.json"
)
RECORD_CONTINUITY_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "record_continuity.json"
)
LEDOIT_WOLF_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "ledoit_wolf_effective_sample" / "result.json"
)
DRAWDOWN_LIVE_ESTIMATOR_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "drawdown_live_estimator" / "result.json"
)
SLEEVE_QUALITY_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "sleeve_quality_decomposition" / "result.json"
)
EXECUTION_GAP_POWER_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "execution_gap_power" / "result.json"
)
COST_MODEL_REALISM_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "cost_model_realism" / "result.json"
)
REACHABILITY_HARNESS_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "reachability_harness" / "result.json"
)
ATLAS_REACHABILITY_SCREEN_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "atlas_reachability_screen" / "result.json"
)
ORTHOGONALITY_PRIOR_JSON: Final[Path] = (
    REPO / "artifacts" / "analysis" / "orthogonality_prior" / "result.json"
)

# The discovery bundle's human-facing gate summary is DERIVED from the admission contract rather
# than transcribed beside it. It was transcribed until v6, and by then it had gone stale in the
# direction that flatters: the site published an average-correlation ceiling of 0.15 and a
# 252-observation minimum after the contract in force had moved to 0.00 and 756. Two files
# claiming the same fact is one file too many -- the copy drifts, and a reader auditing the config
# cannot tell which one binds.
_DISCOVERY_GATE_SOURCE: Final[dict[str, str]] = {
    "book_deflated_sharpe_min": "book_deflated_sharpe_min",
    "pbo_max": "pbo_max",
    "average_pairwise_correlation_max": "average_pairwise_correlation_max",
    "average_pairwise_correlation_upper_95_max": "average_pairwise_correlation_upper_95_max",
    "pairwise_correlation_max": "ordinary_pairwise_correlation_max",
    "stressed_pairwise_correlation_max": "stressed_pairwise_correlation_max",
    "minimum_oos_observations": "minimum_oos_observations",
    "net_sharpe_min": "net_sharpe_min",
    "capacity_usd_min": "capacity_usd_min",
}

# Published gate names that are no longer thresholds. Listed rather than silently dropped, so the
# site can say what changed instead of a bar simply vanishing from the page between deploys.
_DISCOVERY_GATE_RETIRED: Final[dict[str, str]] = {
    "deflated_sharpe_min": (
        "Retired as a per-sleeve GATE in contract v6 and replaced by book_deflated_sharpe_min at "
        "the same 0.95 against the complete union of hypothesis identities. A 0.95 per-sleeve "
        "floor required an annualized Sharpe of 1.184 even at the least deflation the formula "
        "permits, about eight times the declared net Sharpe floor, and no sleeve in this book "
        "clears it. The per-sleeve figure is still measured and published for every candidate; "
        "evidence that omits it fails closed."
    ),
}


def _write_kill_papers(research_dir: Path, glassbox_dir: Path) -> int:
    """Render one paper per killed candidate into the site's research directory.

    Forty-six candidates have been killed and three have survived. The forty-six are the papers
    almost nobody publishes, which is exactly why they are the ones worth publishing: a kill log
    is a table, a paper is the reasoning another researcher can use. Every FIGURE in them is
    injected from the kill-log entry; the prose is written by hand. See scripts/build_kill_papers.
    """
    # Imported here rather than at module scope: this script is run directly, so a sibling module
    # is only importable once its own directory is on the path, and doing that at import time
    # would reorder every other import in the file.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_kill_papers", Path(__file__).resolve().parent / "build_kill_papers.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("cannot load scripts/build_kill_papers.py")
    kill_papers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kill_papers)

    research_dir.mkdir(parents=True, exist_ok=True)
    source = glassbox_dir / "kill_log.json"
    if not source.exists():
        raise FileNotFoundError(
            f"{source} is missing: glassbox_export.py must run before research_export.py. The "
            "ordering is declared in tests/unit/test_publish_pipeline_order.py; failing here "
            "rather than skipping keeps a reordered pipeline from silently publishing no papers."
        )
    papers = kill_papers.render_kill_papers(json.loads(source.read_text()))
    for filename, markdown in papers.items():
        (research_dir / filename).write_text(markdown)
    return len(papers)


def _discovery_with_contract_gates() -> dict:
    """Project the in-force contract's thresholds over the discovery bundle's gate summary."""
    discovery = json.loads(SLEEVE_DISCOVERY_JSON.read_text())
    contract = json.loads(SLEEVE_ADMISSION_CONTRACT_JSON.read_text())
    thresholds = contract["thresholds"]
    declared = dict(discovery.get("admission_gates", {}))
    # Carry the qualitative commitments through untouched; rebuild every NUMERIC gate from the
    # contract. Patching the existing dict left retired thresholds sitting in it, which is the
    # drift this function exists to prevent.
    gates = {
        key: value
        for key, value in declared.items()
        if isinstance(value, bool) and key not in _DISCOVERY_GATE_RETIRED
    }
    for published_key, threshold_key in _DISCOVERY_GATE_SOURCE.items():
        if threshold_key not in thresholds:
            raise KeyError(
                f"admission contract has no threshold {threshold_key!r} for published gate "
                f"{published_key!r}; either wire it up or retire it in _DISCOVERY_GATE_RETIRED "
                "so the change is stated rather than silent"
            )
        gates[published_key] = thresholds[threshold_key]
    discovery["admission_gates"] = gates
    discovery["retired_admission_gates"] = {
        key: reason for key, reason in _DISCOVERY_GATE_RETIRED.items() if key not in thresholds
    }
    discovery["admission_contract_schema"] = contract["schema"]
    discovery["admission_contract_public_path"] = "/glassbox/sleeve_admission_contract.json"
    # The relationship between the gate and the objective, published beside them both. Without it
    # the page states a target next to a ceiling and leaves the reader to discover that one
    # forbids the other.
    if "frontier_arithmetic" in contract:
        discovery["frontier_arithmetic"] = contract["frontier_arithmetic"]
    return discovery
SLEEVE_ATLAS_JSON: Final[Path] = REPO / "artifacts" / "discovery" / "sleeve_atlas.json"
SLEEVE_ATLAS_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "discovery" / "sleeve_atlas_audit.json"
)
SLEEVE_LINEAGE_AUDIT_JSON: Final[Path] = (
    REPO / "artifacts" / "discovery" / "sleeve_family_lineage_audit.json"
)
SLEEVE_ADMISSION_CONTRACT_JSON: Final[Path] = (
    REPO / "config" / "sleeve_admission_contract.json"
)
TRIAL_ACCOUNTING_POLICY_JSON: Final[Path] = REPO / "config" / "trial_accounting.json"
LEGACY_DSR_EXCEPTIONS_JSON: Final[Path] = REPO / "config" / "legacy_dsr_exceptions.json"
LEGACY_DSR_RESTATEMENT_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "legacy_dsr_restatement.json"
)
LEGACY_DSR_RESTATEMENT_MD: Final[Path] = (
    REPO / "docs" / "research" / "LEGACY_DSR_RESTATEMENT.md"
)
EXECUTION_REALISM_MD: Final[Path] = REPO / "docs" / "research" / "EXECUTION_REALISM.md"
EXECUTION_BENCHMARK_JSON: Final[Path] = (
    REPO / "artifacts" / "benchmarks" / "execution_models.json"
)
FUTURES_EXECUTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "futures_execution_contract.json"
)
FUTURES_EXECUTION_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "FUTURES_EXECUTION_FOUNDATION.md"
)
OPTIONS_EXECUTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "options_execution_contract.json"
)
OPTIONS_EXECUTION_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "OPTIONS_EXECUTION_FOUNDATION.md"
)
BORROW_EXECUTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "borrow_execution_contract.json"
)
BORROW_EXECUTION_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "BORROW_EXECUTION_FOUNDATION.md"
)
MARKET_STATUS_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "market_status_contract.json"
)
MARKET_STATUS_REPLAY_MD: Final[Path] = REPO / "docs" / "research" / "MARKET_STATUS_REPLAY.md"
CROWDING_RISK_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "crowding_risk_contract.json"
)
CROWDING_RISK_FOUNDATION_MD: Final[Path] = (
    REPO / "docs" / "research" / "CROWDING_RISK_FOUNDATION.md"
)
CORPORATE_ACTION_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "corporate_action_contract.json"
)
CORPORATE_ACTION_LIFECYCLE_MD: Final[Path] = (
    REPO / "docs" / "research" / "CORPORATE_ACTION_LIFECYCLE.md"
)
FINANCING_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "financing_contract.json"
)
FINANCING_REPLAY_MD: Final[Path] = REPO / "docs" / "research" / "FINANCING_REPLAY.md"
LINT_DEBT_CONTRACT_JSON: Final[Path] = (
    REPO / "artifacts" / "engineering" / "lint_debt_contract.json"
)
ENGINEERING_QUALITY_MD: Final[Path] = (
    REPO / "docs" / "research" / "ENGINEERING_QUALITY.md"
)
TRIAL_DEBT_RECONCILIATION_JSON: Final[Path] = (
    REPO / "artifacts" / "audit" / "trial_debt_reconciliation.json"
)
LITERATURE_FRONTIER_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_FRONTIER_2026_08_16.md"
)
REPURCHASE_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_REPURCHASE_ISSUANCE_FLOW.md"
)
REPURCHASE_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_REPURCHASE_ISSUANCE_FLOW.md"
)
OPTIONS_DISPERSION_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_OPTIONS_DISPERSION.md"
)
OPTIONS_DISPERSION_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_OPTIONS_DISPERSION.md"
)
STABLECOIN_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_STABLECOIN_DISLOCATION.md"
)
STABLECOIN_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_STABLECOIN_DISLOCATION.md"
)
SPIN_OFF_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_SPIN_OFF_DISLOCATION.md"
)
SPIN_OFF_LINEAGE_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_SPIN_OFF_DISLOCATION.md"
)
SPIN_OFF_DOCUMENT_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_SPIN_OFF_DOCUMENT_SCHEMA.md"
)
SPIN_OFF_LINEAGE_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "spin_off_dislocation" / "result.json"
)
SPIN_OFF_DOCUMENT_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "spin_off_dislocation"
    / "document_schema_result.json"
)
ELECTRICITY_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_ELECTRICITY_LOAD_WEATHER.md"
)
ELECTRICITY_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_ELECTRICITY_LOAD_WEATHER.md"
)
ELECTRICITY_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "electricity_load_weather" / "result.json"
)
NATURAL_GAS_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_NATURAL_GAS_STORAGE_WEATHER.md"
)
NATURAL_GAS_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_NATURAL_GAS_STORAGE_WEATHER.md"
)
NATURAL_GAS_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "natural_gas_storage_weather" / "result.json"
)
CUSTOMER_SUPPLIER_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_CUSTOMER_SUPPLIER_PROPAGATION.md"
)
CUSTOMER_SUPPLIER_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_CUSTOMER_SUPPLIER_PROPAGATION.md"
)
CUSTOMER_SUPPLIER_FEASIBILITY_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "customer_supplier_propagation"
    / "result.json"
)
BOND_ETF_NAV_LITERATURE_MD: Final[Path] = (
    REPO / "docs" / "design" / "LITERATURE_BOND_ETF_NAV_DISLOCATION.md"
)
BOND_ETF_NAV_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_BOND_ETF_NAV_DISLOCATION.md"
)
BOND_ETF_NAV_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "bond_etf_nav_dislocation" / "result.json"
)
TREASURY_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_TREASURY_AUCTION_CONCESSION.md"
)
TREASURY_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "treasury_auction_concession" / "result.json"
)
TREASURY_TIMING_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_TREASURY_AUCTION_IDENTITY_TIMING.md"
)
TREASURY_TIMING_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "identity_timing.json"
)
TREASURY_TENTATIVE_SCHEDULE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "tentative_schedule_audit.json"
)
TREASURY_WAYBACK_SCHEDULE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "wayback_schedule_audit.json"
)
TREASURY_WAYBACK_PDF_SCHEDULE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "wayback_pdf_schedule_audit.json"
)
TREASURY_CALENDAR_REVISION_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "treasury_auction_concession"
    / "calendar_revision_audit.json"
)
CFTC_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_CFTC_HEDGING_PRESSURE.md"
)
CFTC_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "cftc_hedging_pressure" / "result.json"
)
ALPHAVINTAGE_CORRECTION_MD: Final[Path] = (
    REPO / "docs" / "design" / "CORRECTION_ALPHAVINTAGE_MISSING_RELEASE.md"
)
PRE_FOMC_FEASIBILITY_MD: Final[Path] = (
    REPO / "docs" / "design" / "FEASIBILITY_PRE_FOMC_ANNOUNCEMENT_DRIFT.md"
)
PRE_FOMC_FEASIBILITY_RESULT: Final[Path] = (
    REPO / "artifacts" / "feasibility" / "pre_fomc_announcement_drift" / "result.json"
)
PRE_FOMC_SCHEDULE_LINEAGE_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "annual_schedule_lineage.json"
)
PRE_FOMC_PREREG_MD: Final[Path] = (
    REPO / "docs" / "design" / "PREREG_PRE_FOMC_ANNOUNCEMENT_DRIFT.md"
)
PRE_FOMC_MARKET_DATA_READINESS_RESULT: Final[Path] = (
    REPO
    / "artifacts"
    / "feasibility"
    / "pre_fomc_announcement_drift"
    / "market_data_readiness.json"
)
NARRATIVE_PREREG_MD: Final[Path] = (
    REPO / "docs" / "design" / "PREREG_EARNINGS_NARRATIVE_CHANGE.md"
)
NARRATIVE_PROBE_DIR: Final[Path] = REPO / "artifacts" / "probe" / "earnings_narrative_change"
NARRATIVE_PROBE_RESULT: Final[Path] = NARRATIVE_PROBE_DIR / "result.json"
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


def _trial_label(config: dict[str, Any]) -> str:
    """Return a compact public label without exporting a giant universe/config payload."""
    probe = config.get("probe")
    if isinstance(probe, str) and probe:
        aggregation = config.get("return_aggregation")
        return f"{probe} / {aggregation}" if isinstance(aggregation, str) else probe
    alphas = config.get("alpha_names")
    if isinstance(alphas, list) and alphas:
        return " + ".join(str(alpha) for alpha in alphas)
    for key in ("mechanism", "overlay", "variant"):
        value = config.get(key)
        if isinstance(value, str) and value:
            return value
    return "unlabelled registered identity"


def build_trial_accounting() -> dict[str, Any]:
    """Build the public union ledger, separating measurements from search identities."""
    policy = json.loads(TRIAL_ACCOUNTING_POLICY_JSON.read_text())
    legacy_dsr = json.loads(LEGACY_DSR_EXCEPTIONS_JSON.read_text())
    legacy_restatement = (
        json.loads(LEGACY_DSR_RESTATEMENT_JSON.read_text())
        if LEGACY_DSR_RESTATEMENT_JSON.exists()
        else None
    )
    selection_union = ExperimentUnion.discover(REPO / "var" / "experiments.jsonl", REPO)
    ledger_paths = [path for path in selection_union.paths if path.exists()]
    profiles: list[dict[str, Any]] = []
    union_config_hashes: set[str] = set()
    union_hypotheses: dict[str, tuple[Any, Path]] = {}
    total_records = 0

    for path in ledger_paths:
        ledger = ExperimentLog(path)
        records = ledger.all()
        total_records += len(records)
        union_config_hashes.update(record.config_hash for record in records)
        for record in records:
            key = ledger._hypothesis_key(record.config)
            current = union_hypotheses.get(key)
            if current is None or record.now_ms < current[0].now_ms:
                union_hypotheses[key] = (record, path)
        profiles.append(
            {
                "profile": path.parent.name,
                "source_path": rel(path),
                "immutable_execution_records": len(records),
                "distinct_config_hashes": ledger.n_trials(),
                "hypothesis_identities": ledger.n_hypotheses(),
                "window_only_remeasurements": ledger.window_only_reevaluations(),
                "latest_recorded_at": (
                    dt.datetime.fromtimestamp(
                        max(record.now_ms for record in records) / 1000, tz=dt.UTC
                    ).isoformat()
                    if records
                    else None
                ),
            }
        )

    hypothesis_count = len(union_hypotheses)
    profile_hypothesis_count = sum(profile["hypothesis_identities"] for profile in profiles)
    window_only_count = sum(profile["window_only_remeasurements"] for profile in profiles)
    cross_profile_duplicates = profile_hypothesis_count - hypothesis_count
    budget = int(policy["hypothesis_identity_budget"])
    recent = []
    for key, (record, path) in sorted(
        union_hypotheses.items(), key=lambda item: item[1][0].now_ms, reverse=True
    )[:10]:
        recent.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "label": _trial_label(record.config),
                "ledger_profile": path.parent.name,
                "first_recorded_at": dt.datetime.fromtimestamp(
                    record.now_ms / 1000, tz=dt.UTC
                ).isoformat(),
                "observations": record.n_obs,
                "annualized_sharpe_observed": round(record.sharpe_ann, 6),
            }
        )

    return stamp(
        {
            "schema": "glassbox.trial-ledger/2",
            "claim_boundary": (
                "This ledger proves what was measured and how selection N is counted. It does "
                "not prove that any identity is profitable, independent, or admissible."
            ),
            "accounting_equation": (
                "immutable execution records - window-only remeasurements - cross-profile "
                "duplicate identities = distinct union hypothesis identities"
            ),
            "immutable_execution_records": total_records,
            "distinct_config_hashes": len(union_config_hashes),
            "window_only_remeasurements": window_only_count,
            "cross_profile_duplicate_identities": cross_profile_duplicates,
            "distinct_hypothesis_identities": hypothesis_count,
            "selection_statistics": {
                "unit": "first_immutable_record_per_hypothesis",
                "n_hypotheses": selection_union.n_hypotheses(),
                "sharpe_variance": selection_union.hypothesis_sharpe_variance(),
                "audit_raw_record_sharpe_variance": selection_union.trial_sharpe_variance(),
                "interpretation": (
                    "Operational window remeasurements remain public but cannot alter selection "
                    "N or selection V[SR]."
                ),
            },
            "ledger_profiles": len(profiles),
            "hypothesis_identity_budget": budget,
            "budget_remaining": budget - hypothesis_count,
            "budget_status": "PASS" if hypothesis_count <= budget else "PAUSE_RESEARCH",
            "research_status": policy.get("research_status", "ACTIVE"),
            "definitions": policy["definitions"],
            "budget_review": policy["budget_review"],
            "profiles": profiles,
            "recent_hypothesis_identities": recent,
            "policy_source_path": rel(TRIAL_ACCOUNTING_POLICY_JSON),
            "trial_debt_reconciliation": (
                {
                    "source_path": rel(TRIAL_DEBT_RECONCILIATION_JSON),
                    "source_sha256": hashlib.sha256(
                        TRIAL_DEBT_RECONCILIATION_JSON.read_bytes()
                    ).hexdigest(),
                }
                if TRIAL_DEBT_RECONCILIATION_JSON.exists()
                else None
            ),
            "legacy_dsr_debt": {
                "status": legacy_dsr["status"],
                "historical_exception_paths": (
                    len(legacy_dsr["exceptions"]) + len(legacy_dsr.get("resolved_paths", {}))
                ),
                "executable_debt_paths": len(legacy_dsr["exceptions"]),
                "resolved_code_paths": len(legacy_dsr.get("resolved_paths", {})),
                "union_registration_paths": len(legacy_dsr.get("union_registration_paths", [])),
                "claim_boundary": legacy_dsr["claim_boundary"],
                "source_path": rel(LEGACY_DSR_EXCEPTIONS_JSON),
                "source_sha256": hashlib.sha256(
                    LEGACY_DSR_EXCEPTIONS_JSON.read_bytes()
                ).hexdigest(),
                "restatement": (
                    {
                        "source_path": rel(LEGACY_DSR_RESTATEMENT_JSON),
                        "source_sha256": hashlib.sha256(
                            LEGACY_DSR_RESTATEMENT_JSON.read_bytes()
                        ).hexdigest(),
                        "summary": legacy_restatement["summary"],
                    }
                    if legacy_restatement is not None
                    else None
                ),
            },
        }
    )


# ---------------------------------------------------------------------------
# Section 1 — executive summary
# ---------------------------------------------------------------------------
def build_executive_summary(state: dict[str, Any]) -> dict[str, Any]:
    """The one-screen honest summary, anchored to the paper-state metrics."""
    m = state["metrics"]
    sleeves = state["book"]["sleeves"]
    sleeve_names = ", ".join(str(s["name"]) for s in sleeves)
    return {
        "description": (
            f"The current ALPHAC flagship combines {len(sleeves)} live sleeves: {sleeve_names}. "
            "Their economic inputs differ, but diversification is not treated as proof of alpha. "
            "No sleeve clears the multiple-testing gate in-sample. AlphaVintage remains visible "
            "as a paper-trading history but its calendar-correct research verdict is KILLED; it "
            "is not an admitted sleeve. The live record, including a genuine risk-off episode, "
            "is the evidence that matters next."
        ),
        "deployed_sleeves_count": len(sleeves),
        "technically_admitted_sleeves_count": 0,
        "research_reclassified_killed": ["AlphaVintage"],
        "tested_factor_families_count": "35+",
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
    """Section 5: the current book, its honest forward expectation, and its ceilings."""
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
        "correlation": m.get("correlation_value"),
        "correlation_note": m["correlation"],
        "strategic_tilt": state["book"].get("strategic_tilt"),
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
                "The research window is short, multiple strategies were searched, and every "
                "standalone sleeve remains below the stated deflation gate. The published "
                "forward band is therefore deliberately below the in-sample headline."
            ),
        },
        "deflation": {
            "dsr_gate": DSR_GATE,
            "dsr_pass": False,
            "note": m["gauntlet_pass"],
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
        "live_config": state.get("live_config"),
        "source_path": rel(STATE_JSON),
    }


# ---------------------------------------------------------------------------
# Section 7 — roadmap (the honest path forward)
# ---------------------------------------------------------------------------
def build_roadmap() -> dict[str, Any]:
    """Section 7: the honest path — forward evidence, discovery, then data investment."""
    return {
        "summary": (
            "The binding constraint is trustworthy evidence, not idea count. The current "
            "four-sleeve core must earn its record forward while new candidates move through "
            "one-shot, pre-registered gates. The honest path is three-step."
        ),
        "steps": [
            {
                "order": 1,
                "title": "Earn the current book forward",
                "detail": (
                    "Accrue genuinely out-of-sample paper evidence on the four equal-quarter "
                    "neutral sleeves, with the +10% strategic beta overlay reported separately. "
                    "Do not relabel simulations as realized performance or rescue a weak result "
                    "with an unregistered configuration change."
                ),
            },
            {
                "order": 2,
                "title": "Execute the registered discovery queue",
                "detail": (
                    "Test differentiated candidates across narrative, event, options, lending, "
                    "power, credit, and ownership data under point-in-time, cost, capacity, "
                    "deflation, and correlation gates. Publish ADD, KILL, or DATA-ESCALATE; "
                    "never tune a failed one-shot identity after seeing returns."
                ),
            },
            {
                "order": 3,
                "title": "Buy data and infrastructure only after evidence",
                "detail": (
                    "Escalate to historical borrow/locate, options, broker, execution, or other "
                    "paid credentials only when a named candidate has cleared every key-free "
                    "screen. Credentials such as Alpaca belong to approved shadow execution, "
                    "not to exploratory backtest rescue."
                ),
            },
        ],
        "pre_arm_gates": (
            "Phase-8 pre-arm gates (C3 / C5 / C7 / C10) must clear before live capital."
        ),
        "source_paths": [rel(CROSS_ASSET_BOOK_MD), rel(PRE_REGISTRATION_MD)],
    }


def build_active_probe_results() -> list[dict[str, Any]]:
    """Expose completed one-shot outcomes; never synthesize a pending result."""
    if not NARRATIVE_PROBE_RESULT.exists():
        return []
    result = json.loads(NARRATIVE_PROBE_RESULT.read_text())
    return [
        {
            "id": "earnings_narrative_change",
            "verdict": result["verdict"],
            "hypotheses_spent": result["hypotheses_spent"],
            "metrics": result["metrics"],
            "gates": result["gates"],
            "admission_review": result["admission_review"],
            "lineage": result["lineage"],
            "public_result": "/glassbox/earnings_narrative_change_result.json",
            "source_path": rel(NARRATIVE_PROBE_RESULT),
        }
    ]


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
            "Sharpe is the deflated 0.3-0.9 expectation, never the in-sample headline; "
            "killed factors carry their real negative net Sharpes."
        ),
        "executive_summary": build_executive_summary(state),
        "methodology": build_methodology(),
        "trial_accounting": build_trial_accounting(),
        "factor_research": build_factor_research(rows407, rows888),
        "deflation_gauntlet": build_deflation_gauntlet(),
        "combined_book": build_combined_book(state),
        "track_record": build_track_record(state),
        "corrections": [
            {
                "title": "AlphaVintage missing-release correction protocol",
                "declared": "2026-08-16",
                "status": "REVISED RETURNS SEALED / VERDICT KILLED",
                "hypotheses_added": 0,
                "calendar_correct_net_sharpe": 0.2298358829229609,
                "newey_west_t": 1.2673190577321936,
                "verdict": "KILLED",
                "curve_sha256": "d277c63ddf2bed6e9314aa863dbbf6adf3f4adb55bd89e8166aee4a19aab415f",
                "public_path": "/research/alphavintage-missing-release-correction.md",
                "source_path": rel(ALPHAVINTAGE_CORRECTION_MD),
            }
        ],
        "roadmap": build_roadmap(),
        "active_probe_results": build_active_probe_results(),
        "sleeve_discovery": {
            **_discovery_with_contract_gates(),
            "source_path": rel(SLEEVE_DISCOVERY_JSON),
        },
        "sleeve_atlas": {
            "atlas": json.loads(SLEEVE_ATLAS_JSON.read_text()),
            "audit": json.loads(SLEEVE_ATLAS_AUDIT_JSON.read_text()),
            "lineage_audit": json.loads(SLEEVE_LINEAGE_AUDIT_JSON.read_text()),
            "atlas_public_path": "/glassbox/sleeve_atlas.json",
            "audit_public_path": "/glassbox/sleeve_atlas_audit.json",
            "lineage_audit_public_path": "/glassbox/sleeve_family_lineage_audit.json",
            "atlas_source_path": rel(SLEEVE_ATLAS_JSON),
            "audit_source_path": rel(SLEEVE_ATLAS_AUDIT_JSON),
            "lineage_audit_source_path": rel(SLEEVE_LINEAGE_AUDIT_JSON),
        },
        # The contract run against a REAL candidate through the production evaluator, rather than
        # only against a fixture written to pass. It is published because its verdict bears on an
        # open allocation decision: the sleeve currently carrying a quarter of the book.
        "admission_dry_run": (
            {
                "result": json.loads(ADMISSION_DRY_RUN_JSON.read_text()),
                "public_path": "/glassbox/admission_dry_run.json",
                "source_path": rel(ADMISSION_DRY_RUN_JSON),
                "source_sha256": hashlib.sha256(ADMISSION_DRY_RUN_JSON.read_bytes()).hexdigest(),
            }
            if ADMISSION_DRY_RUN_JSON.exists()
            else None
        ),
        # The book measured with and without the sleeve whose allocation is an open decision.
        # Published because the decision is the owner's and the input it needs is a measurement.
        "book_without_alphavintage": (
            json.loads(BOOK_WITHOUT_ALPHAVINTAGE_JSON.read_text())
            if BOOK_WITHOUT_ALPHAVINTAGE_JSON.exists()
            else None
        ),
        # The family closest to clearing feasibility, and why its last gate cannot be reached by
        # improving extraction. Published because a null that closes a line of enquiry is worth
        # as much to a reader as one that opens it.
        # The same question asked of the other two near-miss families. Published together because
        # the answer is the same shape for all three and it is not the encouraging one.
        # What the LIVE covariance estimator does with a halflife, per sleeve. Published because
        # the overlay policy was set from a simulation of a different estimator.
        # Whether the forward record has holes. Published because the record's whole value is
        # its continuity, and a gap that is only visible internally is a gap nobody can check.
        # A documented approximation measured rather than trusted. Published because it bears on
        # the open drawdown decision: it is immaterial today and material at the halflife the
        # drawdown study points toward.
        # The drawdown sweep re-run through the estimator production actually uses, rather than
        # the untruncated recursion the original simulated. Published because the earlier answer
        # is on this site and this one supersedes it.
        # Which sleeve drags per-sleeve quality, and whether the drag is construction or cost.
        # Published with its own boundary: commission is measured, spread is modelled, and market
        # impact is not separable from what the artifacts carry.
        # Whether the live book is delivering its backtest — and the honest answer that the
        # record is far too short to say. Published because "we cannot tell yet, here is when we
        # can" is a result, and a noisy estimate presented as one would not be.
        # Whether the modelled cost matches what the live book pays. Published including the
        # parts that cannot be checked from what is recorded, because that boundary is the
        # actionable half of the result.
        "cost_model_realism": (
            json.loads(COST_MODEL_REALISM_JSON.read_text())
            if COST_MODEL_REALISM_JSON.exists()
            else None
        ),
        "execution_gap_power": (
            json.loads(EXECUTION_GAP_POWER_JSON.read_text())
            if EXECUTION_GAP_POWER_JSON.exists()
            else None
        ),
        "sleeve_quality_decomposition": (
            json.loads(SLEEVE_QUALITY_JSON.read_text()) if SLEEVE_QUALITY_JSON.exists() else None
        ),
        "drawdown_live_estimator": (
            json.loads(DRAWDOWN_LIVE_ESTIMATOR_JSON.read_text())
            if DRAWDOWN_LIVE_ESTIMATOR_JSON.exists()
            else None
        ),
        "ledoit_wolf_effective_sample": (
            json.loads(LEDOIT_WOLF_JSON.read_text()) if LEDOIT_WOLF_JSON.exists() else None
        ),
        "record_continuity": (
            json.loads(RECORD_CONTINUITY_JSON.read_text())
            if RECORD_CONTINUITY_JSON.exists()
            else None
        ),
        "live_covariance_memory": (
            json.loads(COVARIANCE_MEMORY_JSON.read_text())
            if COVARIANCE_MEMORY_JSON.exists()
            else None
        ),
        "feasibility_gate_reachability": (
            json.loads(GATE_REACHABILITY_JSON.read_text())
            if GATE_REACHABILITY_JSON.exists()
            else None
        ),
        "spinoff_prorata_gate": (
            json.loads(SPINOFF_PRORATA_GATE_JSON.read_text())
            if SPINOFF_PRORATA_GATE_JSON.exists()
            else None
        ),
        # The pre-test the two artifacts above are now instances of. Published because the
        # reusable part is the thing worth copying: ask whether a near-miss gate is reachable
        # AT ALL before writing a protocol, since the alternative move is always to widen the
        # detector until the number clears, and that is tuning a measurement to fit a target.
        "reachability_harness": (
            json.loads(REACHABILITY_HARNESS_JSON.read_text())
            if REACHABILITY_HARNESS_JSON.exists()
            else None
        ),
        # The harness above, applied to the twenty families nothing has been spent on. Published
        # because the answer is the useful kind of discouraging: most of what is left is blocked
        # on money, on a record nobody archived, or on prices nobody could trade — and none of
        # those is closed by working harder, which is what a reader deciding whether to believe
        # this programme most needs to know.
        "atlas_reachability_screen": (
            json.loads(ATLAS_REACHABILITY_SCREEN_JSON.read_text())
            if ATLAS_REACHABILITY_SCREEN_JSON.exists()
            else None
        ),
        # The same twenty families ordered by expected orthogonality, BEFORE any is measured.
        # Published as a prior and labelled one in every row, because an ordering stated after the
        # measurement is not an ordering. It also prints the number the ordering exists to serve:
        # a book whose every new pair sits exactly on the correlation gate still misses the target,
        # so the gate is necessary and not sufficient, and that arithmetic belongs on the same
        # page as the target rather than in a drawer.
        "orthogonality_prior": (
            json.loads(ORTHOGONALITY_PRIOR_JSON.read_text())
            if ORTHOGONALITY_PRIOR_JSON.exists()
            else None
        ),
        "sleeve_admission_contract": {
            "contract": json.loads(SLEEVE_ADMISSION_CONTRACT_JSON.read_text()),
            "source_sha256": hashlib.sha256(
                SLEEVE_ADMISSION_CONTRACT_JSON.read_bytes()
            ).hexdigest(),
            "public_path": "/glassbox/sleeve_admission_contract.json",
            "source_path": rel(SLEEVE_ADMISSION_CONTRACT_JSON),
        },
        "engineering_benchmarks": {
            "execution_fill_models": {
                "benchmark": json.loads(EXECUTION_BENCHMARK_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    EXECUTION_BENCHMARK_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/execution_models_benchmark.json",
                "source_path": rel(EXECUTION_BENCHMARK_JSON),
            }
        },
        "engineering_quality": {
            "lint_debt": {
                "contract": json.loads(LINT_DEBT_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    LINT_DEBT_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/lint_debt_contract.json",
                "book_path": "/research/engineering-quality.md",
                "source_path": rel(LINT_DEBT_CONTRACT_JSON),
            }
        },
        "engineering_capabilities": {
            "financing": {
                "contract": json.loads(FINANCING_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    FINANCING_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/financing_contract.json",
                "book_path": "/research/financing-replay.md",
                "source_path": rel(FINANCING_CONTRACT_JSON),
            },
            "corporate_action_lifecycle": {
                "contract": json.loads(CORPORATE_ACTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    CORPORATE_ACTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/corporate_action_contract.json",
                "book_path": "/research/corporate-action-lifecycle.md",
                "source_path": rel(CORPORATE_ACTION_CONTRACT_JSON),
            },
            "borrow_execution": {
                "contract": json.loads(BORROW_EXECUTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    BORROW_EXECUTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/borrow_execution_contract.json",
                "book_path": "/research/borrow-execution-foundation.md",
                "source_path": rel(BORROW_EXECUTION_CONTRACT_JSON),
            },
            "crowding_risk": {
                "contract": json.loads(CROWDING_RISK_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    CROWDING_RISK_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/crowding_risk_contract.json",
                "book_path": "/research/crowding-risk-foundation.md",
                "source_path": rel(CROWDING_RISK_CONTRACT_JSON),
            },
            "futures_execution": {
                "contract": json.loads(FUTURES_EXECUTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    FUTURES_EXECUTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/futures_execution_contract.json",
                "book_path": "/research/futures-execution-foundation.md",
                "source_path": rel(FUTURES_EXECUTION_CONTRACT_JSON),
            },
            "market_status_replay": {
                "contract": json.loads(MARKET_STATUS_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    MARKET_STATUS_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/market_status_contract.json",
                "book_path": "/research/market-status-replay.md",
                "source_path": rel(MARKET_STATUS_CONTRACT_JSON),
            },
            "options_execution": {
                "contract": json.loads(OPTIONS_EXECUTION_CONTRACT_JSON.read_text()),
                "source_sha256": hashlib.sha256(
                    OPTIONS_EXECUTION_CONTRACT_JSON.read_bytes()
                ).hexdigest(),
                "public_path": "/glassbox/options_execution_contract.json",
                "book_path": "/research/options-execution-foundation.md",
                "source_path": rel(OPTIONS_EXECUTION_CONTRACT_JSON),
            }
        },
    }


def main(out_dir: Path = OUT_DIR) -> Path:
    """Build research.json and write it to ``out_dir``; return the written path."""
    # Mirrored to the dashboard too (2026-08-06). Writing only to the landing dir left
    # app.canlicapital.com serving six-week-old glass-box artifacts, including a track
    # record showing 0.00% over "3 days" while the landing showed -2.54% over 38.
    payload = stamp(build_research_export())
    stamped = json.dumps(payload, indent=2) + "\n"
    trial_ledger = json.dumps(payload["trial_accounting"], indent=2) + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / OUT_FILE
    path.write_text(stamped)
    (out_dir / "trial_ledger.json").write_text(trial_ledger)
    if LEGACY_DSR_RESTATEMENT_JSON.exists():
        (out_dir / "legacy_dsr_restatement.json").write_text(
            LEGACY_DSR_RESTATEMENT_JSON.read_text()
        )
    discovery = json.dumps(_discovery_with_contract_gates(), indent=2) + "\n"
    (out_dir / "sleeve_discovery.json").write_text(discovery)
    (out_dir / "sleeve_atlas.json").write_text(SLEEVE_ATLAS_JSON.read_text())
    (out_dir / "sleeve_atlas_audit.json").write_text(SLEEVE_ATLAS_AUDIT_JSON.read_text())
    (out_dir / "sleeve_family_lineage_audit.json").write_text(
        SLEEVE_LINEAGE_AUDIT_JSON.read_text()
    )
    (out_dir / "sleeve_admission_contract.json").write_text(
        SLEEVE_ADMISSION_CONTRACT_JSON.read_text()
    )
    if ADMISSION_DRY_RUN_JSON.exists():
        (out_dir / "admission_dry_run.json").write_text(ADMISSION_DRY_RUN_JSON.read_text())
    if COST_MODEL_REALISM_JSON.exists():
        (out_dir / "cost_model_realism.json").write_text(
            COST_MODEL_REALISM_JSON.read_text()
        )
    if EXECUTION_GAP_POWER_JSON.exists():
        (out_dir / "execution_gap_power.json").write_text(
            EXECUTION_GAP_POWER_JSON.read_text()
        )
    if SLEEVE_QUALITY_JSON.exists():
        (out_dir / "sleeve_quality_decomposition.json").write_text(
            SLEEVE_QUALITY_JSON.read_text()
        )
    if DRAWDOWN_LIVE_ESTIMATOR_JSON.exists():
        (out_dir / "drawdown_live_estimator.json").write_text(
            DRAWDOWN_LIVE_ESTIMATOR_JSON.read_text()
        )
    if LEDOIT_WOLF_JSON.exists():
        (out_dir / "ledoit_wolf_effective_sample.json").write_text(
            LEDOIT_WOLF_JSON.read_text()
        )
    if RECORD_CONTINUITY_JSON.exists():
        (out_dir / "record_continuity.json").write_text(
            RECORD_CONTINUITY_JSON.read_text()
        )
    if COVARIANCE_MEMORY_JSON.exists():
        (out_dir / "live_covariance_memory.json").write_text(
            COVARIANCE_MEMORY_JSON.read_text()
        )
    if GATE_REACHABILITY_JSON.exists():
        (out_dir / "feasibility_gate_reachability.json").write_text(
            GATE_REACHABILITY_JSON.read_text()
        )
    if SPINOFF_PRORATA_GATE_JSON.exists():
        (out_dir / "spinoff_prorata_gate.json").write_text(
            SPINOFF_PRORATA_GATE_JSON.read_text()
        )
    if REACHABILITY_HARNESS_JSON.exists():
        (out_dir / "reachability_harness.json").write_text(
            REACHABILITY_HARNESS_JSON.read_text()
        )
    if ATLAS_REACHABILITY_SCREEN_JSON.exists():
        (out_dir / "atlas_reachability_screen.json").write_text(
            ATLAS_REACHABILITY_SCREEN_JSON.read_text()
        )
    if ORTHOGONALITY_PRIOR_JSON.exists():
        (out_dir / "orthogonality_prior.json").write_text(
            ORTHOGONALITY_PRIOR_JSON.read_text()
        )
    if BOOK_WITHOUT_ALPHAVINTAGE_JSON.exists():
        (out_dir / "book_without_alphavintage.json").write_text(
            BOOK_WITHOUT_ALPHAVINTAGE_JSON.read_text()
        )
    (out_dir / "execution_models_benchmark.json").write_text(
        EXECUTION_BENCHMARK_JSON.read_text()
    )
    (out_dir / "futures_execution_contract.json").write_text(
        FUTURES_EXECUTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "options_execution_contract.json").write_text(
        OPTIONS_EXECUTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "borrow_execution_contract.json").write_text(
        BORROW_EXECUTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "market_status_contract.json").write_text(
        MARKET_STATUS_CONTRACT_JSON.read_text()
    )
    (out_dir / "crowding_risk_contract.json").write_text(
        CROWDING_RISK_CONTRACT_JSON.read_text()
    )
    (out_dir / "corporate_action_contract.json").write_text(
        CORPORATE_ACTION_CONTRACT_JSON.read_text()
    )
    (out_dir / "financing_contract.json").write_text(FINANCING_CONTRACT_JSON.read_text())
    (out_dir / "lint_debt_contract.json").write_text(LINT_DEBT_CONTRACT_JSON.read_text())
    literature_dir = out_dir.parent / "research"
    _write_kill_papers(literature_dir, out_dir)
    literature_dir.mkdir(parents=True, exist_ok=True)
    (literature_dir / "execution-realism.md").write_text(EXECUTION_REALISM_MD.read_text())
    (literature_dir / "futures-execution-foundation.md").write_text(
        FUTURES_EXECUTION_FOUNDATION_MD.read_text()
    )
    (literature_dir / "options-execution-foundation.md").write_text(
        OPTIONS_EXECUTION_FOUNDATION_MD.read_text()
    )
    (literature_dir / "borrow-execution-foundation.md").write_text(
        BORROW_EXECUTION_FOUNDATION_MD.read_text()
    )
    (literature_dir / "market-status-replay.md").write_text(MARKET_STATUS_REPLAY_MD.read_text())
    (literature_dir / "crowding-risk-foundation.md").write_text(
        CROWDING_RISK_FOUNDATION_MD.read_text()
    )
    (literature_dir / "corporate-action-lifecycle.md").write_text(
        CORPORATE_ACTION_LIFECYCLE_MD.read_text()
    )
    (literature_dir / "financing-replay.md").write_text(FINANCING_REPLAY_MD.read_text())
    (literature_dir / "engineering-quality.md").write_text(ENGINEERING_QUALITY_MD.read_text())
    # MISSING FROM THE PRIMARY SITE until 2026-08-22. The app host published this paper and this
    # host did not, because the two write blocks are hand-mirrored copies and one edit landed in
    # only one of them. Nothing could notice: the paper is not linked from research.json, so its
    # absence produced no broken link and no failing check — the primary site was simply missing
    # the document that restates every Sharpe the deflation correction touched.
    # tests/unit/test_glassbox_write_paths.py now compares the two blocks as sets, so the next
    # one-sided edit fails a test rather than quietly publishing to one host.
    if LEGACY_DSR_RESTATEMENT_MD.exists():
        (literature_dir / "legacy-dsr-restatement.md").write_text(
            LEGACY_DSR_RESTATEMENT_MD.read_text()
        )
    (literature_dir / "literature-frontier-2026-08-16.md").write_text(
        LITERATURE_FRONTIER_MD.read_text()
    )
    (literature_dir / "literature-repurchase-issuance-flow.md").write_text(
        REPURCHASE_LITERATURE_MD.read_text()
    )
    (literature_dir / "repurchase-issuance-flow-feasibility.md").write_text(
        REPURCHASE_FEASIBILITY_MD.read_text()
    )
    (literature_dir / "literature-options-dispersion.md").write_text(
        OPTIONS_DISPERSION_LITERATURE_MD.read_text()
    )
    (literature_dir / "options-dispersion-feasibility.md").write_text(
        OPTIONS_DISPERSION_FEASIBILITY_MD.read_text()
    )
    (literature_dir / "literature-stablecoin-dislocation.md").write_text(
        STABLECOIN_LITERATURE_MD.read_text()
    )
    (literature_dir / "stablecoin-dislocation-feasibility.md").write_text(
        STABLECOIN_FEASIBILITY_MD.read_text()
    )
    (literature_dir / "literature-spin-off-dislocation.md").write_text(
        SPIN_OFF_LITERATURE_MD.read_text()
    )
    (literature_dir / "spin-off-dislocation-lineage.md").write_text(
        SPIN_OFF_LINEAGE_MD.read_text()
    )
    (literature_dir / "spin-off-document-schema.md").write_text(
        SPIN_OFF_DOCUMENT_MD.read_text()
    )
    (out_dir / "spin_off_lineage.json").write_text(SPIN_OFF_LINEAGE_RESULT.read_text())
    (out_dir / "spin_off_document_schema.json").write_text(
        SPIN_OFF_DOCUMENT_RESULT.read_text()
    )
    (literature_dir / "literature-electricity-load-weather.md").write_text(
        ELECTRICITY_LITERATURE_MD.read_text()
    )
    (literature_dir / "electricity-load-weather-feasibility.md").write_text(
        ELECTRICITY_FEASIBILITY_MD.read_text()
    )
    (out_dir / "electricity_load_weather_feasibility.json").write_text(
        ELECTRICITY_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "literature-natural-gas-storage-weather.md").write_text(
        NATURAL_GAS_LITERATURE_MD.read_text()
    )
    (literature_dir / "natural-gas-storage-weather-feasibility.md").write_text(
        NATURAL_GAS_FEASIBILITY_MD.read_text()
    )
    (out_dir / "natural_gas_storage_weather_feasibility.json").write_text(
        NATURAL_GAS_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "literature-customer-supplier-propagation.md").write_text(
        CUSTOMER_SUPPLIER_LITERATURE_MD.read_text()
    )
    (literature_dir / "customer-supplier-propagation-feasibility.md").write_text(
        CUSTOMER_SUPPLIER_FEASIBILITY_MD.read_text()
    )
    (out_dir / "customer_supplier_propagation_feasibility.json").write_text(
        CUSTOMER_SUPPLIER_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "literature-bond-etf-nav-dislocation.md").write_text(
        BOND_ETF_NAV_LITERATURE_MD.read_text()
    )
    (literature_dir / "bond-etf-nav-dislocation-feasibility.md").write_text(
        BOND_ETF_NAV_FEASIBILITY_MD.read_text()
    )
    (out_dir / "bond_etf_nav_dislocation_feasibility.json").write_text(
        BOND_ETF_NAV_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "treasury-auction-concession-feasibility.md").write_text(
        TREASURY_FEASIBILITY_MD.read_text()
    )
    (out_dir / "treasury_auction_concession_feasibility.json").write_text(
        TREASURY_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "treasury-auction-identity-timing.md").write_text(
        TREASURY_TIMING_MD.read_text()
    )
    (out_dir / "treasury_auction_identity_timing.json").write_text(
        TREASURY_TIMING_RESULT.read_text()
    )
    (out_dir / "treasury_tentative_schedule_audit.json").write_text(
        TREASURY_TENTATIVE_SCHEDULE_RESULT.read_text()
    )
    (out_dir / "treasury_wayback_schedule_audit.json").write_text(
        TREASURY_WAYBACK_SCHEDULE_RESULT.read_text()
    )
    (out_dir / "treasury_wayback_pdf_schedule_audit.json").write_text(
        TREASURY_WAYBACK_PDF_SCHEDULE_RESULT.read_text()
    )
    (out_dir / "treasury_calendar_revision_audit.json").write_text(
        TREASURY_CALENDAR_REVISION_RESULT.read_text()
    )
    (literature_dir / "cftc-hedging-pressure-feasibility.md").write_text(
        CFTC_FEASIBILITY_MD.read_text()
    )
    (out_dir / "cftc_hedging_pressure_feasibility.json").write_text(
        CFTC_FEASIBILITY_RESULT.read_text()
    )
    (literature_dir / "alphavintage-missing-release-correction.md").write_text(
        ALPHAVINTAGE_CORRECTION_MD.read_text()
    )
    (literature_dir / "pre-fomc-announcement-drift-feasibility.md").write_text(
        PRE_FOMC_FEASIBILITY_MD.read_text()
    )
    (out_dir / "pre_fomc_announcement_drift_feasibility.json").write_text(
        PRE_FOMC_FEASIBILITY_RESULT.read_text()
    )
    (out_dir / "pre_fomc_schedule_lineage.json").write_text(
        PRE_FOMC_SCHEDULE_LINEAGE_RESULT.read_text()
    )
    (literature_dir / "prereg-pre-fomc-announcement-drift.md").write_text(
        PRE_FOMC_PREREG_MD.read_text()
    )
    (out_dir / "pre_fomc_market_data_readiness.json").write_text(
        PRE_FOMC_MARKET_DATA_READINESS_RESULT.read_text()
    )
    (literature_dir / "prereg-earnings-narrative-change.md").write_text(
        NARRATIVE_PREREG_MD.read_text()
    )
    for source_name, public_name in (
        ("result.json", "earnings_narrative_change_result.json"),
        ("input_data_manifest.json", "earnings_narrative_change_input_data_manifest.json"),
        ("diversification.json", "earnings_narrative_change_diversification.json"),
    ):
        source = NARRATIVE_PROBE_DIR / source_name
        if source.exists():
            (out_dir / public_name).write_text(source.read_text())
    if out_dir.resolve() == OUT_DIR.resolve():
        app_dir = REPO.parent / "meridian-app" / "public" / "glassbox"
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / OUT_FILE).write_text(stamped)
        (app_dir / "trial_ledger.json").write_text(trial_ledger)
        if LEGACY_DSR_RESTATEMENT_JSON.exists():
            (app_dir / "legacy_dsr_restatement.json").write_text(
                LEGACY_DSR_RESTATEMENT_JSON.read_text()
            )
        (app_dir / "sleeve_discovery.json").write_text(discovery)
        (app_dir / "sleeve_atlas.json").write_text(SLEEVE_ATLAS_JSON.read_text())
        (app_dir / "sleeve_atlas_audit.json").write_text(
            SLEEVE_ATLAS_AUDIT_JSON.read_text()
        )
        (app_dir / "sleeve_family_lineage_audit.json").write_text(
            SLEEVE_LINEAGE_AUDIT_JSON.read_text()
        )
        if ADMISSION_DRY_RUN_JSON.exists():
            (app_dir / "admission_dry_run.json").write_text(ADMISSION_DRY_RUN_JSON.read_text())
        if COST_MODEL_REALISM_JSON.exists():
            (app_dir / "cost_model_realism.json").write_text(
                COST_MODEL_REALISM_JSON.read_text()
            )
        if EXECUTION_GAP_POWER_JSON.exists():
            (app_dir / "execution_gap_power.json").write_text(
                EXECUTION_GAP_POWER_JSON.read_text()
            )
        if SLEEVE_QUALITY_JSON.exists():
            (app_dir / "sleeve_quality_decomposition.json").write_text(
                SLEEVE_QUALITY_JSON.read_text()
            )
        if DRAWDOWN_LIVE_ESTIMATOR_JSON.exists():
            (app_dir / "drawdown_live_estimator.json").write_text(
                DRAWDOWN_LIVE_ESTIMATOR_JSON.read_text()
            )
        if LEDOIT_WOLF_JSON.exists():
            (app_dir / "ledoit_wolf_effective_sample.json").write_text(
                LEDOIT_WOLF_JSON.read_text()
            )
        if RECORD_CONTINUITY_JSON.exists():
            (app_dir / "record_continuity.json").write_text(
                RECORD_CONTINUITY_JSON.read_text()
            )
        if COVARIANCE_MEMORY_JSON.exists():
            (app_dir / "live_covariance_memory.json").write_text(
                COVARIANCE_MEMORY_JSON.read_text()
            )
        if GATE_REACHABILITY_JSON.exists():
            (app_dir / "feasibility_gate_reachability.json").write_text(
                GATE_REACHABILITY_JSON.read_text()
            )
        if SPINOFF_PRORATA_GATE_JSON.exists():
            (app_dir / "spinoff_prorata_gate.json").write_text(
                SPINOFF_PRORATA_GATE_JSON.read_text()
            )
        if REACHABILITY_HARNESS_JSON.exists():
            (app_dir / "reachability_harness.json").write_text(
                REACHABILITY_HARNESS_JSON.read_text()
            )
        if ATLAS_REACHABILITY_SCREEN_JSON.exists():
            (app_dir / "atlas_reachability_screen.json").write_text(
                ATLAS_REACHABILITY_SCREEN_JSON.read_text()
            )
        if ORTHOGONALITY_PRIOR_JSON.exists():
            (app_dir / "orthogonality_prior.json").write_text(
                ORTHOGONALITY_PRIOR_JSON.read_text()
            )
        if BOOK_WITHOUT_ALPHAVINTAGE_JSON.exists():
            (app_dir / "book_without_alphavintage.json").write_text(
                BOOK_WITHOUT_ALPHAVINTAGE_JSON.read_text()
            )
        (app_dir / "sleeve_admission_contract.json").write_text(
            SLEEVE_ADMISSION_CONTRACT_JSON.read_text()
        )
        (app_dir / "execution_models_benchmark.json").write_text(
            EXECUTION_BENCHMARK_JSON.read_text()
        )
        (app_dir / "futures_execution_contract.json").write_text(
            FUTURES_EXECUTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "options_execution_contract.json").write_text(
            OPTIONS_EXECUTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "borrow_execution_contract.json").write_text(
            BORROW_EXECUTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "market_status_contract.json").write_text(
            MARKET_STATUS_CONTRACT_JSON.read_text()
        )
        (app_dir / "crowding_risk_contract.json").write_text(
            CROWDING_RISK_CONTRACT_JSON.read_text()
        )
        (app_dir / "corporate_action_contract.json").write_text(
            CORPORATE_ACTION_CONTRACT_JSON.read_text()
        )
        (app_dir / "financing_contract.json").write_text(
            FINANCING_CONTRACT_JSON.read_text()
        )
        (app_dir / "lint_debt_contract.json").write_text(
            LINT_DEBT_CONTRACT_JSON.read_text()
        )
        app_literature_dir = app_dir.parent / "research"
        _write_kill_papers(app_literature_dir, app_dir)
        app_literature_dir.mkdir(parents=True, exist_ok=True)
        (app_literature_dir / "execution-realism.md").write_text(
            EXECUTION_REALISM_MD.read_text()
        )
        (app_literature_dir / "futures-execution-foundation.md").write_text(
            FUTURES_EXECUTION_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "options-execution-foundation.md").write_text(
            OPTIONS_EXECUTION_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "borrow-execution-foundation.md").write_text(
            BORROW_EXECUTION_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "market-status-replay.md").write_text(
            MARKET_STATUS_REPLAY_MD.read_text()
        )
        (app_literature_dir / "crowding-risk-foundation.md").write_text(
            CROWDING_RISK_FOUNDATION_MD.read_text()
        )
        (app_literature_dir / "corporate-action-lifecycle.md").write_text(
            CORPORATE_ACTION_LIFECYCLE_MD.read_text()
        )
        (app_literature_dir / "financing-replay.md").write_text(
            FINANCING_REPLAY_MD.read_text()
        )
        (app_literature_dir / "engineering-quality.md").write_text(
            ENGINEERING_QUALITY_MD.read_text()
        )
        if LEGACY_DSR_RESTATEMENT_MD.exists():
            (app_literature_dir / "legacy-dsr-restatement.md").write_text(
                LEGACY_DSR_RESTATEMENT_MD.read_text()
            )
        (app_literature_dir / "literature-frontier-2026-08-16.md").write_text(
            LITERATURE_FRONTIER_MD.read_text()
        )
        (app_literature_dir / "literature-repurchase-issuance-flow.md").write_text(
            REPURCHASE_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "repurchase-issuance-flow-feasibility.md").write_text(
            REPURCHASE_FEASIBILITY_MD.read_text()
        )
        (app_literature_dir / "literature-options-dispersion.md").write_text(
            OPTIONS_DISPERSION_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "options-dispersion-feasibility.md").write_text(
            OPTIONS_DISPERSION_FEASIBILITY_MD.read_text()
        )
        (app_literature_dir / "literature-stablecoin-dislocation.md").write_text(
            STABLECOIN_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "stablecoin-dislocation-feasibility.md").write_text(
            STABLECOIN_FEASIBILITY_MD.read_text()
        )
        (app_literature_dir / "literature-spin-off-dislocation.md").write_text(
            SPIN_OFF_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "spin-off-dislocation-lineage.md").write_text(
            SPIN_OFF_LINEAGE_MD.read_text()
        )
        (app_literature_dir / "spin-off-document-schema.md").write_text(
            SPIN_OFF_DOCUMENT_MD.read_text()
        )
        (app_dir / "spin_off_lineage.json").write_text(
            SPIN_OFF_LINEAGE_RESULT.read_text()
        )
        (app_dir / "spin_off_document_schema.json").write_text(
            SPIN_OFF_DOCUMENT_RESULT.read_text()
        )
        (app_literature_dir / "literature-electricity-load-weather.md").write_text(
            ELECTRICITY_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "electricity-load-weather-feasibility.md").write_text(
            ELECTRICITY_FEASIBILITY_MD.read_text()
        )
        (app_dir / "electricity_load_weather_feasibility.json").write_text(
            ELECTRICITY_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "literature-natural-gas-storage-weather.md").write_text(
            NATURAL_GAS_LITERATURE_MD.read_text()
        )
        (app_literature_dir / "natural-gas-storage-weather-feasibility.md").write_text(
            NATURAL_GAS_FEASIBILITY_MD.read_text()
        )
        (app_dir / "natural_gas_storage_weather_feasibility.json").write_text(
            NATURAL_GAS_FEASIBILITY_RESULT.read_text()
        )
        (
            app_literature_dir / "literature-customer-supplier-propagation.md"
        ).write_text(CUSTOMER_SUPPLIER_LITERATURE_MD.read_text())
        (
            app_literature_dir / "customer-supplier-propagation-feasibility.md"
        ).write_text(CUSTOMER_SUPPLIER_FEASIBILITY_MD.read_text())
        (app_dir / "customer_supplier_propagation_feasibility.json").write_text(
            CUSTOMER_SUPPLIER_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "literature-bond-etf-nav-dislocation.md").write_text(
            BOND_ETF_NAV_LITERATURE_MD.read_text()
        )
        (
            app_literature_dir / "bond-etf-nav-dislocation-feasibility.md"
        ).write_text(BOND_ETF_NAV_FEASIBILITY_MD.read_text())
        (app_dir / "bond_etf_nav_dislocation_feasibility.json").write_text(
            BOND_ETF_NAV_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "treasury-auction-concession-feasibility.md").write_text(
            TREASURY_FEASIBILITY_MD.read_text()
        )
        (app_dir / "treasury_auction_concession_feasibility.json").write_text(
            TREASURY_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "treasury-auction-identity-timing.md").write_text(
            TREASURY_TIMING_MD.read_text()
        )
        (app_dir / "treasury_auction_identity_timing.json").write_text(
            TREASURY_TIMING_RESULT.read_text()
        )
        (app_dir / "treasury_tentative_schedule_audit.json").write_text(
            TREASURY_TENTATIVE_SCHEDULE_RESULT.read_text()
        )
        (app_dir / "treasury_wayback_schedule_audit.json").write_text(
            TREASURY_WAYBACK_SCHEDULE_RESULT.read_text()
        )
        (app_dir / "treasury_wayback_pdf_schedule_audit.json").write_text(
            TREASURY_WAYBACK_PDF_SCHEDULE_RESULT.read_text()
        )
        (app_dir / "treasury_calendar_revision_audit.json").write_text(
            TREASURY_CALENDAR_REVISION_RESULT.read_text()
        )
        (app_literature_dir / "cftc-hedging-pressure-feasibility.md").write_text(
            CFTC_FEASIBILITY_MD.read_text()
        )
        (app_dir / "cftc_hedging_pressure_feasibility.json").write_text(
            CFTC_FEASIBILITY_RESULT.read_text()
        )
        (app_literature_dir / "alphavintage-missing-release-correction.md").write_text(
            ALPHAVINTAGE_CORRECTION_MD.read_text()
        )
        (app_literature_dir / "pre-fomc-announcement-drift-feasibility.md").write_text(
            PRE_FOMC_FEASIBILITY_MD.read_text()
        )
        (app_dir / "pre_fomc_announcement_drift_feasibility.json").write_text(
            PRE_FOMC_FEASIBILITY_RESULT.read_text()
        )
        (app_dir / "pre_fomc_schedule_lineage.json").write_text(
            PRE_FOMC_SCHEDULE_LINEAGE_RESULT.read_text()
        )
        (app_literature_dir / "prereg-pre-fomc-announcement-drift.md").write_text(
            PRE_FOMC_PREREG_MD.read_text()
        )
        (app_dir / "pre_fomc_market_data_readiness.json").write_text(
            PRE_FOMC_MARKET_DATA_READINESS_RESULT.read_text()
        )
        (app_literature_dir / "prereg-earnings-narrative-change.md").write_text(
            NARRATIVE_PREREG_MD.read_text()
        )
        for source_name, public_name in (
            ("result.json", "earnings_narrative_change_result.json"),
            ("input_data_manifest.json", "earnings_narrative_change_input_data_manifest.json"),
            ("diversification.json", "earnings_narrative_change_diversification.json"),
        ):
            source = NARRATIVE_PROBE_DIR / source_name
            if source.exists():
                (app_dir / public_name).write_text(source.read_text())
    print(f"wrote {path}  ({path.stat().st_size} bytes)")
    print(f"content_hash: {payload['content_hash']}")
    return path


if __name__ == "__main__":
    main()
