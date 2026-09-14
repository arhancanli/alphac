"""Account for the retained directional development trial without implying admission."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    reservation = json.loads((directory / "reservation.json").read_text())
    result = json.loads((directory / "comparison.json").read_text())
    record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    if result["disposition"] != "RETAIN_FOR_FURTHER_TESTING":
        raise ValueError("This closure is only for the retained development trial")
    if reservation["trial_config"].get("trend_blend_normalization") != "directional_rms":
        raise ValueError("Directional trial required")
    if record["config"] != reservation["trial_config"]:
        raise ValueError("Measurement identity differs from reservation")
    statements = {
        "admission_or_kill_decision": "All frozen development criteria passed. Retain for further testing only. Full admission evaluation is INCOMPLETE_NOT_ADMITTED.",  # noqa: E501
        "code_environment_and_reproduction": "Runner, locked environment, sealed inputs and baseline reference comparison are preserved. No independent third-party reproduction is claimed.",  # noqa: E501
        "economic_mechanism_and_falsifiable_hypothesis": "Preserving the weighted time-series trend direction sought improved net risk-adjusted returns. The preregistered directional RMS construction passed all four development comparisons; this is already-inspected data, not untouched validation.",  # noqa: E501
        "execution_and_cost_model": "Both arms used matched modeled costs. Dated broker-level borrow, live implementation shortfall and capacity validation were not collected.",  # noqa: E501
        "family_and_union_trial_accounting": "The new identity remains in the discoverable experiment union. Previous rejected trials remain counted; retaining this candidate does not reset the search history.",  # noqa: E501
        "identity_and_authorship": "User-directed ALPHAC research, implementation and evaluation by Codex; not independent replication.",  # noqa: E501
        "literature_and_overlap_decision": "A construction variant of existing managed-futures trend, not a new independent sleeve. No new literature review or independent mechanism is claimed.",  # noqa: E501
        "machine_readable_packet_and_stable_public_paper": "Local machine-readable comparison and report are preserved. Reserved public URLs were not published; external distribution remains unestablished.",  # noqa: E501
        "point_in_time_data_and_survivorship_controls": "Previously inspected sealed inputs were reused. This is development evidence; historical short availability and untouched evaluation are not established.",  # noqa: E501
        "preregistration_and_hashes": "Reservation and source hashes were validated before computation; all available bindings are preserved.",  # noqa: E501
        "result_uncertainty_stress_capacity_and_diversification": "Paired summary, exact baseline reproduction and allocation/signal diagnostics are preserved. Independent uncertainty validation, capacity sweep, cost stress sweep, portfolio integration and PBO were not run. These are explicit admission blockers, not passing gates.",  # noqa: E501
    }
    block_path = directory / "admission_evidence_accounting.json"
    block_path.write_text(
        json.dumps(
            {
                "schema": "alphac.development-evidence-accounting.v1",
                "disposition": "INCOMPLETE_NOT_ADMITTED",
                "development_disposition": result["disposition"],
                "sections": statements,
            },
            indent=2,
        )
        + "\n"
    )
    names = [
        "reservation.json",
        "reservation_validation.json",
        "preregistration.json",
        "input_manifest.json",
        "environment.json",
        "comparison.json",
        "experiments.jsonl",
        "REPORT.md",
        "admission_evidence_accounting.json",
    ]
    bindings = [
        {"path": str((directory / name).relative_to(ROOT)), "sha256": sha(directory / name)}
        for name in names
    ]
    packet = {
        "schema": "canli.alphac-identity-trial-packet.v2",
        "hypothesis_key": reservation["hypothesis_identity"],
        "config_hash": record["config_hash"],
        "configuration": record["config"],
        "research_family_key": "managed_futures_trend",
        "complete": True,
        "missing_sections": [],
        "partial_sections": [],
        "packet_status": "COMPLETE_ACCOUNTING_FINAL_INCOMPLETE_NOT_ADMITTED",
        "completion_assessment": {
            "packet_evidence_accounting_complete": True,
            "candidate_evidence_complete_for_admission": False,
            "disposition": "INCOMPLETE_NOT_ADMITTED",
        },
        "required_sections": {
            name: {
                "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
                "statement": statement,
                "evidence": bindings,
            }
            for name, statement in statements.items()
        },
        "immutable_first_measurement": record,
        "claim_boundary": "Complete means every evidence section is accounted for by measured sources or explicit hash-bound limitations, following the existing final-incomplete packet convention. Admission evidence is NOT complete. No capacity, stress, independent reproduction or public publication is fabricated.",  # noqa: E501
    }
    packet["content_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    target = (
        ROOT / "artifacts/research/trial_packets" / f"{reservation['hypothesis_identity']}.json"
    )
    with target.open("x") as f:
        json.dump(packet, f, indent=2)
        f.write("\n")
    print(target)


if __name__ == "__main__":
    main()
