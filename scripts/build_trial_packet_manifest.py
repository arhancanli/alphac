#!/usr/bin/env python3
"""Inventory one permanent evidence packet for every union hypothesis identity.

This does not manufacture papers from sparse ledger rows. It creates the auditable join that was
missing: every deduplicated return identity, its first immutable measurement, and any public paper
that appears to name that identity. Candidate matches remain explicitly unverified until a human
or a stronger packet validator confirms every required section.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any, Final

from alphaforge.validation.experiments import ExperimentLog, ExperimentUnion

REPO: Final[Path] = Path(__file__).resolve().parent.parent
ACTIVE_LEDGER: Final[Path] = REPO / "var" / "experiments.jsonl"
ARTIFACT: Final[Path] = REPO / "artifacts" / "research" / "trial_packet_manifest.json"
LEGACY_EPOCH_CLOSURE: Final[Path] = (
    REPO / "artifacts" / "research" / "legacy_research_epoch_closure.json"
)
IDENTITY_PACKET_DIR: Final[Path] = REPO / "artifacts" / "research" / "trial_packets"
HOST_RESEARCH_DIRS: Final[tuple[Path, Path]] = (
    REPO.parent / "meridian" / "public" / "research",
    REPO.parent / "meridian-app" / "public" / "research",
)
HOST_OUTPUTS: Final[tuple[Path, Path]] = (
    HOST_RESEARCH_DIRS[0].parent / "glassbox" / "trial_packet_manifest.json",
    HOST_RESEARCH_DIRS[1].parent / "glassbox" / "trial_packet_manifest.json",
)
SOURCE_PAPERS: Final[dict[str, Path]] = {
    "alphamax-equity-momentum-lineage.md": (
        REPO / "docs" / "research" / "ALPHAMAX_EQUITY_MOMENTUM_LINEAGE.md"
    ),
    "crypto-carry-lineage.md": REPO / "docs" / "research" / "CRYPTO_CARRY_LINEAGE.md",
    "crypto-momentum-lineage.md": REPO / "docs" / "research" / "CRYPTO_MOMENTUM_LINEAGE.md",
    "alphatrend-managed-futures-lineage.md": (
        REPO / "docs" / "research" / "ALPHATREND_MANAGED_FUTURES_LINEAGE.md"
    ),
    "crypto-vrp-lineage.md": REPO / "docs" / "research" / "CRYPTO_VRP_LINEAGE.md",
    "crypto-multifactor-engine-lineage.md": (
        REPO / "docs" / "research" / "CRYPTO_MULTIFACTOR_ENGINE_LINEAGE.md"
    ),
    "equity-narrative-change-lineage.md": (
        REPO / "docs" / "research" / "EQUITY_NARRATIVE_CHANGE_LINEAGE.md"
    ),
    "equity-quality-lineage.md": REPO / "docs" / "research" / "EQUITY_QUALITY_LINEAGE.md",
    "equity-value-investment-lineage.md": (
        REPO / "docs" / "research" / "EQUITY_VALUE_INVESTMENT_LINEAGE.md"
    ),
    "crypto-defensive-lineage.md": REPO / "docs" / "research" / "CRYPTO_DEFENSIVE_LINEAGE.md",
    "crypto-reversal-lineage.md": REPO / "docs" / "research" / "CRYPTO_REVERSAL_LINEAGE.md",
    "energy-inventory-lineage.md": REPO / "docs" / "research" / "ENERGY_INVENTORY_LINEAGE.md",
    "equity-insider-activity-lineage.md": REPO
    / "docs"
    / "research"
    / "EQUITY_INSIDER_ACTIVITY_LINEAGE.md",
    "equity-low-beta-lineage.md": REPO / "docs" / "research" / "EQUITY_LOW_BETA_LINEAGE.md",
    "macro-economic-trend-lineage.md": REPO
    / "docs"
    / "research"
    / "MACRO_ECONOMIC_TREND_LINEAGE.md",
}
FAMILY_PAPER_BINDINGS: Final[dict[str, dict[str, Any]]] = {
    "alphamax_equity_momentum": {
        "public_path": "/research/alphamax-equity-momentum-lineage.md",
        # Shared family sections can be credited through the deterministic taxonomy. Exact
        # preregistration, results, and reproduction remain identity-level packet debt.
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "crypto_carry": {
        "public_path": "/research/crypto-carry-lineage.md",
        # The paper proves the shared family context only. Exact preregistration, results,
        # environments, and reproduction remain identity-level packet debt and stay fail-closed.
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "crypto_momentum": {
        "public_path": "/research/crypto-momentum-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "managed_futures_trend": {
        "public_path": "/research/alphatrend-managed-futures-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "crypto_volatility_risk_premium": {
        "public_path": "/research/crypto-vrp-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "crypto_multifactor_engine": {
        "public_path": "/research/crypto-multifactor-engine-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "equity_narrative_change": {
        "public_path": "/research/equity-narrative-change-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "equity_fundamental_quality": {
        "public_path": "/research/equity-quality-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
    "equity_fundamental_value_investment": {
        "public_path": "/research/equity-value-investment-lineage.md",
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    },
}

for _family_key_name, _public_path in {
    "crypto_defensive": "/research/crypto-defensive-lineage.md",
    "crypto_short_horizon_reversal": "/research/crypto-reversal-lineage.md",
    "energy_inventory": "/research/energy-inventory-lineage.md",
    "equity_insider_activity": "/research/equity-insider-activity-lineage.md",
    "equity_low_beta": "/research/equity-low-beta-lineage.md",
    "macro_economic_trend": "/research/macro-economic-trend-lineage.md",
}.items():
    FAMILY_PAPER_BINDINGS[_family_key_name] = {
        "public_path": _public_path,
        "verified_shared_sections": (
            "identity_and_authorship",
            "economic_mechanism_and_falsifiable_hypothesis",
            "literature_and_overlap_decision",
            "family_and_union_trial_accounting",
            "machine_readable_packet_and_stable_public_paper",
        ),
    }

REQUIRED_PACKET_SECTIONS: Final[tuple[str, ...]] = (
    "identity_and_authorship",
    "economic_mechanism_and_falsifiable_hypothesis",
    "literature_and_overlap_decision",
    "preregistration_and_hashes",
    "point_in_time_data_and_survivorship_controls",
    "execution_and_cost_model",
    "family_and_union_trial_accounting",
    "result_uncertainty_stress_capacity_and_diversification",
    "admission_or_kill_decision",
    "code_environment_and_reproduction",
    "machine_readable_packet_and_stable_public_paper",
)

RESEARCH_FAMILIES: Final[dict[str, dict[str, str]]] = {
    "alphamax_equity_momentum": {
        "title": "AlphaMax equity momentum and construction",
        "sleeve": "AlphaMax",
    },
    "equity_fundamental_quality": {
        "title": "Equity fundamental quality",
        "sleeve": "AlphaMax research",
    },
    "equity_fundamental_value_investment": {
        "title": "Equity value, issuance, and investment",
        "sleeve": "AlphaMax research",
    },
    "equity_low_beta": {
        "title": "Equity low-beta and defensive factors",
        "sleeve": "AlphaMax research",
    },
    "equity_insider_activity": {
        "title": "Equity insider activity",
        "sleeve": "AlphaMax research",
    },
    "equity_narrative_change": {
        "title": "Equity filing and narrative change",
        "sleeve": "AlphaMax research",
    },
    "managed_futures_trend": {
        "title": "Managed-futures trend",
        "sleeve": "Managed Futures",
    },
    "crypto_carry": {
        "title": "Crypto perpetual-futures carry",
        "sleeve": "AlphaForge",
    },
    "crypto_momentum": {
        "title": "Crypto time-series and cross-sectional momentum",
        "sleeve": "AlphaForge research",
    },
    "crypto_multifactor_engine": {
        "title": "Crypto multi-factor allocator, regime, and ML engine",
        "sleeve": "AlphaForge research",
    },
    "crypto_short_horizon_reversal": {
        "title": "Crypto short-horizon residual reversal",
        "sleeve": "AlphaVintage research",
    },
    "crypto_defensive": {
        "title": "Crypto low-volatility and low-beta factors",
        "sleeve": "AlphaVintage research",
    },
    "crypto_volatility_risk_premium": {
        "title": "Crypto volatility risk-premium proxy",
        "sleeve": "AlphaForge research",
    },
    "macro_economic_trend": {
        "title": "Point-in-time macroeconomic trend",
        "sleeve": "Diversifier research",
    },
    "energy_inventory": {
        "title": "Energy inventory scarcity",
        "sleeve": "Diversifier research",
    },
}


def _family_key(config: dict[str, Any]) -> str:
    """Assign every charged hypothesis to one stable economic research family.

    The taxonomy groups evidence and papers; it never changes the hypothesis hash or the honest
    multiple-testing denominator. Unknown identities fail closed instead of quietly landing in an
    unreviewed catch-all family.
    """
    probe = config.get("probe")
    if probe in {
        "forensic_alphamax_construction",
        "forensic_alphamax_weighting",
        "alphamax_volscale",
        "alphamax_hyst_live",
        "alphamax_turnover",
    }:
        return "alphamax_equity_momentum"
    if probe in {"alphatrend_arp", "alphatrend_breadth"}:
        return "managed_futures_trend"
    if probe == "crypto_vrp_proxy":
        return "crypto_volatility_risk_premium"
    if probe in {"macro_vintage_family", "econtrend", "cpi_surprise_size"}:
        return "macro_economic_trend"
    if probe == "eia_petroleum_inventory":
        return "energy_inventory"
    if probe == "earnings_narrative_change":
        return "equity_narrative_change"
    if probe == "insider_purchase_clusters":
        return "equity_insider_activity"

    raw_alphas = config.get("alpha_names")
    alphas = {str(alpha) for alpha in raw_alphas} if isinstance(raw_alphas, list) else set()
    if raw_alphas is None and config.get("train_bars") == 8760 and config.get("test_bars") == 2184:
        return "crypto_multifactor_engine"
    if any(alpha.startswith("mf_trend_") for alpha in alphas):
        return "managed_futures_trend"
    if any(alpha.startswith("carry_") for alpha in alphas):
        return "crypto_carry"
    if any(alpha.startswith(("mom_ts_", "mom_xs_")) for alpha in alphas):
        return "crypto_momentum"
    if any(alpha.startswith("mr_res_") for alpha in alphas):
        return "crypto_short_horizon_reversal"
    if alphas & {"lowvol_720", "beta_lowbeta_720"}:
        return "crypto_defensive"
    if any(alpha.startswith("eq_mom_") for alpha in alphas) or "eq_rev_resid_21" in alphas:
        return "alphamax_equity_momentum"
    if "eq_bab_252" in alphas:
        return "equity_low_beta"
    if alphas & {
        "eq_operating_margin",
        "eq_gross_profitability",
        "eq_quality_composite",
        "eq_roe",
        "eq_qual_gpe",
    }:
        return "equity_fundamental_quality"
    if alphas & {
        "eq_accruals",
        "eq_asset_growth",
        "eq_book_to_price",
        "eq_earnings_yield",
        "eq_ilrev",
        "eq_net_issuance",
        "eq_sales_to_price",
        "eq_value_composite",
        "eq_52whigh_252",
    }:
        return "equity_fundamental_value_investment"
    raise ValueError(f"unclassified trial identity: {_label(config)}")


def _label(config: dict[str, Any]) -> str:
    probe = config.get("probe")
    if isinstance(probe, str) and probe:
        variant = config.get("variant")
        return f"{probe} / {variant}" if isinstance(variant, str) and variant else probe
    alphas = config.get("alpha_names")
    if isinstance(alphas, list) and alphas:
        return " + ".join(str(alpha) for alpha in alphas)
    if alphas is None and config.get("train_bars") == 8760 and config.get("test_bars") == 2184:
        if config.get("ml") and config.get("regime"):
            return "crypto multi-factor / ML + regime"
        if config.get("ml"):
            return "crypto multi-factor / ML gate"
        if config.get("regime"):
            return "crypto multi-factor / regime gate"
        if config.get("allocator") == "mvo":
            return "crypto multi-factor / MVO allocator"
        if config.get("rebalance_bars") == 24:
            return "crypto multi-factor / daily rebalance"
        if config.get("no_trade_band") == 0.001:
            return "crypto multi-factor / 10 bp no-trade band"
        return "crypto multi-factor / baseline"
    for key in ("mechanism", "overlay", "variant"):
        value = config.get(key)
        if isinstance(value, str) and value:
            return value
    return "unlabelled_identity"


def _identity_terms(config: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("probe", "mechanism", "overlay", "variant"):
        value = config.get(key)
        if isinstance(value, str) and len(value) >= 4:
            values.append(value)
    alphas = config.get("alpha_names")
    if isinstance(alphas, list):
        values.extend(str(value) for value in alphas if len(str(value)) >= 4)
    return {value.lower() for value in values}


def _paper_corpus() -> dict[str, str]:
    """Load the public corpus only when both hosts publish identical bytes."""
    corpora: list[dict[str, bytes]] = []
    for directory in HOST_RESEARCH_DIRS:
        if not directory.exists():
            raise FileNotFoundError(f"public research corpus missing: {directory}")
        corpora.append({path.name: path.read_bytes() for path in sorted(directory.glob("*.md"))})
    if corpora[0] != corpora[1]:
        left = set(corpora[0])
        right = set(corpora[1])
        raise ValueError(
            "public paper corpora differ across hosts; refusing to measure ambiguous coverage: "
            f"legacy_only={sorted(left - right)}, app_only={sorted(right - left)}"
        )
    corpus = {name: payload.decode("utf-8") for name, payload in corpora[0].items()}

    # Canonical source papers are rendered later in the same publication pipeline. Overlay their
    # current bytes so packet coverage does not lag one release behind merely because the public
    # directories still contain the previous release at inventory time.
    for public_name, source_path in SOURCE_PAPERS.items():
        if not source_path.exists():
            raise FileNotFoundError(f"canonical research paper missing: {source_path}")
        corpus[public_name] = source_path.read_text(encoding="utf-8")

    # Kill papers are generated from the current kill ledger later in the same publication run.
    # Render them in memory here so a newly killed identity is not invisible for one cycle merely
    # because the previous public directory has not been overwritten yet.
    kill_logs = tuple(path.parent / "glassbox" / "kill_log.json" for path in HOST_RESEARCH_DIRS)
    if not all(path.exists() for path in kill_logs):
        raise FileNotFoundError("kill_log.json must exist on both hosts before packet inventory")
    if kill_logs[0].read_bytes() != kill_logs[1].read_bytes():
        raise ValueError("kill ledgers differ across hosts; refusing to inventory papers")
    spec = importlib.util.spec_from_file_location(
        "build_kill_papers_for_packet_manifest", REPO / "scripts" / "build_kill_papers.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("cannot load scripts/build_kill_papers.py")
    kill_papers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kill_papers)
    corpus.update(kill_papers.render_kill_papers(json.loads(kill_logs[0].read_text())))
    return corpus


def _candidate_papers(config: dict[str, Any], corpus: dict[str, str]) -> list[str]:
    terms = _identity_terms(config)
    if not terms:
        return []
    candidates = []
    for name, markdown in corpus.items():
        haystack = f"{name}\n{markdown}".lower()
        normalized = re.sub(r"[^a-z0-9]+", "_", haystack)
        if any(
            term in haystack or re.sub(r"[^a-z0-9]+", "_", term) in normalized for term in terms
        ):
            candidates.append(f"/research/{name}")
    return candidates


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _identity_packet(key: str, config_hash: str, family_key: str) -> dict[str, Any]:
    path = IDENTITY_PACKET_DIR / f"{key}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"identity packet missing for {key}; run scripts/build_identity_trial_packets.py first"
        )
    packet: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if packet.get("hypothesis_key") != key:
        raise ValueError(f"{key}: packet hypothesis key mismatch")
    if packet.get("config_hash") != config_hash:
        raise ValueError(f"{key}: packet config hash mismatch")
    if packet.get("research_family_key") != family_key:
        raise ValueError(f"{key}: packet family mismatch")
    claimed = packet.pop("content_hash", None)
    canonical = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    observed = "sha256:" + hashlib.sha256(canonical).hexdigest()
    packet["content_hash"] = claimed
    if claimed != observed:
        raise ValueError(f"{key}: packet content hash mismatch")
    return packet


def _sealed_legacy_manifest() -> dict[str, Any] | None:
    """Return the immutable legacy manifest after its epoch has been sealed.

    A prospective identity appended after the closure must never be folded into the retired
    228-identity manifest. The forward epoch publishes separate packets. Any drift in either the
    closure or its bound manifest fails closed instead of regenerating history in place.
    """
    if not LEGACY_EPOCH_CLOSURE.exists():
        return None
    closure: dict[str, Any] = json.loads(LEGACY_EPOCH_CLOSURE.read_text(encoding="utf-8"))
    closure_hash = closure.pop("content_hash", None)
    closure_canonical = json.dumps(closure, sort_keys=True, separators=(",", ":")).encode()
    closure["content_hash"] = closure_hash
    if closure_hash != "sha256:" + hashlib.sha256(closure_canonical).hexdigest():
        raise ValueError("legacy research epoch closure content hash mismatch")
    if closure.get("status") != "LEGACY_EPOCH_RETIRED_FAIL_CLOSED":
        raise ValueError("legacy research epoch closure is not retired fail closed")
    binding = closure.get("source_bindings", {}).get("trial_packet_manifest", {})
    if binding.get("path") != str(ARTIFACT.relative_to(REPO)) or not ARTIFACT.is_file():
        raise ValueError("sealed legacy trial-packet manifest is missing")
    observed_sha256 = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()
    if observed_sha256 != binding.get("sha256"):
        raise ValueError("sealed legacy trial-packet manifest file hash mismatch")
    manifest: dict[str, Any] = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    manifest_hash = manifest.pop("content_hash", None)
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["content_hash"] = manifest_hash
    if (
        manifest_hash != "sha256:" + hashlib.sha256(canonical).hexdigest()
        or manifest_hash != binding.get("content_hash")
        or manifest.get("summary", {}).get("distinct_hypothesis_identities") != 228
    ):
        raise ValueError("sealed legacy trial-packet manifest content does not reconcile")
    return manifest


def build_manifest() -> dict[str, Any]:
    sealed = _sealed_legacy_manifest()
    if sealed is not None:
        return sealed
    corpus = _paper_corpus()
    union = ExperimentUnion.discover(ACTIVE_LEDGER, REPO)
    first: dict[str, tuple[Any, Path]] = {}
    for path in union.paths:
        if not path.exists():
            continue
        ledger = ExperimentLog(path)
        for record in ledger.all():
            key = ledger._hypothesis_key(record.config)
            current = first.get(key)
            if current is None or (record.now_ms, record.config_hash) < (
                current[0].now_ms,
                current[0].config_hash,
            ):
                first[key] = (record, path)

    identities = []
    for key, (record, path) in sorted(first.items(), key=lambda item: (item[1][0].now_ms, item[0])):
        candidates = _candidate_papers(record.config, corpus)
        family_key = _family_key(record.config)
        binding = FAMILY_PAPER_BINDINGS.get(family_key)
        packet = _identity_packet(key, record.config_hash, family_key)
        verified_sections = list(packet["verified_sections"])
        missing_sections = list(packet["missing_sections"])
        is_complete = bool(packet["complete"] and not missing_sections)
        identities.append(
            {
                "hypothesis_key": key,
                "config_hash": record.config_hash,
                "label": _label(record.config),
                "research_family_key": family_key,
                "research_family_title": RESEARCH_FAMILIES[family_key]["title"],
                "sleeve_context": RESEARCH_FAMILIES[family_key]["sleeve"],
                "ledger_profile": path.parent.name,
                "ledger_source_path": str(path.relative_to(REPO)),
                "first_recorded_at": dt.datetime.fromtimestamp(
                    record.now_ms / 1000, tz=dt.UTC
                ).isoformat(),
                "measurement": {
                    "observations": record.n_obs,
                    "annualized_sharpe": _finite_or_none(record.sharpe_ann),
                    "skew": _finite_or_none(record.skew),
                    "kurtosis": _finite_or_none(record.kurtosis),
                },
                "candidate_public_papers": candidates,
                "candidate_match_is_verified": binding is not None,
                "verified_family_paper_path": binding["public_path"] if binding else None,
                "family_paper_binding_status": (
                    "VERIFIED_TAXONOMY_BINDING" if binding else "NO_VERIFIED_FAMILY_PAPER"
                ),
                "verified_packet_path": f"/glassbox/trial-packets/{key}.json",
                "identity_packet_content_hash": packet["content_hash"],
                "identity_packet_status": packet["packet_status"],
                "completion_assessment": packet["completion_assessment"],
                "verified_sections": verified_sections,
                "missing_sections": missing_sections,
                "coverage_status": (
                    "COMPLETE"
                    if is_complete
                    else "VERIFIED_INCOMPLETE_IDENTITY_PACKET"
                    if binding
                    else "CANDIDATE_PAPER_MATCH_UNVERIFIED"
                    if candidates
                    else "NO_PAPER_MATCH"
                ),
            }
        )

    candidate_matches = sum(bool(item["candidate_public_papers"]) for item in identities)
    complete_packets = sum(item["coverage_status"] == "COMPLETE" for item in identities)
    family_summaries = []
    for family_key, metadata in RESEARCH_FAMILIES.items():
        members = [item for item in identities if item["research_family_key"] == family_key]
        if not members:
            continue
        family_summaries.append(
            {
                "research_family_key": family_key,
                **metadata,
                "distinct_hypothesis_identities": len(members),
                "identities_with_candidate_paper_matches": sum(
                    bool(item["candidate_public_papers"]) for item in members
                ),
                "identities_with_verified_family_paper": sum(
                    item["family_paper_binding_status"] == "VERIFIED_TAXONOMY_BINDING"
                    for item in members
                ),
                "complete_trial_packets": sum(
                    item["coverage_status"] == "COMPLETE" for item in members
                ),
                "first_recorded_at": min(item["first_recorded_at"] for item in members),
                "last_recorded_at": max(item["first_recorded_at"] for item in members),
            }
        )
    canonical_corpus = json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode()
    ledger_hashes = {
        str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in union.paths
        if path.exists()
    }
    payload: dict[str, Any] = {
        "schema": "canli.alphac-trial-packet-manifest.v2",
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "claim_boundary": (
            "This manifest proves identity enumeration and reports candidate text matches. A "
            "verified family-paper binding can credit shared sections, but is not a complete "
            "identity-level trial packet. Coverage becomes COMPLETE only when all required "
            "sections are verified and a stable public packet is bound to the exact hypothesis key."
        ),
        "required_packet_sections": list(REQUIRED_PACKET_SECTIONS),
        "summary": {
            "distinct_hypothesis_identities": len(identities),
            "distinct_research_families": len(family_summaries),
            "published_markdown_papers": len(corpus),
            "identities_with_candidate_paper_matches": candidate_matches,
            "identities_with_verified_family_papers": sum(
                item["family_paper_binding_status"] == "VERIFIED_TAXONOMY_BINDING"
                for item in identities
            ),
            "identities_without_candidate_paper_matches": len(identities) - candidate_matches,
            "complete_trial_packets": complete_packets,
            "incomplete_trial_packets": len(identities) - complete_packets,
            "published_identity_packets": len(identities),
            "audited_not_currently_completable": sum(
                item["completion_assessment"]["status"]
                == "AUDITED_NOT_CURRENTLY_COMPLETABLE"
                for item in identities
            ),
            "audited_exact_replay_candidates": sum(
                item["completion_assessment"]["status"] == "AUDITED_EXACT_REPLAY_CANDIDATE"
                for item in identities
            ),
            "audited_exact_replays_failed_data_quality": sum(
                item["completion_assessment"]["status"]
                == "AUDITED_EXACT_REPLAY_FAILED_DATA_QUALITY"
                for item in identities
            ),
            "audited_exact_replays_failed_reproduction": sum(
                item["completion_assessment"]["status"]
                == "AUDITED_EXACT_REPLAY_FAILED_REPRODUCTION"
                for item in identities
            ),
            "audited_corrected_reproductions_kill_preserved": sum(
                item["completion_assessment"]["status"]
                == "AUDITED_CORRECTED_REPRODUCTION_KILL_PRESERVED"
                for item in identities
            ),
            "incomplete_not_yet_audited": sum(
                item["completion_assessment"]["status"] == "NOT_YET_AUDITED"
                for item in identities
            ),
            "coverage_status": (
                "COMPLETE"
                if complete_packets == len(identities)
                else "INCOMPLETE_BACKFILL_REQUIRED"
            ),
        },
        "source_provenance": {
            "ledger_sha256": ledger_hashes,
            "public_paper_corpus_sha256": hashlib.sha256(canonical_corpus).hexdigest(),
            "public_hosts_byte_identical": True,
        },
        "research_families": family_summaries,
        "identities": identities,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["content_hash"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    payload = build_manifest()
    rendered = json.dumps(payload, indent=2) + "\n"
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(rendered)
    for output in HOST_OUTPUTS:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
    summary = payload["summary"]
    complete = summary["complete_trial_packets"]
    identities = summary["distinct_hypothesis_identities"]
    candidate_mapped = summary["identities_with_candidate_paper_matches"]
    print(f"trial packets: {complete}/{identities} complete; {candidate_mapped} candidate-mapped")


if __name__ == "__main__":
    main()
