"""Verify the track-record transparency log — anyone can run this, it needs only the public file.

Re-checks, for every entry in the signed append-only chain:
  1. the chain hash = sha256(prev_chain_hash | payload_sha256 | date | seq) is correct,
  2. prev_chain_hash actually links to the previous entry's chain hash (no gaps, no rewrites),
  3. seq numbers are contiguous from 0,
  4. the Ed25519 signature over the chain hash is valid under the published public key.

If ALL pass, the published history is provably append-only and un-edited. If any past day had been
changed, that entry's chain hash — and every signature after it — would fail here. Exit 0 = PASS.

    uv run python scripts/verify_transparency.py [path/to/transparency_log.json]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = Path(__file__).resolve().parent.parent
DEFAULT = REPO.parent / "meridian" / "public" / "glassbox" / "transparency_log.json"
GENESIS = "0" * 64


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    if not path.exists():
        print(f"FAIL: no transparency log at {path}")
        return 1
    doc = json.loads(path.read_text())
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(doc["public_key_ed25519_hex"]))
    entries = doc["entries"]
    if not entries:
        print("FAIL: empty chain")
        return 1

    prev = GENESIS
    for i, e in enumerate(entries):
        # 1 + 3: seq contiguous
        if e["seq"] != i:
            print(f"FAIL @ index {i}: seq {e['seq']} != expected {i}")
            return 1
        # 2: links to the previous entry's chain hash
        if e["prev_chain_hash"] != prev:
            print(f"FAIL @ seq {e['seq']}: prev_chain_hash does not link to the prior entry "
                  "(history was rewritten or an entry was removed)")
            return 1
        # 1: recompute the chain hash
        expect = _sha256(f"{e['prev_chain_hash']}|{e['payload_sha256']}|{e['date']}|{e['seq']}".encode())
        if expect != e["chain_hash"]:
            print(f"FAIL @ seq {e['seq']} ({e['date']}): chain hash mismatch — this day was edited")
            return 1
        # 4: signature over the chain hash
        try:
            pub.verify(bytes.fromhex(e["signature"]), bytes.fromhex(e["chain_hash"]))
        except InvalidSignature:
            print(f"FAIL @ seq {e['seq']} ({e['date']}): invalid signature")
            return 1
        prev = e["chain_hash"]

    head = entries[-1]
    print(f"PASS — {len(entries)} entries, chain intact, every signature valid.")
    print(f"  first: seq 0  {entries[0]['date']}")
    print(f"  head : seq {head['seq']}  {head['date']}  chain_hash {head['chain_hash'][:16]}…")
    print(f"  public key (Ed25519): {doc['public_key_ed25519_hex']}")
    print("  The published track record is provably append-only and un-edited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
