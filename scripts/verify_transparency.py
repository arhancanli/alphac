"""Verify the public track-record chain, signatures and disclosed payloads.

Re-checks, for every entry in the signed append-only chain:
  1. the chain hash = sha256(prev_chain_hash | payload_sha256 | date | seq) is correct,
  2. prev_chain_hash actually links to the previous entry's chain hash (no gaps, no rewrites),
  3. seq numbers are contiguous from 0,
  4. the Ed25519 signature over the chain hash is valid under the published public key.

V1 entries contain opaque payload hashes, so their underlying contents cannot be rehashed from the
public file. V2 entries include their canonical payload and are independently content-verifiable.
Exit 0 means the checks described here passed; it is not a broker attestation.

    uv run python scripts/verify_transparency.py [path/to/transparency_log.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from alphaforge.validation.transparency import validate_transparency_document

REPO = Path(__file__).resolve().parent.parent
DEFAULT = REPO.parent / "meridian" / "public" / "glassbox" / "transparency_log.json"
def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not path.exists():
        print(f"FAIL: no transparency log at {path}")
        return 1
    document = json.loads(path.read_text())
    try:
        result = validate_transparency_document(document)
    except (KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1
    entries = document["entries"]
    head = entries[-1]
    print(f"PASS — {result['entries']} entries, chain intact, every signature valid.")
    print(f"  first: seq 0  {entries[0]['date']}")
    print(f"  head : seq {head['seq']}  {head['date']}  chain_hash {head['chain_hash'][:16]}…")
    print(f"  public key (Ed25519): {document['public_key_ed25519_hex']}")
    print(
        f"  disclosed payloads: {result['disclosed_entries']}; independently rehashable "
        f"from seq {result['first_disclosed_seq']}"
    )
    print(
        f"  opaque historical commitments: {result['opaque_historical_entries']}; their "
        "payload contents are not recoverable from this file"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
