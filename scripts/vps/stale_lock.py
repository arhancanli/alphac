#!/usr/bin/env python3
'''Release the ingest lock ONLY when the process that holds it is genuinely gone.

THE LOCK THIS CLEARS, and why the first attempt cleared the wrong thing. The ingester holds TWO
independent things: rows in ops.sqlite  with status='running', and a pid file at
var/ingest.lock. On 2026-08-10 the DB rows were cleared and the hourly timer STILL exited instantly
with LockHeldError, because the real blocker was the pid file — held by pid 10079, a run killed by
an ssh timeout, which never got to remove it. A lock whose owner is dead is not protecting
anything; it is just stopping work.

The check is deliberately conservative: read the pid, and only unlink if that pid does not exist.
If the holder is alive this does nothing, so a genuinely concurrent run is still respected. Never
clear a lock on age alone — a long backfill is legitimately long, and killing it mid-write is how
you corrupt a lake.
'''
import os, sys
from pathlib import Path

lock = Path('/opt/alphaforge/var/ingest.lock')
if not lock.exists():
    sys.exit(0)
raw = lock.read_text().strip()
try:
    pid = int(raw.split()[0])
except (ValueError, IndexError):
    print(f'  lock file unparseable ({raw!r}) — leaving it alone for a human')
    sys.exit(0)
try:
    os.kill(pid, 0)          # signal 0 = existence check, does not touch the process
except ProcessLookupError:
    lock.unlink()
    print(f'  released stale lock: holder pid {pid} no longer exists')
except PermissionError:
    print(f'  pid {pid} exists (owned by another user) — lock is LIVE, leaving it')
else:
    print(f'  pid {pid} is alive — lock is LIVE, leaving it')
