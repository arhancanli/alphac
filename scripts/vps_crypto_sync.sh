#!/bin/zsh
# Pull the crypto lake down from the Binance-reachable VPS and MERGE it into the Mac's lake.
#
#   ./scripts/vps_crypto_sync.sh <ip> [ssh_key]
#
# *** WHY THIS MERGES INSTEAD OF COPYING — a data-loss bug, caught 2026-08-10 ***
# The first version of this script rsync'd VPS -> Mac at the FILE level. That is wrong, and it
# would have destroyed history the first time it succeeded. The VPS lake is NOT a superset of the
# Mac's: the VPS was provisioned empty and fetches only forward from the seeded watermark, so its
# per-instrument parquet holds RECENT ROWS ONLY. Measured on the day it was caught:
#     Mac  data/lake/funding/instrument_id=BINANCE:PERP:NIGHTUSDT/year=2026/data.parquet  19,263 B
#     VPS  /opt/alphaforge/.../NIGHTUSDT/year=2026/data.parquet                            6,090 B
# Same path, same instrument, same year partition — and the SMALLER file is the newer one. A
# file-level copy replaces the 19KB of history with 6KB of recent rows and loses the difference
# silently, because rsync has no idea the file is a row container rather than a blob.
#
# Parquet partitions are ROW CONTAINERS. The only correct operation is a row-level UNION with
# dedupe on the natural key. So this stages the VPS files somewhere harmless and merges them in.
#
# DIRECTION AND AUTHORITY. The VPS is authoritative for RECENT rows (it is the only host that can
# see Binance). The Mac is authoritative for HISTORY (it has years the VPS will never fetch).
# Neither is authoritative for the whole lake, which is exactly why neither may overwrite the
# other. The union is authoritative.
#
# NOT SYNCED: var/, artifacts/, any .env, the transparency key. The VPS has none of those and must
# never gain them — it is an ingest box, not a second brain.

set -u
IP="${1:-}"
KEY="${2:-$HOME/.ssh/moonshot_vps}"
if [ -z "$IP" ]; then echo "usage: $0 <ip> [ssh_key]"; exit 2; fi
RSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20"
REPO="$HOME/alphaforge"
STAGE="$REPO/var/vps_stage"

echo "=== crypto lake sync  VPS($IP) -> stage -> merge into Mac ==="

# STEP 1 — stage. Never rsync onto the live lake: a staging dir makes a bad transfer recoverable
# and makes the merge auditable before it touches anything real.
# MERGE ONLY WHAT ACTUALLY CHANGED. The VPS lake holds 4,508 parquet files once seeded with full
# history. rsync is already incremental and ships only the handful that moved, but an earlier
# version of this script then read and re-merged ALL of them every hour — thousands of parquet
# reads to find a few hundred new rows, which pushed the hourly tick past ten minutes and would
# eventually have collided with the next one. `--out-format=%n` makes rsync name exactly what it
# transferred, and only those files are merged. The staging dir is NOT wiped between runs, so
# unchanged files stay put and rsync keeps skipping them.
mkdir -p "$STAGE"
CHANGED="$STAGE/.changed.txt"
: > "$CHANGED"
for ds in funding ohlcv; do
  echo "--- fetching $ds ---"
  mkdir -p "$STAGE/$ds"
  rsync -az --out-format='%n' -e "$RSH" \
    root@"$IP":/opt/alphaforge/data/lake/$ds/ "$STAGE/$ds/" 2>/dev/null \
    | grep '\.parquet$' | sed "s|^|$ds/|" >> "$CHANGED" \
    || { echo "  rsync failed for $ds"; exit 1; }
done
echo "  changed files to merge: $(wc -l < "$CHANGED" | tr -d ' ')"

# STEP 2 — row-level merge with dedupe. Done in python because it is a data operation, not a file
# operation, and every guard below exists because the file-level version had no way to express it.
cd "$REPO" && .venv/bin/python - "$STAGE" <<'PY'
import os
import sys
from pathlib import Path

import pandas as pd

stage = Path(sys.argv[1])
LAKE = Path("data/lake")
# Natural keys. A row is the same row iff these match; anything else is a genuinely new observation.
KEYS = {"funding": ["instrument_id", "ts_funding"], "ohlcv": ["instrument_id", "ts_open"]}

# Only the files rsync reported as transferred this run (see the --out-format note above).
changed = stage / ".changed.txt"
rel_by_ds: dict[str, list[str]] = {k: [] for k in KEYS}
if changed.exists():
    for line in changed.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        ds, _, rel = line.partition("/")
        if ds in rel_by_ds and rel:
            rel_by_ds[ds].append(rel)

total_new = 0
for ds, keys in KEYS.items():
    src_files = [str(stage / ds / r) for r in rel_by_ds[ds] if (stage / ds / r).exists()]
    if not src_files:
        print(f"  {ds}: no changed files")
        continue
    added = replaced = created = 0
    for src in src_files:
        rel = os.path.relpath(src, stage / ds)
        dst = LAKE / ds / rel
        new = pd.read_parquet(src)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            new.to_parquet(dst, index=False)
            created += 1
            added += len(new)
            continue
        old = pd.read_parquet(dst)
        before = len(old)
        merged = pd.concat([old, new], ignore_index=True)
        k = [c for c in keys if c in merged.columns]
        if k:
            # keep='last' so a REVISED row from the venue wins over a stale local copy, while a
            # row the VPS never saw is preserved rather than dropped.
            merged = merged.drop_duplicates(subset=k, keep="last")
            merged = merged.sort_values(k)
        gained = len(merged) - before
        # THE GUARD THAT WOULD HAVE CAUGHT THE ORIGINAL BUG: a merge must never shrink a partition.
        if len(merged) < before:
            print(f"  !! REFUSING {rel}: merge would drop {before - len(merged)} rows — not writing")
            continue
        if gained:
            merged.to_parquet(dst, index=False)
            replaced += 1
            added += gained
    print(f"  {ds}: +{added} rows  ({created} new partitions, {replaced} merged)")
    total_new += added
print(f"  TOTAL new rows merged: {total_new}")
PY

# STEP 2b — pull the crypto TRACK RECORD back.
#
# UNLIKE THE LAKE, THIS IS A FILE COPY AND THAT IS CORRECT. The lake needed a row-level merge
# because Mac and VPS each hold rows the other lacks. The trading DB is different: once the paper
# loop moved to the VPS, the VPS became the SOLE WRITER and its database is the direct continuation
# of the Mac's (it was seeded from it). There is nothing on the Mac side to merge — only a stale
# snapshot to replace.
#
# THE GUARD MATTERS MORE THAN THE COPY. Copying a STALE VPS database over a NEWER Mac one would
# silently erase live history, so this only ever copies FORWARD IN TIME: it compares the newest row
# timestamp on each side and refuses if the VPS is not strictly ahead. That makes the operation
# safe to run before, during and after the cutover, including on a host where the loop has not
# started writing yet.
echo "--- pulling crypto track record (only if the VPS is strictly ahead) ---"
VPS_DB_TMP="$STAGE/trading_crypto_perp.sqlite"
if rsync -az -e "$RSH" root@"$IP":/opt/alphaforge/var/trading_crypto_perp.sqlite "$VPS_DB_TMP" 2>/dev/null; then
  cd "$REPO" && .venv/bin/python - "$VPS_DB_TMP" <<'PY'
import shutil
import sqlite3
import sys
from pathlib import Path

remote = Path(sys.argv[1])
local = Path("var/trading_crypto_perp.sqlite")


def newest(db: Path) -> int:
    """Newest row timestamp across the tables that constitute the track record."""
    if not db.exists():
        return -1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    best = 0
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            for c in ("ts", "ts_ms", "created_ms", "created_at_ms"):
                if c in cols:
                    v = con.execute(f'SELECT MAX("{c}") FROM "{t}"').fetchone()[0]
                    if isinstance(v, int | float) and v > best:
                        best = int(v)
                    break
    finally:
        con.close()
    return best


r_ts, l_ts = newest(remote), newest(local)
if r_ts > l_ts:
    shutil.copy2(remote, local)
    print(f"  track record updated: VPS {r_ts} > Mac {l_ts}")
elif r_ts == l_ts:
    print(f"  track record unchanged (both at {l_ts}) — the VPS loop has not written since last sync")
else:
    print(f"  REFUSING: VPS db ({r_ts}) is OLDER than the Mac's ({l_ts}) — not overwriting live history")
PY
else
  echo "  (no remote trading db yet — the loop has not run on the VPS)"
fi

# --- maker shadow: mirror the VPS record, same forward-only guard --------------------------------
# The VPS is the SOLE writer of the maker experiment (live_tick.sh no longer records here — see the
# long note there for why a second, connection-biased record on this host was a correctness bug and
# not merely a duplicate). This copy exists so that reporting and the 2026-08-19 promote decision
# read the authoritative population from the machine the sleeve actually trades on.
#
# Forward-only, for the same reason as above: an older VPS file must never overwrite a newer local
# one. The Mac's own divergent rows were quarantined to var/quarantine/ on 2026-08-12 rather than
# merged — unioning a continuously-sampled population with an intermittently-sampled one would have
# produced a fill rate describing neither.
echo "--- mirroring maker shadow record (only if the VPS is strictly ahead) ---"
MK_TMP="$STAGE/maker_shadow.sqlite"
if rsync -az -e "$RSH" root@"$IP":/opt/alphaforge/var/maker_shadow.sqlite "$MK_TMP" 2>/dev/null; then
  cd "$REPO" && .venv/bin/python - "$MK_TMP" <<'PY'
import shutil
import sqlite3
import sys
from pathlib import Path

remote = Path(sys.argv[1])
local = Path("var/maker_shadow.sqlite")


def newest(db: Path) -> int:
    if not db.exists():
        return -1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        v = con.execute("SELECT MAX(ts) FROM quotes").fetchone()[0]
        return int(v) if isinstance(v, int | float) else 0
    except sqlite3.Error:
        return -1
    finally:
        con.close()


r_ts, l_ts = newest(remote), newest(local)
if r_ts > l_ts:
    shutil.copy2(remote, local)
    print(f"  maker record updated: VPS {r_ts} > Mac {l_ts}")
elif r_ts == l_ts:
    print(f"  maker record unchanged (both at {l_ts})")
else:
    print(f"  REFUSING: VPS maker db ({r_ts}) is OLDER than the Mac's ({l_ts}) — not overwriting")
PY
else
  echo "  (no remote maker shadow db yet)"
fi

# --- Deribit research lake: append-only JSONL union, never a file replacement -------------------
# The Mac owns the June history and the VPS owns new reachable observations.  Daily files may be
# appended by a rerun, so neither `--ignore-existing` nor blind rsync replacement is correct.  Stage
# the remote tree, validate every line as JSON, then atomically write the line-level union.
echo "--- merging Deribit research snapshots from VPS ---"
DERIBIT_STAGE="$STAGE/deribit"
mkdir -p "$DERIBIT_STAGE"
if rsync -az -e "$RSH" root@"$IP":/opt/alphaforge/data/deribit/ "$DERIBIT_STAGE/" 2>/dev/null; then
  cd "$REPO" && .venv/bin/python - "$DERIBIT_STAGE" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

remote_root = Path(sys.argv[1])
local_root = Path("data/deribit")
added = 0
files = 0
for src in sorted(remote_root.rglob("*.jsonl")):
    rel = src.relative_to(remote_root)
    dst = local_root / rel
    old_lines = dst.read_text().splitlines() if dst.exists() else []
    incoming = src.read_text().splitlines()
    # Reject malformed transfer/source bytes before touching the local lake.
    for line in incoming:
        json.loads(line)
    seen = set(old_lines)
    new_lines = [line for line in incoming if line not in seen]
    if not new_lines:
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    merged = old_lines + new_lines
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", dir=dst.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(merged) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, dst)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    files += 1
    added += len(new_lines)
print(f"  Deribit merged: +{added} JSON rows across {files} changed files")
PY
else
  echo "  (remote Deribit lake unavailable — existing local history preserved)"
fi

# STEP 3 — freshness is the POINT of this script, so assert it rather than assume it. Scan EVERY
# file: an earlier version sampled the last 120 alphabetically and reported the lake stale while
# fresh rows sat in files the sample never opened.
cd "$REPO" && .venv/bin/python - <<'PY'
import glob
import pandas as pd
fs = glob.glob("data/lake/funding/**/*.parquet", recursive=True)
mx = None
names_today = set()
for f in fs:
    d = pd.read_parquet(f, columns=["instrument_id", "ts_funding"])
    if not len(d):
        continue
    t = pd.to_datetime(d["ts_funding"].max(), unit="ms", utc=True)
    mx = t if mx is None or t > mx else mx
now = pd.Timestamp.now("UTC")
print(f"  files scanned  : {len(fs)}")
print(f"  newest funding : {mx}")
if mx is not None:
    age = now - mx
    print(f"  age            : {age}")
    if age > pd.Timedelta(hours=12):
        print("  !! STILL STALE (>12h) — check the VPS timer:")
        print("  !!   ssh root@<ip> 'systemctl status af-ingest.timer; tail -40 /opt/alphaforge/var/log/ingest.log'")
    else:
        print("  OK — lake is current.")
PY
