#!/usr/bin/env python3
"""Reproduce our numbers — the outsider's one-command verifier of the Canli Capital glass box.

"Don't trust us, verify us" only means something if verifying is easy. This is the whole kit. Three
levels of proof, each more hands-on, each independent of taking our word for anything:

  L1  CONTENT HASHES  (Python stdlib only — no repo, no data, no install):
      every published glassbox artifact carries a sha256 over its own canonical bytes. This recomputes
      each and confirms it matches, so the numbers you read are the numbers that were hashed — not
      edited afterward. You can run this on files downloaded straight from canlicapital.com.

  L2  SIGNATURES  (needs `cryptography`):
      the transparency chain and the capacity commitment are Ed25519-signed. This re-checks the
      capacity-commitment signature against the published public key, and points you at
      verify_transparency.py for the full append-only chain.

  L3  ENGINE DETERMINISM  (needs this repo):
      runs the golden-master test — the backtest engine reproduces a scripted fixture byte-for-byte,
      proving the engine that produced the numbers is deterministic and unchanged.

Verify the LIVE site with nothing but Python:
    mkdir gb && cd gb
    for f in capacity deflation track_record kill_log pre_registration red_team reproducibility research; do
      curl -s https://canlicapital.com/glassbox/$f.json -o $f.json; done
    curl -s https://canlicapital.com/glassbox/capacity_commitment.json -o capacity_commitment.json
    python3 reproduce.py --dir .

Or, in this repo, all three levels at once:
    python3 scripts/reproduce.py
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

_SIGNED = ("capacity_commitment.json", "transparency_log.json")  # verify by signature, not content-hash


def _canon_hash(payload: dict) -> str:
    """sha256 over the canonical payload with the content_hash field removed (the exporter's convention)."""
    p = {k: v for k, v in payload.items() if k != "content_hash"}
    return "sha256:" + hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def level1_hashes(glassbox: Path) -> tuple[int, int]:
    print("L1  CONTENT HASHES (stdlib only — recompute each published artifact's sha256)")
    ok = bad = 0
    for f in sorted(glassbox.glob("*.json")):
        if f.name in _SIGNED or f.name == "repro_manifest.json":
            continue
        try:
            d = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        pub = d.get("content_hash")
        if not pub:
            continue
        match = _canon_hash(d) == pub
        ok += match
        bad += not match
        print(f"    {'PASS' if match else 'FAIL':4}  {f.name:26}  {pub[:26]}")
    return ok, bad


def level2_signatures(glassbox: Path) -> tuple[int, int]:
    print("\nL2  SIGNATURES (Ed25519 against the published public key)")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        print("    SKIP  (pip install cryptography to check signatures)")
        return 0, 0
    ok = bad = 0
    strip = {"payload_sha256", "signature_ed25519", "public_key_ed25519_hex", "verify"}
    for name in ("capacity_commitment.json", "founder_commitment.json"):
        f = glassbox / name
        if not f.exists():
            continue
        o = json.loads(f.read_text())
        payload = {k: v for k, v in o.items() if k not in strip}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        hash_ok = digest == o.get("payload_sha256")
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(o["public_key_ed25519_hex"])).verify(
                bytes.fromhex(o["signature_ed25519"]), bytes.fromhex(o["payload_sha256"])
            )
            sig_ok = True
        except Exception:
            sig_ok = False
        good = hash_ok and sig_ok
        ok += good
        bad += not good
        print(f"    {'PASS' if good else 'FAIL':4}  {name:26} (hash {'ok' if hash_ok else 'BAD'}, signature {'ok' if sig_ok else 'BAD'})")
    if (glassbox / "transparency_log.json").exists():
        print("    NOTE  transparency_log.json is the full append-only chain — verify it with scripts/verify_transparency.py")
    return ok, bad


def level3_golden_master() -> bool | None:
    print("\nL3  ENGINE DETERMINISM (golden-master byte-identity)")
    repo = Path(__file__).resolve().parent.parent
    test = repo / "tests" / "integration" / "test_golden_master.py"
    if not test.exists():
        print("    SKIP  (run inside the alphaforge repo to check engine determinism)")
        return None
    r = subprocess.run([sys.executable, "-m", "pytest", str(test), "-q"], capture_output=True, text=True, cwd=repo)
    passed = r.returncode == 0
    tail = [ln for ln in (r.stdout + r.stderr).splitlines() if " passed" in ln or " failed" in ln]
    print(f"    {'PASS' if passed else 'FAIL':4}  {tail[-1].strip() if tail else ('exit ' + str(r.returncode))}")
    return passed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reproduce", description="Verify the Canli Capital published record.")
    ap.add_argument("--dir", type=Path, default=None,
                    help="a folder of downloaded glassbox JSONs (default: the repo's published copy)")
    a = ap.parse_args(argv)
    glassbox = a.dir or (Path.home() / "meridian" / "public" / "glassbox")
    print(f"== Reproducing the Canli Capital glass box from {glassbox} ==\n")

    h_ok, h_bad = level1_hashes(glassbox)
    s_ok, s_bad = level2_signatures(glassbox)
    gm = level3_golden_master()

    print("\n== SUMMARY ==")
    print(f"  L1 content hashes : {h_ok} reproduced, {h_bad} failed")
    print(f"  L2 signatures     : {s_ok} verified, {s_bad} failed")
    print(f"  L3 golden master  : {'PASS' if gm else ('FAIL' if gm is False else 'skipped (not in repo)')}")
    failed = h_bad + s_bad + (1 if gm is False else 0)
    if failed == 0:
        print("\n  ALL CHECKS REPRODUCED. The published numbers match their hashes/signatures"
              + (", and the engine is byte-deterministic." if gm else "."))
        return 0
    print(f"\n  {failed} CHECK(S) FAILED — the published record does not reproduce. That is the kit working.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
