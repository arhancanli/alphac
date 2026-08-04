#!/usr/bin/env python3
"""Founder skin-in-the-game — a SIGNED disclosure of the founder's own capital commitment.

Skin in the game is a trust signal because it cannot be faked cheaply: the founder's own money rides
the exact live record published here, on the same terms as anyone else. This emits that disclosure,
signs it with the same Ed25519 key as the transparency chain (authenticated, tamper-evident), and is
honest about scale — a small commitment stated plainly beats a big one implied. Anyone verifies the
signature with the published public key.

A disclosure, NOT investment advice or an offer. Run in the publish pipeline; idempotent.
"""
# ruff: noqa: E501
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
from transparency_log import _canon, _load_or_create_key, _public_hex, _sha256  # noqa: E402

_AMOUNT_USD = 1000
_PUB_DIRS = (
    Path.home() / "meridian" / "public" / "glassbox",
    Path.home() / "meridian-app" / "public" / "glassbox",
)


def main() -> int:
    payload = {
        "schema": "glassbox.founder_commitment/1",
        "title": "Founder skin-in-the-game",
        "summary": "The founder's own capital, committed on the same terms as any future investor — "
                   "stated plainly, signed so it cannot be quietly edited.",
        "commitment": [
            f"The founder commits USD {_AMOUNT_USD:,} of personal capital at first live (real-money) "
            "deployment of the book.",
            "It deploys into the SAME book, at the SAME time, on the SAME terms as any external "
            "capital — never a preferential share class, never a side pocket, never a better entry.",
            f"USD {_AMOUNT_USD:,} is small in absolute terms and we will not pretend otherwise. What it "
            "buys is alignment: the founder's own money rides the exact live record published here, "
            "win or lose, before anyone else is asked to.",
            "As the live track record earns it, the founder's commitment scales with the book. Any "
            "change is disclosed here, signed and dated — never walked back in silence.",
        ],
        "amount_usd": _AMOUNT_USD,
        "trigger": "first live (real-money) deployment",
        "honest_scope": "A disclosure of the founder's own capital commitment, signed so it cannot be "
                        "quietly edited. NOT investment advice, an offer, or a solicitation. No real "
                        "capital is deployed yet; this is a forward commitment that activates at first "
                        "live deployment.",
        "as_of": dt.datetime.now(dt.UTC).date().isoformat(),
    }
    key = _load_or_create_key()
    payload_sha256 = _sha256(_canon(payload))
    out = {
        **payload,
        "payload_sha256": payload_sha256,
        "signature_ed25519": key.sign(bytes.fromhex(payload_sha256)).hex(),
        "public_key_ed25519_hex": _public_hex(key),
        "verify": "Remove {payload_sha256, signature_ed25519, public_key_ed25519_hex, verify}, "
                  "canonical-JSON the rest (sorted keys, compact separators), sha256 it (= payload_sha256), "
                  "then check the Ed25519 signature over that hash against the public key.",
    }
    blob = json.dumps(out, indent=2) + "\n"
    for d in _PUB_DIRS:
        if d.parent.parent.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            (d / "founder_commitment.json").write_text(blob)
            print(f"signed founder commitment -> {d / 'founder_commitment.json'}")
    print(f"amount ${_AMOUNT_USD:,} | payload_sha256 {payload_sha256[:16]}… | signed by {_public_hex(key)[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
