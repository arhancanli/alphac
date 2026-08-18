#!/bin/bash
# Hourly crypto ingest. Resumable and dedupe-safe: crash at any point and the next run resumes
# from the stored watermarks.
#
# STALE-RUN RECOVERY. The ingester refuses to start when a row in ops.sqlite says status='running',
# which is correct — two concurrent runs would race on the same lake and checkpoints. But a run
# killed by a timeout (or inherited inside a copied ops.sqlite, which is how 27 of them arrived
# here on 2026-08-10) leaves that row set forever and every subsequent hourly run exits instantly
# doing nothing. A run still 'running' after 2h is not running; nothing here takes 2h. Clear those
# and only those, so a genuinely concurrent run is still respected.
cd /opt/alphaforge || exit 1
LOCK=/opt/alphaforge/var/locks/ingest.lock
# Stale-lock recovery: a trap on EXIT does not fire for SIGTERM/OOM/reboot, so a killed run can
# leave this directory behind forever and silently mute the job (measured: 15 hours of lost
# collection on 2026-08-11). 90 min is far above this job's measured runtime.
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +90 2>/dev/null)" ]; then
  echo "$(date -u +%FT%TZ) releasing stale lock $LOCK (older than 90 min, owner gone)"
  rmdir "$LOCK" 2>/dev/null
fi
mkdir "$LOCK" 2>/dev/null || { echo "$(date -u +%FT%TZ) another run holds the file lock"; exit 0; }
trap "rmdir $LOCK 2>/dev/null" EXIT
{
  echo "=== ingest $(date -u +%FT%TZ) ==="
  ./.venv/bin/python - <<'PYEOF'
import sqlite3, time
cutoff = int(time.time() * 1000) - 2 * 3600 * 1000
c = sqlite3.connect('/opt/alphaforge/var/ops.sqlite')
n = c.execute("SELECT COUNT(*) FROM runs WHERE status='running' AND started_ms < ?", (cutoff,)).fetchone()[0]
if n:
    c.execute("UPDATE runs SET status='failed', finished_ms=?, detail='stale >2h, auto-cleared' "
              "WHERE status='running' AND started_ms < ?", (int(time.time()*1000), cutoff))
    c.commit()
    print(f'  cleared {n} stale run row(s) older than 2h')
c.close()
PYEOF
  ./.venv/bin/python /opt/alphaforge/stale_lock.py
  timeout 3000 ./.venv/bin/af data update 2>&1 | tail -5 || echo 'WARN: af data update returned non-zero'
  echo "=== done $(date -u +%FT%TZ) ==="
} >> /opt/alphaforge/var/log/ingest.log 2>&1
