#!/bin/zsh
# Canli Capital — hourly pull of the crypto lake from the Binance-reachable VPS.
#
# WHY THIS EXISTS AS ITS OWN JOB. The VPS is the only host that can see Binance (the Mac is
# network-blocked in Turkey; the US droplet is geo-blocked 451). It ingests hourly at :05. Nothing
# on the Mac was pulling that down, so the freshly-fetched data sat on a rented server while the
# sleeve here still marked on a stale lake — which is the same failure the whole exercise was meant
# to end, just moved one host to the left.
#
# RUNS AT :20 — deliberately after the VPS's :05 ingest, leaving it ~15 minutes to finish. If it
# has not, no harm: the merge is a row-level UNION and the next hour picks up whatever arrived
# late. There is no ordering requirement and nothing is lost by being early.
#
# THE MERGE IS NOT A COPY. scripts/vps_crypto_sync.sh stages the remote files and unions them row
# by row with dedupe on the natural key, because the VPS holds RECENT ROWS ONLY while the Mac holds
# YEARS. A file-level copy would replace history with the recent slice and silently destroy the
# difference — that bug was caught on 2026-08-10 before it ever ran. It also refuses any merge that
# would shrink a partition.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks

VPS_IP="201.79.12.40"

# Single-runner lock: two concurrent merges would both read-modify-write the same parquet
# partitions and the later writer would silently drop the earlier one's rows.
LOCK="var/locks/vps_sync.lock"
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +45 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== vps_sync $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" \
    >> var/log/vps_sync.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

{
  echo "=== vps_sync $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  # BOUNDED. Every external call on this system is bounded since an unbounded one blocked all
  # trading for 28h. 20 min is generous: a healthy incremental sync is well under 2.
  ( sleep 1200; pkill -f "vps_crypto_sync.sh" 2>/dev/null ) &
  _WD=$!
  ./scripts/vps_crypto_sync.sh "$VPS_IP" || echo "WARN: vps_crypto_sync returned non-zero"
  kill "$_WD" 2>/dev/null; wait "$_WD" 2>/dev/null
  echo "=== vps_sync done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/vps_sync.log 2>&1
