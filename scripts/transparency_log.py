"""Tamper-evident transparency log for the live track record.

Every published track-record state enters a signed hash chain. Each entry hashes the canonical
daily payload and the previous link, then signs the link with Ed25519. From the payload-disclosure
boundary onward the canonical payload is included in the entry, so an outsider can independently
rehash the exact snapshot as well as verify the link and signature.

Historical v1 entries contain only opaque payload digests. Their linkage, signatures and external
OpenTimestamps checkpoints remain verifiable, but their underlying snapshots cannot be recovered
from the public chain and must not be described as independently content-verifiable. No historical
payload is reconstructed or fabricated. The chain also does not prove that broker data is true;
broker reconciliation and continuity evidence are separate gates.

Design:
  - Anchors the DAILY-resolution realized track record (live curves collapsed to one point per UTC
    day + each algorithm's standalone Sharpe / go-live). Append-only-on-change: hourly re-runs that
    add no new daily mark are no-ops, so the chain grows ~once per day.
  - Ed25519 keypair: private at ~/.config/alphaforge/transparency_ed25519.key (chmod 600, NEVER
    committed, generated on first run); public key published so anyone can verify.
  - The chain lives in var/transparency_log.jsonl (append-only) and is published in full to
    <meridian>/public/glassbox/transparency_log.json with the public key + verify instructions.

Verify with: uv run python scripts/verify_transparency.py
Run (in the publish pipeline):  uv run python scripts/transparency_log.py
"""
from __future__ import annotations

import datetime as dt
import json
import stat
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from alphaforge.validation.transparency import (
    GENESIS,
    PAYLOAD_SCHEMA,
    canonical_json,
    daily_track_record_payload,
    sha256_hex,
)

REPO: Final[Path] = Path(__file__).resolve().parent.parent
STATE_JSON: Final[Path] = REPO / "data" / "paper" / "state.json"
LOG_JSONL: Final[Path] = REPO / "var" / "transparency_log.jsonl"
KEY_PATH: Final[Path] = Path.home() / ".config" / "alphaforge" / "transparency_ed25519.key"
PUBLIC_OUT: Final[Path] = REPO.parent / "meridian" / "public" / "glassbox" / "transparency_log.json"


# --------------------------------------------------------------------------- keys
def _load_or_create_key() -> Ed25519PrivateKey:
    """Load the Ed25519 signing key (hex, chmod 600); generate + persist it on first run.

    The PRIVATE key never leaves this box and is never committed. Only the public key is published.
    """
    if KEY_PATH.exists():
        priv_hex = KEY_PATH.read_text().strip()
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    KEY_PATH.write_text(raw.hex() + "\n")
    KEY_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600 — owner read/write only
    print(f"generated new Ed25519 signing key at {KEY_PATH} (chmod 600, never commit)")
    return key


def _public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


# ----------------------------------------------------------------- payload digest
def _canon(obj: Any) -> bytes:
    return canonical_json(obj)


def _sha256(data: bytes) -> str:
    return sha256_hex(data)


_daily_digest = daily_track_record_payload


# ------------------------------------------------------------------- the chain
def _read_log() -> list[dict[str, Any]]:
    if not LOG_JSONL.exists():
        return []
    return [json.loads(line) for line in LOG_JSONL.read_text().splitlines() if line.strip()]


def main() -> int:
    if not STATE_JSON.exists():
        print(f"no state.json at {STATE_JSON} — run paper_trading_state.py first")
        return 1
    state = json.loads(STATE_JSON.read_text())
    key = _load_or_create_key()
    pub_hex = _public_hex(key)

    digest = _daily_digest(state)
    payload_sha256 = _sha256(_canon(digest))

    chain = _read_log()
    disclosure_upgrade = bool(chain and "payload" not in chain[-1])
    if chain and chain[-1]["payload_sha256"] == payload_sha256 and not disclosure_upgrade:
        print(f"transparency log: no change (head seq {chain[-1]['seq']}, "
              f"{chain[-1]['date']}). chain intact, {len(chain)} entries.")
        _publish(chain, pub_hex)  # still refresh the public copy (idempotent)
        return 0

    seq = len(chain)
    prev = chain[-1]["chain_hash"] if chain else GENESIS
    today = dt.datetime.now(tz=dt.UTC)
    date = today.date().isoformat()
    chain_hash = _sha256(f"{prev}|{payload_sha256}|{date}|{seq}".encode())
    signature = key.sign(bytes.fromhex(chain_hash)).hex()
    entry = {
        "seq": seq,
        "date": date,
        "generated_at": today.isoformat(),
        "payload_sha256": payload_sha256,
        "prev_chain_hash": prev,
        "chain_hash": chain_hash,
        "signature": signature,
        "payload_schema": PAYLOAD_SCHEMA,
        "payload": digest,
        "event": (
            "PAYLOAD_DISCLOSURE_UPGRADE"
            if disclosure_upgrade
            else "TRACK_RECORD_STATE"
        ),
    }
    LOG_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with LOG_JSONL.open("a") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
    chain.append(entry)
    _publish(chain, pub_hex)
    print(f"transparency log: APPENDED seq {seq} ({date}). chain head {chain_hash[:16]}…, "
          f"{len(chain)} entries, signed.")
    return 0


def _publish(chain: list[dict[str, Any]], pub_hex: str) -> None:
    """Emit the full signed chain + public key + verify instructions to the public glass-box dir."""
    disclosed = [entry for entry in chain if "payload" in entry]
    first_disclosed = disclosed[0]["seq"] if disclosed else None
    opaque_entries = len(chain) - len(disclosed)
    payload = {
        "schema": "glassbox.transparency_log/2",
        "title": "The Transparency Log",
        "summary": (
            "Every published state is linked and signed. From the declared disclosure boundary, "
            "the full canonical payload is also published and independently rehashable. Earlier "
            "entries remain signed opaque commitments, not reconstructable snapshots."
        ),
        "what_it_proves": (
            "The verifier checks link continuity, Ed25519 signatures, and every disclosed payload "
            "hash. OpenTimestamps separately timestamps selected chain heads. This makes disclosed "
            "snapshots tamper-evident; it does not prove broker truth, completeness before the "
            "disclosure boundary, or the absence of an unpublished alternative history."
        ),
        "payload_disclosure": {
            "payload_schema": PAYLOAD_SCHEMA,
            "first_disclosed_seq": first_disclosed,
            "disclosed_entries": len(disclosed),
            "opaque_historical_entries": opaque_entries,
            "historical_limitation": (
                "Entries before first_disclosed_seq contain signed payload hashes but not their "
                "canonical payloads. Their contents cannot be independently reconstructed from "
                "this public chain; no backfill is claimed."
            ),
        },
        "algorithm": "Ed25519 over sha256(prev_chain_hash | payload_sha256 | date | seq)",
        "public_key_ed25519_hex": pub_hex,
        "verify": "uv run python scripts/verify_transparency.py  (re-checks each chain hash + sig)",
        "entries": chain,
        "head": chain[-1] if chain else None,
        "entry_count": len(chain),
        # DAYS AND ENTRIES ARE NOT THE SAME NUMBER, and publishing one as the other overstated the
        # record by ~8x. The chain gains an entry on every PUBLISH, and the tick publishes hourly,
        # so 371 entries spanned 47 calendar dates. open.html rendered entry_count followed by the
        # literal word "days", under the heading "Signed chain", on the one page whose whole
        # argument is "don't trust us, verify us". The longer the site ran the worse the claim got,
        # because nothing tied the label to the data.
        # Both numbers are emitted, DERIVED from the chain and never typed, so the site can no
        # longer choose a flattering one by accident and neither can drift from the entries below.
        "distinct_days": len({e["date"] for e in chain}),
        "first_date": chain[0]["date"] if chain else None,
        "last_date": chain[-1]["date"] if chain else None,
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
    }
    if PUBLIC_OUT.parent.is_dir() or True:
        PUBLIC_OUT.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC_OUT.write_text(json.dumps(payload, indent=2) + "\n")
    # also drop a copy next to the app's public glass-box if present
    app_glass = Path.home() / "meridian-app" / "public" / "glassbox"
    if app_glass.is_dir():
        (app_glass / "transparency_log.json").write_text(json.dumps(payload, indent=2) + "\n")


# expose for the verifier
_PUBLIC_KEY_FROM_HEX = Ed25519PublicKey.from_public_bytes
__all__ = [
    "GENESIS",
    "PAYLOAD_SCHEMA",
    "_PUBLIC_KEY_FROM_HEX",
    "_canon",
    "_daily_digest",
    "_sha256",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
