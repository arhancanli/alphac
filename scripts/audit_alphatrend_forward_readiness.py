"""Read-only local readiness and sleeve-evidence audit; no broker or return computation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/alphatrend-forward-readiness-20260912"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    bindings = {}

    def freeze(path):
        data = path.read_bytes()
        scope = "worktree" if path.is_relative_to(ROOT) else "production_local"
        rel = path.relative_to(ROOT if scope == "worktree" else PRODUCTION)
        dest = OUT / "sources" / scope / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        bindings[f"{scope}/{rel}"] = {
            "sha256": sha(data),
            "bytes": len(data),
            "snapshot": str(dest.relative_to(OUT)),
        }
        return data

    files = [
        "ALPHAC_BREADTH_PHASE.md",
        "CURRENT_RESTART_STATUS.md",
        "RUNNER_AND_ALPHABET_PROGRESS.md",
        "DATA_SOURCE_AND_EQUITY_SEARCH.md",
        "BREADTH_SOURCE_REVIEW.md",
        "WASDE_TIMING_AND_LIFECYCLE.md",
        "SHARE_CLASS_QUOTE_RESULTS.md",
        "config/sleeve_family_lineage.json",
        "config/forward_evidence_contract.json",
        "config/sleeve_admission_contract.json",
        "config/sleeve_discovery.json",
        "evidence/existing-sleeve-audit-20260911/audit.json",
        "evidence/spot-dedicated-account-verification.json",
        "evidence/alphabet-prospective-quotes-20260911-sip/receipt.json",
        "evidence/alphabet-prospective-quotes-20260911-iex/receipt.json",
        "scripts/mf_gauntlet.py",
        "src/alphaforge/signals/service.py",
        "deploy/systemd/alphaforge-alphatrend.service",
        "deploy/systemd/alphaforge-alphatrend.timer",
        "artifacts/analysis/alphatrend_directional_validation_20260912/validation_closure.json",
        "artifacts/analysis/alphatrend_directional_validation_20260912/REPORT.md",
        "artifacts/analysis/alphatrend_directional_20260912_attempt2/reservation.json",
    ]
    for rel in files:
        freeze(ROOT / rel)
    legacy = json.loads((ROOT / "evidence/existing-sleeve-audit-20260911/audit.json").read_text())
    for record in legacy["source_bindings"].values():
        p = ROOT / "evidence/existing-sleeve-audit-20260911" / record["snapshot"]
        assert sha(p.read_bytes()) == record["sha256"]
    for record in json.loads((ROOT / files[-3]).read_text())["files"]:
        assert sha((ROOT / record["path"]).read_bytes()) == record["sha256"]
    live_sources = {}
    for rel in [
        "scripts/mf_tick.sh",
        "scripts/live_cycle.py",
        "src/alphaforge/signals/service.py",
        "artifacts/walkforward/mf_live_fwd/walkforward.json",
    ]:
        data = freeze(PRODUCTION / rel)
        live_sources[rel] = data
    wf = json.loads(live_sources["artifacts/walkforward/mf_live_fwd/walkforward.json"])
    data_coverage = []
    for directory in sorted((PRODUCTION / "data/lake_mf/ohlcv_1d").glob("instrument_id=*")):
        paths = sorted(directory.glob("year=2026/*.parquet"))
        if not paths:
            continue
        last = None
        for path in paths:
            frame = pd.read_parquet(path, columns=["ts_open"])
            timestamp = frame.ts_open.max()
            last = timestamp if last is None else max(last, timestamp)
            # Frozen one-column extraction and original file hash; no price outcomes inspected.
            dest = OUT / "coverage" / directory.name / path.parent.name / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(dest, index=False)
            bindings[str(path.relative_to(PRODUCTION))] = {
                "source_sha256": sha(path.read_bytes()),
                "extraction": str(dest.relative_to(OUT)),
                "extraction_sha256": sha(dest.read_bytes()),
            }
        data_coverage.append(
            {"instrument_id": directory.name.split("=", 1)[1], "latest_bar_open": str(last)}
        )
    lineage = json.loads((ROOT / "config/sleeve_family_lineage.json").read_text())
    sleeves = [
        {
            "name": "AlphaTrend directional candidate",
            "mechanism": "multi-asset time-series momentum",
            "status": "RETAINED_DEVELOPMENT_NOT_ADMITTED",
            "evidence": "Passed baseline comparison and one doubled-cost scenario; era instability remains",  # noqa: E501
            "overlap": "Trend and directional market exposure; new-candidate cross-sleeve overlap unmeasured",  # noqa: E501
            "next": "Separate immutable observation epoch and causal as-of runtime parity",
        },
        {
            "name": "AlphaMax",
            "mechanism": "US equity cross-sectional momentum",
            "status": "LEGACY_REPLAY_PROVENANCE_LIMITATION",
            "evidence": "Prior author replay does not exactly reproduce preserved research curve",
            "overlap": "Potential momentum and equity exposure overlap with AlphaTrend",
            "next": "Freeze comparable identity/curve provenance before a new synchronized overlap study",  # noqa: E501
        },
        {
            "name": "AlphaVintage",
            "mechanism": "PIT CPI-surprise equity size spread",
            "status": "LEGACY_MARGINAL_CONTRIBUTION_REVIEW_REQUIRED",
            "evidence": "Archived common-window comparison suggests possible diversification; not current validation",  # noqa: E501
            "overlap": "Distinct macro-event input, shared equity execution; candidate-specific overlap unknown",  # noqa: E501
            "next": "Reconcile exact curve identity and synchronized dates; measure contribution without filling gaps",  # noqa: E501
        },
        {
            "name": "AlphaForge disputed carry",
            "mechanism": "crypto funding carry",
            "status": "QUARANTINED_FROM_COMPARISONS",
            "evidence": "Preserved disputed history and correction do not establish a replacement track record",  # noqa: E501
            "overlap": "Excluded from usable correlation and portfolio performance claims",
            "next": "Keep legacy record separate; do not splice restart returns",
        },
        {
            "name": "AlphaForge spot restart",
            "mechanism": "BTC/ETH trend, long or cash",
            "status": "SEPARATE_RESTART_NOT_ACTIVATED_BY_THIS_WORK",
            "evidence": "Prior dedicated-account verification exists; current account/clock/runtime not re-probed",  # noqa: E501
            "overlap": "Crypto trend is not automatically independent of multi-asset trend",
            "next": "Resolve documented timing/runtime gates; new dated paper epoch only after readiness",  # noqa: E501
        },
    ]
    gates = [
        {
            "gate": "Candidate definition and development evidence",
            "status": "AVAILABLE",
            "detail": "ec7ec19175ac10a9 frozen; 2x-cost validation passed, still not admission",
        },
        {
            "gate": "Candidate installed in local production signal path",
            "status": "FAIL",
            "detail": "Production SignalService lacks directional_rms; saved WF config has no candidate normalization",  # noqa: E501
        },
        {
            "gate": "Fresh complete daily inputs for observation",
            "status": "UNESTABLISHED",
            "detail": "All 17 local 2026 ETF partitions end September 10; new received-time input captures absent from audited candidate evidence",  # noqa: E501
        },
        {
            "gate": "Targets tied to a pre-outcome decision",
            "status": "FAIL_FOR_CURRENT_PATH",
            "detail": "mf_tick refreshes Yahoo history and reruns WF; live_cycle selects latest saved position weights, not a sealed candidate decision packet",  # noqa: E501
        },
        {
            "gate": "As-of signal and allocation runtime parity",
            "status": "UNESTABLISHED",
            "detail": "Historical reconstruction passed; equity prospective decision-calendar, causal blend-weight updates and persistent risk/cadence parity are not established",  # noqa: E501
        },
        {
            "gate": "Independent execution benchmarks and dated borrow",
            "status": "INCOMPLETE",
            "detail": "live_cycle records padded order price as decision_price and uses shortability flags; no verified candidate-wide arrival/fee/borrow record",  # noqa: E501
        },
        {
            "gate": "New identity-bound append-only observation epoch",
            "status": "NOT_EVIDENCED",
            "detail": "No candidate deployment/epoch receipt in the audited source set; historical reruns cannot backfill this record",  # noqa: E501
        },
        {
            "gate": "Current account, clock, licensed feed and remote scheduler verification",
            "status": "NOT_RECHECKED",
            "detail": "Local source/credential presence only. Earlier SIP/clock failures are dated evidence, not fresh status",  # noqa: E501
        },
    ]
    result = {
        "schema": "alphac.forward-readiness-and-sleeve-map.v1",
        "audited_at": datetime.now(UTC).isoformat(),
        "scope": "Read-only local source and saved-artifact audit; no broker/network/remote service probe",  # noqa: E501
        "decision": "CANDIDATE_FORWARD_OBSERVATION_NOT_READY",
        "goals": {
            "owner_portfolio_sharpe_target": 2,
            "owner_independent_sleeves_target": 14,
            "canonical_forward_target_unchanged": 1.5,
        },
        "new_return_trials": 0,
        "selection_union_unchanged": 234,
        "new_sleeves_admitted": 0,
        "current_qualified_sleeve_count": None,
        "credential_file_presence_only": {
            name: (Path.home() / ".config/alphaforge" / name).is_file()
            for name in ["alpaca.env", "alpaca_equity.env", "alpaca_spot.env"]
        },
        "local_saved_walkforward_end": str(
            pd.to_datetime(wf["config"]["end"], unit="ms", utc=True)
        ),
        "local_saved_normalization": wf["config"].get("trend_blend_normalization"),
        "local_candidate_implementation_present": b"directional_rms"
        in live_sources["src/alphaforge/signals/service.py"],
        "gates": gates,
        "data_coverage": data_coverage,
        "sleeves": sleeves,
        "lineage_registry_as_of": lineage["as_of"],
        "lineage_family_counts": dict(
            Counter(row["classification"] for row in lineage["families"].values())
        ),
        "lineage_families": lineage["families"],
        "historical_overlap_only": legacy["historical_common_window"],
        "candidate_overlap_status": "NOT_MEASURED_WITH_CURRENT_CANDIDATE",
        "source_bindings": bindings,
    }
    (OUT / "audit.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = [
        "# AlphaTrend forward readiness and sleeve map",
        "",
        "**The retained candidate is not ready for forward execution.** We can build its "
        "isolated observation recorder now; the audited runner does not yet produce the "
        "identity-bound prospective evidence needed to activate it.",
        "",
        "This is a September 12 local source/artifact audit, not a fresh broker or remote-host "
        "check. Nothing was deployed, no orders or API requests were sent, and no return "
        "trial or portfolio reweighting was performed. The experiment union stays at 234.",
        "",
        "## Readiness findings",
        "",
        "| Gate | Status | Evidence / gap |",
        "| --- | --- | --- |",
    ]
    for row in gates:
        lines.append(f"| {row['gate']} | {row['status']} | {row['detail']} |")
    lines += [
        "",
        "The local saved walk-forward end is **August 25, 2026**, while all 17 local ETF data "
        "partitions reach **September 10**. These different cutoffs show that refreshed data "
        "do not prove refreshed targets. Remote Frankfurt runtime state was not queried.",
        "",
        "Credential files for general, equity and dedicated spot contexts exist. No keys were "
        "read or copied. Later restart notes and the preserved dedicated-account verification "
        "supersede older missing-credential notes. This audit does not ask for replacement keys "
        "or infer present account readiness from file existence.",
        "",
        "## Sleeve evidence and mechanism map",
        "",
        "| Sleeve / candidate | Status | Overlap implication | Next evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in sleeves:
        lines.append(f"| {row['name']} | {row['status']} | {row['overlap']} | {row['next']} |")
    lines += [
        "",
        "The August 16 lineage registry lists 40 research families: "
        + ", ".join(
            f"{count} {status}" for status, count in result["lineage_family_counts"].items()
        )
        + ". "
        "These are novelty/queue labels, not admission findings. Four legacy book names and a "
        "separate restart do not establish five qualified independent sleeves.",
        "",
        "## What the old overlap numbers can tell us",
        "",
        "| Pair | Archived joint-activity correlation |",
        "| --- | ---: |",
    ]
    for pair, value in legacy["historical_common_window"][
        "pairwise_joint_activity_correlations"
    ].items():
        lines.append(f"| {pair.replace('|', ' / ')} | {value:.3f} |")
    lines += [
        "",
        "These are preserved values from the old 1,061-calendar-day research window ending "
        "June 1, 2026. They use the old AlphaTrend construction and source alignment, not the "
        "new directional candidate. They cannot certify its diversification. AlphaForge legacy "
        "returns are excluded here; no corrected current portfolio Sharpe or qualified sleeve "
        "count can be established from this audit.",
        "",
        "## Work sequence",
        "",
        "1. Build an isolated, append-only AlphaTrend observation recorder. Bind the candidate "
        "code/config, point-in-time inputs, received timestamps, decision deadline, exchange "
        "calendar and causal weight state before computing and committing each signal. "
        "Capture missed/invalid observations explicitly; never reconstruct a past decision.",
        "2. Verify research/as-of signal parity and persistent allocation/risk/cadence behavior "
        "on an equity session calendar. Compare a controlled replay with the frozen baseline; "
        "do not switch existing broker targets to the new candidate.",
        "3. Collect bounded read-only feed, clock, asset/borrow and account evidence for the "
        "chosen observation context. Use existing credentials. Require an independent "
        "decision/arrival benchmark and clear feed scope; dated Alphabet diagnostics do not "
        "substitute for a current 17-ETF observation check.",
        "4. Freeze compatible AlphaMax and AlphaVintage identities and synchronized return "
        "observations before a portfolio-overlap study. Distinguish absent observations from "
        "known flat exposure. Do not include disputed AlphaForge history or splice restarts.",
        "5. Resume data-feasibility work on complementary mechanisms. WASDE has original-"
        "release timing/lifecycle gaps; Alphabet has quote/borrow/clock gates; FDA/convertible "
        "leads still need historical mapping and execution evidence. Prefer closing a specific "
        "gap with existing data over buying more data or launching another return sweep.",
        "",
        "The next concrete implementation is the observation recorder and its parity tests. "
        "It should begin a new prospective epoch only when the required inputs can be captured "
        "before their outcomes. A local recorder alone does not provide independent public "
        "timestamp proof, mature paper performance or admission.",
        "",
        "Owner targets remain Sharpe near 2 and 14+ independently useful sleeves. Existing "
        "canonical 1.5 forward criteria and 252/756 calendar-mark maturity rules remain "
        "unchanged; they must not be silently applied as 252-session AlphaTrend research rules.",
        "",
        "[Machine-readable audit and full family inventory](audit.json). Source snapshots and "
        "hashes are included; no secret files are part of this evidence packet.",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines))
    (OUT / "closure.json").write_text(
        json.dumps(
            {
                "files": [
                    {"path": str(p.relative_to(ROOT)), "sha256": sha(p.read_bytes())}
                    for p in [Path(__file__), OUT / "audit.json", OUT / "REPORT.md"]
                ]
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "decision",
                    "local_saved_walkforward_end",
                    "local_candidate_implementation_present",
                    "lineage_family_counts",
                    "new_return_trials",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
