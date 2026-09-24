#!/usr/bin/env python3
"""Build the trial-reasoning dataset: every governed trial, as a record a model can learn from.

WHAT A RECORD IS. One tested hypothesis, end to end: the family and label, the configuration as
it was fixed, the first measurement, the evidence sections that exist and the ones that are
missing, and, for a trial with a sealed closure, the decision and every gate it failed. Failures
are the point: few public datasets show research that did not work and exactly why.

WHAT IT NEVER CONTAINS. Vendor rows. A record carries our own configuration, our own statistics
and our own decisions, and names its data sources by key only.

RIGHTS TIER, per record, from the sources its family used (the all-sleeve rights audit):
- COMMERCIAL_CANDIDATE: every source is public government data whose reuse is documented (SEC,
  EIA). Still subject to their named exceptions and an owner decision before any sale.
- FREE_RESULTS_ONLY: at least one source restricts derived publication; the record mirrors what
  the glass box already publishes (results, never rows) and may not be sold or licensed.
- UNMAPPED: the family has no sleeve in the rights audit; excluded from every release tier.

Nothing here publishes anything. External release of either tier is the owner's decision.

    uv run python scripts/build_trial_reasoning_dataset.py [--write]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
PACKETS: Final = ROOT / "artifacts" / "research" / "trial_packets"
FORWARD_INDEX: Final = PACKETS / "forward_index.json"
RIGHTS_AUDIT: Final = ROOT / "artifacts" / "publication" / "all_sleeve_data_rights_audit.json"
SLEEVE_EVIDENCE: Final = ROOT / "config" / "sleeve_publication_evidence.json"
OUTPUT_DIR: Final = ROOT / "artifacts" / "datasets" / "trial_reasoning" / "v0"
SCHEMA: Final = "canli.trial-reasoning-record.v0"
MANIFEST_SCHEMA: Final = "canli.trial-reasoning-dataset.v0"
PUBLIC_REUSE_SOURCES: Final = frozenset({"SEC_PUBLIC_DATA_AND_FILINGS", "EIA_PUBLIC_DATA"})
INDEX_FILES: Final = frozenset({"index.json", "forward_index.json"})
# Instrument-id venue prefix -> the rights-policy source it implies. A packet's family is its trial
# ACCOUNT (combined-book studies of equity momentum and crypto carry are charged to
# managed_futures_trend), so sources read from the account alone can miss a venue the trial traded.
# Adding these can only move a record to a stricter tier, never a looser one.
VENUE_SOURCES: Final = {"BINANCE:": "BINANCE_EXCHANGE_MARKET_DATA"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _content_hash(document: dict[str, Any]) -> str:
    body = {key: value for key, value in document.items() if key != "content_hash"}
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def family_sources(
    rights_audit: dict[str, Any], sleeve_evidence: dict[str, Any]
) -> dict[str, list[str]]:
    """Trial family -> the source keys its sleeve depends on, joined on the sleeve registry key."""
    by_sleeve = {
        record["registry_key"]: sorted({d["source_key"] for d in record["source_dependencies"]})
        for record in rights_audit["records"]
    }
    out: dict[str, list[str]] = {}
    for registry_key, sleeve in sleeve_evidence["sleeves"].items():
        if registry_key in by_sleeve:
            out[sleeve["trial_family_key"]] = by_sleeve[registry_key]
    return out


def trial_sources(
    account_sources: list[str] | None, configuration: dict[str, Any] | None
) -> list[str]:
    """The account's sources plus every venue the trial's own instruments name."""
    found = set(account_sources or [])
    for instrument in (configuration or {}).get("instrument_ids") or []:
        for prefix, source in VENUE_SOURCES.items():
            if str(instrument).startswith(prefix):
                found.add(source)
    return sorted(found)


def rights_tier(sources: list[str] | None) -> str:
    if not sources:
        return "UNMAPPED"
    if set(sources) <= PUBLIC_REUSE_SOURCES:
        return "COMMERCIAL_CANDIDATE"
    return "FREE_RESULTS_ONLY"


PREREG_MAX_BYTES: Final = 64_000


def _decision(closure: dict[str, Any] | None) -> dict[str, Any] | None:
    """The sealed verdict in one shape across the three closure schemas.

    Narrative-change closures list every failed gate; development-trial closures state the study's
    own verdict in a sentence; the portable-carry closure names the fields it never froze.
    """
    if closure is None:
        return None
    decision = closure.get("decision") or {}
    finding = closure.get("governance_finding") or {}
    return {
        "closure_schema": closure.get("schema"),
        "disposition": decision.get("disposition"),
        "admitted": decision.get("admitted"),
        "external_disposition": decision.get("external_disposition"),
        "statement": decision.get("statement"),
        "checks_evaluated": decision.get("checks_evaluated"),
        "failed_gates": list(decision.get("failures") or []),
        "unfrozen_fields": list(finding.get("required_but_unfrozen_fields") or []),
        "headline": closure.get("headline"),
    }


def _preregistration(closure: dict[str, Any] | None, root: Path) -> dict[str, Any] | None:
    """The trial's own sealed preregistration (our authorship), when its closure binds one."""
    for evidence in ((closure or {}).get("lineage") or {}).get("decision_evidence") or []:
        path = root / str(evidence.get("path", ""))
        if path.name == "preregistration.json" and path.is_file():
            raw = path.read_bytes()
            if len(raw) > PREREG_MAX_BYTES or hashlib.sha256(raw).hexdigest() != evidence.get(
                "sha256"
            ):
                return None  # moved since sealing, or too large to carry inline: cite, never guess
            return {
                "path": evidence["path"],
                "sha256": evidence["sha256"],
                "document": json.loads(raw),
            }
    return None


def build_record(
    packet: dict[str, Any],
    closure: dict[str, Any] | None,
    sources: list[str] | None,
    root: Path = ROOT,
) -> dict[str, Any]:
    first = packet.get("immutable_first_measurement") or {}
    configuration = packet.get("configuration") or {}
    # Unmapped stays unmapped: a venue found in the instruments cannot stand in for the missing
    # family review, so it only adds sources to an account that has a review.
    sources = trial_sources(sources, configuration) if sources else sources
    sections = packet.get("required_sections") or {}
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "hypothesis_key": packet["hypothesis_key"],
        "family_trial_account": packet.get("research_family_key"),
        "alpha_names": list(configuration.get("alpha_names") or []),
        "label": packet.get("label"),
        "evidence_date": packet.get("evidence_date"),
        "packet_status": packet.get("packet_status"),
        "complete": bool(packet.get("complete")),
        "configuration": packet.get("configuration"),
        "first_measurement": {
            "annualized_sharpe": first.get("annualized_sharpe"),
            "observations": first.get("observations"),
            "skew": first.get("skew"),
            "kurtosis": first.get("kurtosis"),
        },
        "evidence_sections": {name: body.get("status") for name, body in sorted(sections.items())},
        "missing_sections": sorted(packet.get("missing_sections") or []),
        "preregistration": _preregistration(closure, root),
        "decision": _decision(closure),
        "data_sources": sources or [],
        "rights_tier": rights_tier(sources),
        "packet_content_hash": packet.get("content_hash"),
    }
    record["content_hash"] = _content_hash(record)
    return record


def load_inputs(
    root: Path = ROOT,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
    packets_dir = root / PACKETS.relative_to(ROOT)
    packets = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(packets_dir.glob("*.json"))
        if path.name not in INDEX_FILES
    ]
    packets = [
        p for p in packets if p.get("schema", "").startswith("canli.alphac-identity-trial-packet")
    ]
    closures: dict[str, dict[str, Any]] = {}
    forward = root / FORWARD_INDEX.relative_to(ROOT)
    if forward.is_file():
        for row in json.loads(forward.read_text(encoding="utf-8"))["packets"]:
            path = (row.get("closure") or {}).get("path")
            if path and (root / path).is_file():
                closures[row["hypothesis_key"]] = json.loads(
                    (root / path).read_text(encoding="utf-8")
                )
    sources = family_sources(
        json.loads((root / RIGHTS_AUDIT.relative_to(ROOT)).read_text(encoding="utf-8")),
        json.loads((root / SLEEVE_EVIDENCE.relative_to(ROOT)).read_text(encoding="utf-8")),
    )
    return packets, closures, sources


def build(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    packets, closures, sources = load_inputs(root)
    # A packet published under both its hash and a reserved alias is one trial, counted once.
    seen: set[str] = set()
    records = []
    for packet in packets:
        key = packet["hypothesis_key"]
        if key in seen:
            continue
        seen.add(key)
        records.append(
            build_record(
                packet, closures.get(key), sources.get(packet.get("research_family_key")), root
            )
        )
    tiers = Counter(r["rights_tier"] for r in records)
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "author": "Arhan Canli",
        "claim_boundary": (
            "Our own governed trials: configurations, statistics and decisions, never vendor rows. "
            "FREE_RESULTS_ONLY records mirror what the glass box already publishes and may not be "
            "sold or licensed; COMMERCIAL_CANDIDATE needs an owner decision before any sale; "
            "nothing "
            "here is published by this build."
        ),
        "records": len(records),
        "with_sealed_decision": sum(1 for r in records if r["decision"] is not None),
        "with_inline_preregistration": sum(1 for r in records if r["preregistration"] is not None),
        "dispositions": dict(
            sorted(Counter(r["decision"]["disposition"] for r in records if r["decision"]).items())
        ),
        "complete_packets": sum(1 for r in records if r["complete"]),
        "rights_tiers": dict(sorted(tiers.items())),
        "family_trial_accounts": dict(
            sorted(Counter(r["family_trial_account"] for r in records).items())
        ),
        "failed_gate_frequency": dict(
            Counter(
                gate.split(":")[0] + ":" + gate.split(":")[1] if gate.count(":") >= 1 else gate
                for r in records
                if r["decision"]
                for gate in r["decision"]["failed_gates"]
            ).most_common(25)
        ),
        "records_sha256": hashlib.sha256(
            b"".join(_canonical(r) + b"\n" for r in records)
        ).hexdigest(),
    }
    manifest["content_hash"] = _content_hash(manifest)
    return records, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write", action="store_true", help=f"write {OUTPUT_DIR.relative_to(ROOT)}"
    )
    args = parser.parse_args()
    records, manifest = build()
    print(
        f"{manifest['records']} trials, {manifest['with_sealed_decision']} with a sealed decision, "
        f"tiers {manifest['rights_tiers']}"
    )
    if args.write:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with (OUTPUT_DIR / "records.jsonl").open("wb") as handle:
            for record in records:
                handle.write(_canonical(record) + b"\n")
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        print(f"wrote {OUTPUT_DIR.relative_to(ROOT)}  {manifest['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
