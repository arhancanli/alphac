#!/bin/bash
# AlphaForge crypto PAPER trading loop — runs HERE because this is the only host that can see
# Binance (the Mac is network-blocked in Turkey, the US droplet is geo-blocked 451).
#
# WHY THIS HOST HOLDS NO SECRETS. The sleeve is paper-only on PUBLIC market data: there is no
# Binance credential file anywhere in this system, and CCXTBroker refuses to act unless BOTH
# live.paper=False in config AND ALPHAFORGE_ARMED=1 in the environment. Neither is set here and
# neither should ever be. This box can therefore be rented, rebuilt or destroyed without any
# credential exposure — which is precisely why the loop was safe to move and the equity sleeves
# (which DO hold Alpaca keys) were not.
#
# WHAT STAYS ON THE MAC: published state, the glass-box export, and the signed append-only
# transparency chain. Those must have exactly ONE writer; two hosts appending to a tamper-evident
# record is a worse problem than any staleness it would fix. This host produces a track record;
# the Mac remains the only thing that publishes one.
#
# ORDERING: :05 ingest -> :10 trade (fresh lake first) -> Mac pulls at :20.
cd /opt/alphaforge || exit 1
LOCK=/opt/alphaforge/var/locks/trade.lock
mkdir -p /opt/alphaforge/var/locks
# Stale-lock recovery: a trap on EXIT does not fire for SIGTERM/OOM/reboot, so a killed run can
# leave this directory behind forever and silently mute the job (measured: 15 hours of lost
# collection on 2026-08-11). 45 min is far above this job's measured runtime.
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +45 2>/dev/null)" ]; then
  echo "$(date -u +%FT%TZ) releasing stale lock $LOCK (older than 45 min, owner gone)"
  rmdir "$LOCK" 2>/dev/null
fi
mkdir "$LOCK" 2>/dev/null || { echo "$(date -u +%FT%TZ) another trade run holds the lock"; exit 0; }
trap "rmdir $LOCK 2>/dev/null" EXIT
{
  echo "=== trade $(date -u +%FT%TZ) ==="
  # BOUNDED. An unbounded external call once blocked all trading on this system for 28h.
  timeout 2400 ./.venv/bin/af paper run --once 2>&1 | tail -25     || echo 'WARN: af paper run returned non-zero'
  # MAKER SHADOW v2 — samples the top-of-book on the names the sleeve actually holds, then
  # resolves matured quotes queue-aware and marks them at ts+60min. Records only; places no
  # orders and cannot touch the live loop. Runs AFTER the cycle so it shadows the real book.
  ./.venv/bin/python scripts/maker_shadow.py record   2>&1 | tail -2 || echo 'WARN: shadow record failed'
  echo "=== trade done $(date -u +%FT%TZ) ==="
} >> /opt/alphaforge/var/log/trade.log 2>&1
