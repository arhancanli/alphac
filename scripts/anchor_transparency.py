#!/usr/bin/env python3
"""External anchoring of the transparency chain into Bitcoin via OpenTimestamps — the S-tier trust seal.

The signed Ed25519 chain (scripts/transparency_log.py) proves our published record is append-only and
internally consistent. But WE hold the private key, so a hardened skeptic can still object: "you could
regenerate the entire chain today with fresh timestamps and re-sign it." This script closes exactly
that hole. Each time the chain gains a new head, we commit the head's chain_hash to the BITCOIN
BLOCKCHAIN via OpenTimestamps. Bitcoin's block time is something we cannot forge, backdate, or
regenerate — so the anchor is an INDEPENDENT witness that the record existed at a point in time.

What it adds over the signed chain: the chain proves "not edited since first published"; the anchor
proves "first published no later than this Bitcoin block." Together: a record we cannot rewrite OR
backdate. Anyone verifies with the standard `ots` tool or https://opentimestamps.org — trusting us for
nothing.

Lifecycle: a fresh stamp is calendar-attested (PENDING); it upgrades to a full Bitcoin attestation
after the next block aggregation (~1-6h). Each daily run stamps the new head and upgrades prior
pending proofs. Proofs + a human-readable head file live in var/ots/ and publish to the sites'
glassbox/ots/ with an anchors.json manifest and verify instructions.

Run AFTER scripts/transparency_log.py in the publish pipeline.
"""
# ruff: noqa: E501
from __future__ import annotations

import contextlib
import hashlib
import json
import subprocess
from pathlib import Path

from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

REPO = Path(__file__).resolve().parent.parent
LOG_JSONL = REPO / "var" / "transparency_log.jsonl"
OTS_DIR = REPO / "var" / "ots"
OTS_BIN = REPO / ".venv" / "bin" / "ots"
# the opentimestamps.org pool answers reliably; the eternitywall/catallaxy CLI defaults often time out
CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://alice.btc.calendar.opentimestamps.org",
)
PUB_DIRS = (
    Path.home() / "meridian" / "public" / "glassbox" / "ots",
    Path.home() / "meridian-app" / "public" / "glassbox" / "ots",
)


def _stamp(file_digest: bytes) -> bytes:
    """Submit a file's sha256 to the calendars; return a serialized (pending) .ots proof."""
    ts = Timestamp(file_digest)
    n = 0
    for url in CALENDARS:
        try:
            ts.merge(RemoteCalendar(url).submit(file_digest, timeout=20))
            n += 1
        except Exception:
            continue
    if n == 0:
        raise RuntimeError("no OpenTimestamps calendar attested the digest")
    ctx = BytesSerializationContext()
    DetachedTimestampFile(OpSHA256(), ts).serialize(ctx)
    return ctx.getbytes()


def _load(ots_path: Path) -> DetachedTimestampFile:
    return DetachedTimestampFile.deserialize(BytesDeserializationContext(ots_path.read_bytes()))


def _status(dtf: DetachedTimestampFile) -> dict:
    """pending (calendar only) vs bitcoin (block-confirmed, un-forgeable)."""
    for _msg, att in dtf.timestamp.all_attestations():
        if isinstance(att, BitcoinBlockHeaderAttestation):
            return {"status": "bitcoin", "bitcoin_block_height": int(att.height)}
    return {"status": "pending"}


def _upgrade(ots_path: Path) -> None:
    """Best-effort: pull the Bitcoin attestation once the calendar has it (no resubmission)."""
    with contextlib.suppress(Exception):
        subprocess.run([str(OTS_BIN), "upgrade", str(ots_path)], capture_output=True, timeout=60)


def main() -> int:
    if not LOG_JSONL.exists():
        print("no transparency chain yet — nothing to anchor")
        return 0
    chain = [json.loads(line) for line in LOG_JSONL.read_text().splitlines() if line.strip()]
    if not chain:
        return 0
    OTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) stamp the current head if it is not already anchored
    head = chain[-1]
    name = f"seq{head['seq']:04d}_{head['chain_hash'][:12]}"
    head_file = OTS_DIR / f"{name}.head.txt"
    ots_file = OTS_DIR / f"{name}.head.txt.ots"
    if not ots_file.exists():
        head_file.write_text(
            "Canli Capital — transparency chain anchor\n"
            f"seq: {head['seq']}\ndate: {head['date']}\nchain_hash: {head['chain_hash']}\n"
        )
        digest = hashlib.sha256(head_file.read_bytes()).digest()
        ots_file.write_bytes(_stamp(digest))
        print(f"anchored head seq {head['seq']} ({head['chain_hash'][:16]}...) -> {ots_file.name} [pending Bitcoin]")
    else:
        print(f"head seq {head['seq']} already anchored ({ots_file.name})")

    # 2) upgrade prior pending proofs toward a full Bitcoin attestation
    upgraded = 0
    for p in sorted(OTS_DIR.glob("*.head.txt.ots")):
        if _status(_load(p))["status"] == "pending":
            _upgrade(p)
            if _status(_load(p))["status"] == "bitcoin":
                upgraded += 1
    if upgraded:
        print(f"upgraded {upgraded} pending proof(s) to Bitcoin attestation")

    # 3) manifest the anchors (newest first), tying each .ots back to its chain entry
    by_seq = {c["seq"]: c for c in chain}
    anchors = []
    for p in sorted(OTS_DIR.glob("*.head.txt.ots")):
        seq = int(p.name.split("_")[0][3:])
        c = by_seq.get(seq, {})
        anchors.append({
            "seq": seq,
            "date": c.get("date"),
            "chain_hash": c.get("chain_hash"),
            "head_file": p.name[:-4],          # the .head.txt that was stamped
            "ots_file": p.name,
            **_status(_load(p)),
        })
    anchors.sort(key=lambda a: a["seq"], reverse=True)

    manifest = {
        "schema": "glassbox.ots_anchors/1",
        "method": "OpenTimestamps checkpoints for selected transparency-chain heads.",
        "what_it_proves": (
            "A Bitcoin-confirmed OpenTimestamps proof shows that the exact checkpoint file digest "
            "existed no later than the attesting block. A pending proof is calendar-attested only "
            "and is not yet a Bitcoin confirmation. The checkpoint binds a chain head, not the truth "
            "or completeness of the underlying broker record."
        ),
        "does_not_prove": (
            "It does not establish when an unanchored entry was first published, make opaque payload "
            "hashes reconstructable, prove that the data came from Alpaca, or rule out an unpublished "
            "alternative chain."
        ),
        "how_to_verify": [
            "pip install opentimestamps-client",
            "Download a head file and its proof from this folder, e.g. {f}.head.txt and {f}.head.txt.ots".format(
                f=anchors[0]["head_file"].rsplit(".head.txt", 1)[0] if anchors else "seqNNNN_xxxx"
            ),
            "Run:  ots verify <file>.head.txt.ots   (it reports the Bitcoin block + time the head was committed)",
            "Confirm the chain_hash inside the head file matches the head in transparency_log.json.",
            "Or upload the .ots proof at https://opentimestamps.org",
        ],
        "head_anchor": anchors[0] if anchors else None,
        "anchor_count": len(anchors),
        "bitcoin_confirmed_count": sum(a["status"] == "bitcoin" for a in anchors),
        "calendar_pending_count": sum(a["status"] == "pending" for a in anchors),
        "anchors": anchors,
    }

    # 4) publish manifest + proof files to every site's glassbox/ots/
    pending = sum(1 for a in anchors if a["status"] == "pending")
    confirmed = len(anchors) - pending
    for pub in PUB_DIRS:
        if not pub.parent.parent.is_dir():  # only if the site checkout exists
            continue
        pub.mkdir(parents=True, exist_ok=True)
        (pub / "anchors.json").write_text(json.dumps(manifest, indent=2) + "\n")
        for src in list(OTS_DIR.glob("*.head.txt")) + list(OTS_DIR.glob("*.head.txt.ots")):
            (pub / src.name).write_bytes(src.read_bytes())
        print(f"published {len(anchors)} anchors -> {pub} ({confirmed} bitcoin, {pending} pending)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
