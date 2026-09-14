"""Close a reconciled diagnostic packet; never execute strategy returns."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_terminal_comparison_20260913_attempt2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm")
    args = parser.parse_args()
    directory = OUT / args.arm
    audit = json.loads((directory / "independent_audit.json").read_text())
    assert audit["status"] == "SAVED_CONTROL_RECONCILED"
    for path, digest in audit["source_sha256"].items():
        assert sha(ROOT / path) == digest
    assert (directory / "REPORT.md").is_file()
    record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    reservation = json.loads((directory / "reservation.json").read_text())
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/59901461092dd7a6.json").read_text()
    )
    packet = {
        k: v
        for k, v in template.items()
        if k not in {"content_hash", "required_sections", "immutable_first_measurement"}
    }
    limitation = (
        "Retrospective crypto correction diagnostic, not exact legacy replay or qualified alpha. "
        "Static metadata applicability, funding marks, publication lag and terminal prices are modeled. "
        "All scenarios retained; remaining comparisons and benchmark-adjusted excess metrics pending. "
        "No untouched OOS, independent external reproduction, capacity proof or admission."
    )
    files = [
        directory / n
        for n in [
            "reservation.json",
            "preregistration.json",
            "reservation_validation.json",
            "experiments.jsonl",
            "execution_complete.json",
            "independent_audit.json",
            "REPORT.md",
            "run/walkforward.json",
        ]
    ]
    files += [
        OUT / "protocol.json",
        OUT / "input_manifest.json",
        ROOT / "scripts/audit_crypto_terminal_arm.py",
        Path(__file__),
    ]
    evidence = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]
    packet.update(
        hypothesis_key=reservation["hypothesis_identity"],
        config_hash=record["config_hash"],
        configuration=record["config"],
        immutable_first_measurement=record,
        claim_boundary=limitation,
    )
    packet["required_sections"] = {
        name: {
            "status": "MEASURED_EVIDENCE_OR_EXPLICIT_BOUND_LIMITATION",
            "statement": limitation,
            "evidence": evidence,
        }
        for name in template["required_sections"]
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
        json.dump(packet, f, indent=2, sort_keys=True)
        f.write("\n")
    with (directory / "closure.json").open("x") as f:
        json.dump(
            {
                "status": "MEASURED_ARM_RECONCILED_PACKET_CLOSED",
                "qualified": False,
                "packet": str(target.relative_to(ROOT)),
                "packet_sha256": sha(target),
                "independent_audit_sha256": sha(directory / "independent_audit.json"),
            },
            f,
            indent=2,
        )
        f.write("\n")
    print(f"{args.arm}: packet closed")


if __name__ == "__main__":
    main()
