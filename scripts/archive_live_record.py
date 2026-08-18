#!/usr/bin/env python3
"""Freeze the live paper record before an account is re-seeded — a one-way, hashed snapshot.

WHY THIS EXISTS. Alpaca paper accounts cannot be topped up; the only way to change a seed is a
RESET, which erases the account's equity history at the broker. On 2026-08-07 the owner chose to
re-seed AlphaMax and AlphaTrend so every sleeve runs a common, adequately-sized book (a $100k
account trading a 179-name dollar-neutral sleeve loses 5.6% of its short notional to whole-share
truncation and drifts +2.25% NET LONG — the neutrality the sleeve is built on).

A reset is the one operation in this system that destroys evidence. Everything the broker holds
about what actually happened — every fill, every daily equity mark, every position — exists in
exactly one place until this script copies it somewhere else. So this runs FIRST, and the reset is
gated on it.

WHAT IT CAPTURES, per sleeve:
  * the broker's own account snapshot and full portfolio history (pulled live from Alpaca, so the
    record is the BROKER's, not our reconstruction of it),
  * every open position at the moment of freeze,
  * the local trading DB in full (equity_curve, orders, fills, rejects),
  * the published data/paper/state.json as served to the public.

Then it writes a MANIFEST with a sha256 of every file and a sha256 over that manifest. The point
is not that a hash prevents tampering — anyone with write access can recompute one. The point is
that the pre-reset record has a fixed, quotable digest, so a later claim about what the first
live period contained can be checked against it rather than argued about. Publish the manifest
digest to the transparency chain and the freeze becomes checkable by a stranger.

    uv run python scripts/archive_live_record.py            # dry run: show what WOULD be captured
    uv run python scripts/archive_live_record.py --write    # perform the freeze
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_CFG = Path.home() / ".config" / "alphaforge"

# sleeve -> (credentials file, local trading DB). The DBs a sleeve actually writes; a sleeve with
# no DB yet is still captured for its broker-side history.
SLEEVES: dict[str, tuple[str, str | None]] = {
    "alphamax": ("alpaca_equity.env", "var/trading_equity.sqlite"),
    "alphatrend": ("alpaca.env", "var/trading_managed_futures.sqlite"),
    "alphaledger": ("alpaca_ledger.env", None),
    "alphaforge_crypto": (None, "var/trading_crypto_perp.sqlite"),  # not an Alpaca account
}


def _env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _get(base: str, path: str, hdr: dict[str, str], params: str = "") -> Any:
    url = base.rstrip("/") + path + (("?" + params) if params else "")
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _db_dump(db: Path) -> dict[str, Any]:
    """Every row of every table — the archive must not depend on this schema still existing."""
    out: dict[str, Any] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cur = con.execute(f"SELECT * FROM {t}")
            cols = [d[0] for d in cur.description]
            out[t] = {"columns": cols, "rows": [list(r) for r in cur.fetchall()]}
    finally:
        con.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archive_live_record")
    ap.add_argument("--write", action="store_true", help="perform the freeze (default: dry run)")
    ap.add_argument("--out", default=None, help="archive dir (default: artifacts/archive/live_record_<UTC>)")
    a = ap.parse_args(argv)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.out) if a.out else _REPO / "artifacts" / "archive" / f"live_record_{stamp}"
    print("=" * 88)
    print(f"FREEZE THE LIVE RECORD  ({'WRITING' if a.write else 'DRY RUN — nothing written'})")
    print(f"  target: {out}")
    print("=" * 88)

    captured: dict[str, Any] = {}
    for sleeve, (envf, dbf) in SLEEVES.items():
        print(f"\n[{sleeve}]")
        rec: dict[str, Any] = {}
        if envf:
            p = _CFG / envf
            if not p.exists():
                print(f"  credentials {p} MISSING — skipping broker capture")
            else:
                env = _env(p)
                hdr = {"APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
                       "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]}
                base = env.get("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
                try:
                    acct = _get(base, "/v2/account", hdr)
                    pos = _get(base, "/v2/positions", hdr)
                    hist = _get(base, "/v2/account/portfolio/history", hdr,
                                "period=all&timeframe=1D&extended_hours=false")
                    rec["account"] = acct
                    rec["positions"] = pos
                    rec["portfolio_history"] = hist
                    n_hist = len(hist.get("equity") or [])
                    print(f"  broker acct {acct.get('account_number')}  equity ${acct.get('equity')}"
                          f"  positions {len(pos)}  history points {n_hist}")
                except Exception as e:
                    print(f"  !! BROKER CAPTURE FAILED: {type(e).__name__}: {str(e)[:140]}")
                    rec["broker_capture_error"] = f"{type(e).__name__}: {e}"
        if dbf:
            db = _REPO / dbf
            if db.exists():
                rec["trading_db"] = _db_dump(db)
                counts = {t: len(v["rows"]) for t, v in rec["trading_db"].items()}
                print(f"  local db {dbf}: {counts}")
            else:
                print(f"  local db {dbf} MISSING")
        captured[sleeve] = rec

    state = _REPO / "data" / "paper" / "state.json"
    print(f"\n[published state] {state} ({'exists' if state.exists() else 'MISSING'})")

    if not a.write:
        print("\nDRY RUN — rerun with --write to perform the freeze.")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for sleeve, rec in captured.items():
        p = out / f"{sleeve}.json"
        p.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
        written.append(p)
    if state.exists():
        dst = out / "published_state.json"
        shutil.copy2(state, dst)
        written.append(dst)
    for db in sorted((_REPO / "var").glob("trading_*.sqlite")):
        dst = out / db.name
        shutil.copy2(db, dst)
        written.append(dst)

    manifest = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "reason": "pre-reset freeze: AlphaMax and AlphaTrend paper accounts re-seeded to a common "
                  "size so every sleeve trades an adequately-sized book. An Alpaca paper reset "
                  "erases broker-side equity history, so this snapshot is the only surviving copy "
                  "of the first live period.",
        "files": {p.name: {"sha256": _sha256(p), "bytes": p.stat().st_size} for p in sorted(written)},
    }
    mpath = out / "MANIFEST.json"
    mpath.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    digest = _sha256(mpath)
    (out / "MANIFEST.sha256").write_text(digest + "\n", encoding="utf-8")

    # Make the archive read-only: a freeze that can be edited in place is not a freeze.
    for p in [*written, mpath]:
        os.chmod(p, 0o444)

    print("\n" + "=" * 88)
    print(f"FROZEN — {len(written)} files")
    for name, meta in manifest["files"].items():
        print(f"  {meta['sha256'][:16]}…  {meta['bytes']:>10,}  {name}")
    print(f"\n  MANIFEST sha256: {digest}")
    print("  Publish that digest to the transparency chain; it is what makes this freeze")
    print("  checkable by someone who does not trust us.")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
