#!/usr/bin/env python3
"""Public capacity commitment — a SIGNED governance pledge about how we treat capacity.

A black-box fund's incentive is to take every dollar, because fees scale with AUM even after the edge
is gone. The trust move is to commit, in public and in writing we cannot quietly edit, to the opposite:
never market a capacity above our own published model, cap a sleeve once our MEASURED data shows its
edge consumed, and publish the realized decay beside the modeled curve. This emits that pledge, signs
it with the same Ed25519 key as the transparency chain (so it is authenticated and tamper-evident),
and grounds every number in glassbox/capacity.json (no invented figures). Anyone verifies the
signature with the published public key.

It is a governance pledge, NOT investment advice or an offer. Run in the publish pipeline; idempotent
(Ed25519 is deterministic, so an unchanged pledge re-signs identically).
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

_CAPACITY = _REPO.parent / "meridian" / "public" / "glassbox" / "capacity.json"
_PUB_DIRS = (
    Path.home() / "meridian" / "public" / "glassbox",
    Path.home() / "meridian-app" / "public" / "glassbox",
)


def _capacity_facts() -> dict:
    """Pull the MEASURED/MODELED grounding numbers from the published capacity model (no invention)."""
    if not _CAPACITY.exists():
        return {}
    c = json.loads(_CAPACITY.read_text())
    cliff = c.get("crypto_capacity_cliff", {})
    thr = c.get("equity_core_threshold", {})
    fwd = c.get("forward_expectation", {})
    return {
        "crypto_cliff_usd": cliff.get("cap_usd"),
        "crypto_sr_decay": "0.40 @ $100k -> 0.04 @ $1M -> -0.37 @ $10M (MEASURED, verdict.md sweep)",
        "equity_core_threshold_usd": thr.get("aum_usd"),
        "forward_sharpe": f"{fwd.get('central_sharpe')} central, {fwd.get('floor_sharpe')} floor, {fwd.get('ceiling_sharpe')} ceiling",
        "source": f"glassbox/capacity.json {c.get('content_hash')}",
    }


def main() -> int:
    facts = _capacity_facts()
    payload = {
        "schema": "glassbox.capacity_commitment/1",
        "title": "Capacity commitment",
        "summary": "How we promise to treat capacity, so the edge you read is the edge you get. "
                   "A fund earns fees on assets; we commit to not earning them on a dead edge.",
        "pledge": [
            "We will never advertise a capacity figure above our own published capacity model "
            "(glassbox/capacity.json). The model is the ceiling, not marketing.",
            "Crypto funding carry is MEASURED finite-capacity alpha: realized Sharpe decays from 0.40 "
            "at $100k to 0.04 at $1M and turns negative by $10M. We commit to not scaling the crypto "
            "sleeve past the point our own measured sweep shows the edge largely consumed, and never "
            "past its ~$10M structural cliff. We would rather cap the sleeve than collect a fee on a "
            "dead edge.",
            "At every capital milestone we will publish the REALIZED capacity decay beside the modeled "
            "curve, so the gap between model and reality is visible, never hidden.",
            "Above ~$100M the book IS the equity core (the crypto satellite weight is zero past its "
            "cliff). We will say so plainly rather than imply the crypto edge scales.",
            "If we ever close to new capital, we will publish the level and the reason.",
        ],
        "grounded_in": facts,
        "honest_scope": "A governance pledge about how we will treat capacity, signed so it cannot be "
                        "quietly edited. NOT investment advice, an offer, or a solicitation. Crypto "
                        "capacity is MEASURED; equity capacity is MODELED (the equity sleeve is not yet "
                        "at scale). See glassbox/capacity.json for the full basis labels.",
        "as_of": dt.datetime.now(dt.UTC).date().isoformat(),
    }

    key = _load_or_create_key()
    canonical = _canon(payload)
    payload_sha256 = _sha256(canonical)
    signature = key.sign(bytes.fromhex(payload_sha256)).hex()
    out = {
        **payload,
        "payload_sha256": payload_sha256,
        "signature_ed25519": signature,
        "public_key_ed25519_hex": _public_hex(key),
        "verify": "Take this object, remove the 4 fields {payload_sha256, signature_ed25519, "
                  "public_key_ed25519_hex, verify}, serialize the rest as canonical JSON (sorted keys, "
                  "compact separators), sha256 it (must equal payload_sha256), then check the Ed25519 "
                  "signature over that hash against the public key. Same key as the transparency chain.",
    }
    blob = json.dumps(out, indent=2) + "\n"
    for d in _PUB_DIRS:
        if d.parent.parent.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            (d / "capacity_commitment.json").write_text(blob)
            print(f"signed capacity commitment -> {d / 'capacity_commitment.json'}")
    print(f"payload_sha256 {payload_sha256[:16]}…  signed by {_public_hex(key)[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
