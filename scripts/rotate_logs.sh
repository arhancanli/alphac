#!/bin/zsh
# Canli Capital - bound the growth of var/log.
#
# There was no rotation at all until 2026-08-20. var/log had reached 284MB, with a single
# alphamax_tick.log at 197MB across 44 runs (~4.5MB per run) and live_tick.log growing every
# hour. Disk was not close to full, so this is not a fire — but an unbounded writer on the box
# that runs the publish pipeline is a slow fuse, and a disk-full event here does not degrade
# gracefully: it takes down the hourly tick, the deploy and the transparency chain together.
#
# COPYTRUNCATE, deliberately, rather than rename-and-recreate. The tick scripts hold their log
# open for the whole run (`{ ... } >> LOG`). Renaming the file out from under a live writer
# leaves it appending to an invisible inode for the rest of the run, so the hour a rotation
# happens to overlap the :25 tick would silently lose that tick's entire transcript. Copying
# then truncating in place keeps the inode, and O_APPEND writers resume correctly at offset 0.
# The trade is the handful of lines written between the copy and the truncate. For logs that is
# the right trade; for the transparency chain it would not be, which is why this touches ONLY
# var/log and never data/, artifacts/ or public/.
#
# Never fails the caller. A rotation problem must not take down a publish.

set -u
AF="${HOME}/alphaforge"
LOGDIR="$AF/var/log"
MAX_BYTES=$(( 32 * 1024 * 1024 ))   # rotate anything over 32MB

[ -d "$LOGDIR" ] || exit 0

rotated=0
for f in "$LOGDIR"/*.log; do
  [ -f "$f" ] || continue
  size=$(/usr/bin/stat -f %z "$f" 2>/dev/null) || continue
  [ "$size" -gt "$MAX_BYTES" ] 2>/dev/null || continue

  if /bin/cp "$f" "$f.1" 2>/dev/null; then
    # CARRY THE TAIL FORWARD, do not truncate to empty (fixed 2026-08-20, same day, by this
    # script breaking a monitor within the hour). health_check.py's C5a/C5c/C5d/publisher checks
    # answer "when did this loop last run?" by grepping the log for a marker line like
    # "=== alphamax_tick done 2026-08-20T05:06:28Z ===". Emptying the file deletes the only
    # record of that, and the check does not degrade to "unknown" — it reports "no marker", which
    # is the same shape as "the job never ran". Rotation is disk hygiene; it must not be able to
    # tell the monitor a job is dead.
    # The carried lines keep their ORIGINAL timestamps, so the age the monitor computes stays
    # true. Nothing here fabricates a run.
    # Single redirect rather than truncate-then-append: the file is never observably empty.
    if ! /usr/bin/tail -n 300 "$f.1" > "$f" 2>/dev/null; then
      echo "  rotate: carry-forward FAILED for $f — leaving it alone"
      /bin/rm -f "$f.1"
      continue
    fi
    /usr/bin/gzip -f "$f.1" 2>/dev/null &
    mb=$(( size / 1024 / 1024 ))
    echo "  rotated $(basename "$f") (${mb}MB) -> $(basename "$f").1.gz"
    rotated=$(( rotated + 1 ))
  else
    echo "  rotate: copy FAILED for $f — left untouched"
  fi
done
wait 2>/dev/null

# Drop compressed generations older than 30 days; one generation back is enough history to
# diagnose a failure, and nothing reads these programmatically.
/usr/bin/find "$LOGDIR" -name '*.log.1.gz' -mtime +30 -delete 2>/dev/null

[ "$rotated" -gt 0 ] && echo "  log rotation: $rotated file(s) rotated" || echo "  log rotation: nothing over 32MB"
exit 0
