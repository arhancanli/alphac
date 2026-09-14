"""Close local diagnostic only after both independent funded audits pass."""
import argparse,json
from run_trend_funded_account import ROOT, OUT, sha, write
import hashlib
def close_packet(directory, reservation):
    record = json.loads((directory / "experiments.jsonl").read_text().splitlines()[-1])
    template = json.loads(
        (ROOT / "artifacts/research/trial_packets/59901461092dd7a6.json").read_text()
    )
    packet = {
        k: v
        for k, v in template.items()
        if k not in {"content_hash", "required_sections", "immutable_first_measurement"}
    }
    files = [
        directory / n
        for n in [
            "reservation.json",
            "preregistration.json",
            "reservation_validation.json",
            "experiments.jsonl",
            "result.json",
            "REPORT.md",
            "funded_session_audit.json",
            "quantity_calendar_audit.json",
            "funded_calendar.csv",
            "run/run_meta.json",
            "run/session_summary.json",
        ]
    ] + [OUT / "protocol.json", OUT / "input_manifest.json"]
    evidence = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in files]
    limitation = (
        "Current-vintage development comparison on inspected history; "
        "explicit raw fills and payable dividends. "
        "Modeled costs/borrow, static metadata, "
        "no contemporaneous publication or historical borrow proof. "
        "No untouched test, independent reproduction, capacity validation or admission. "
        "Saved-event quantities and NAV reconcile; daily borrow attribution is modeled. "
        "Recorded prices/fees and settlement amounts remain inputs. No source/execution qualification."
    )
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
    write(
        ROOT / "artifacts/research/trial_packets" / f"{reservation['hypothesis_identity']}.json",
        packet,
    )


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('arm',choices=['baseline','baseline_stress']);d=OUT/p.parse_args().arm
 a=json.loads((d/'quantity_calendar_audit.json').read_text());assert max(a['residuals'].values())<1e-6 and not a['qualified']
 for name in ['funded_session_audit.json','quantity_calendar_audit.json']:
  audit=json.loads((d/name).read_text())
  for path,digest in audit['sha256'].items():assert sha(ROOT/path)==digest,path
 close_packet(d,json.loads((d/'reservation.json').read_text()))
 write(d/'funded_packet_closure.json',{'status':'LOCAL_FUNDED_NORMAL_OR_STRESS_DIAGNOSTIC_CLOSED','qualified':False,'quantity_calendar_audit_sha256':sha(d/'quantity_calendar_audit.json')})
 print('Closed',d.name)
