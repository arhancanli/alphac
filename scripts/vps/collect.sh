#!/bin/bash
# Hourly positioning/order-flow capture. Deliberately makes no claim and runs no test — it
# accumulates history that cannot be bought back. See collect_positioning.py for the full rationale.
cd /opt/alphaforge || exit 1
LOCK=/opt/alphaforge/var/locks/collect.lock
mkdir -p /opt/alphaforge/var/locks
# Stale-lock recovery: a trap on EXIT does not fire for SIGTERM/OOM/reboot, so a killed run can
# leave this directory behind forever and silently mute the job (measured: 15 hours of lost
# collection on 2026-08-11). 45 min is far above this job's measured runtime.
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +45 2>/dev/null)" ]; then
  echo "$(date -u +%FT%TZ) releasing stale lock $LOCK (older than 45 min, owner gone)"
  rmdir "$LOCK" 2>/dev/null
fi
mkdir "$LOCK" 2>/dev/null || { echo "$(date -u +%FT%TZ) another collect run holds the lock"; exit 0; }
trap "rmdir $LOCK 2>/dev/null" EXIT
{
  echo "=== collect $(date -u +%FT%TZ) ==="
  timeout 1500 ./.venv/bin/python collect_positioning.py 2>&1 | tail -10 || echo 'WARN: collector returned non-zero'
  # Maker-shadow EVALUATE runs here, 30 minutes after trade.sh records at :10, because
  # running both in the same tick left quotes 3.6s short of their 60min horizon and
  # delayed every maturation by a full extra hour. The mark comes from the kline at
  # ts+horizon, so a later evaluate changes nothing except eligibility.
  ./.venv/bin/python scripts/maker_shadow.py evaluate 2>&1 | tail -2 || echo 'WARN: shadow evaluate failed'
  echo "=== collect done $(date -u +%FT%TZ) ==="
} >> /opt/alphaforge/var/log/collect.log 2>&1
