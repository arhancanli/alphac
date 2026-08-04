#!/bin/zsh
# Canli Capital - WEEKLY corporate-actions ingest (splits + dividends) for the equity sleeve.
#
# WHY THIS EXISTS AS ITS OWN JOB (2026-08-02). Corporate actions used to be ingested INSIDE the
# daily AlphaMax tick (`ingest-equities` defaults to --corp-actions). That pass is per-ticker: two
# vendor REST calls for every instrument id in the lake (17,937 today). On the vendor's FREE tier
# (5 req/min) that is ~36,000 calls of mostly HTTP 429 — the tick launched 2026-07-21T05:00Z did
# not return until 2026-08-01T00:56Z. 10.8 days for ONE rebalance, because the walk-forward and the
# broker step sit BELOW the data phase in that script. The escape was `--no-corp-actions` on the
# daily tick, and that flag STAYS: trading must never be able to block on a vendor.
#
# But corp-actions OFF entirely is its own live risk, and a measured one. A 1-for-20 reverse split
# marked at raw prices (ALIT) once fabricated a -4.95% day, leaked -1.45% of real loss into the
# record, and falsely tripped the -10% drawdown brake so the book traded at half size for a week.
# Any split announced after ~2026-07 would re-create exactly that class of phantom mark.
#
# So: the ingest still runs, just NEVER on the trading path. This job is the only place corporate
# actions are pulled, it runs weekly, off-hours, and nothing downstream of it can be starved by it.
#
# WHY IT IS SAFE TO RUN LONG (and it does run long — see the measurements below):
#   * it is a SEPARATE unit on its own timer. No trading step is sequenced behind it.
#   * `ingest-equities` releases the exclusive var/ingest.lock when the BAR phase returns; the
#     corp-actions pass runs after that release. So even a multi-hour pass here cannot hold the
#     lock the daily bar ingest needs.
#   * the bar window below is DELIBERATELY EMPTY (--start == --until => zero sessions, zero S3
#     traffic). This job ingests corporate actions ONLY; bars remain the daily tick's job.
#   * its own single-runner lock means a slow week can never stack two grinders.
#   * a hard watchdog kills the pass rather than letting it run into the next scheduled cycle,
#     and every failure path is non-fatal (logged, exit 0) — a missed week self-heals next week
#     because the resume watermarks are per-instrument.
#
# MEASURED 2026-08-02 on the upgraded (Stocks Starter) key, before this script was written:
#   * 60 raw /v3/reference/splits calls: 60x HTTP 200, 0x 429, 306 calls/min sustained. The
#     free-tier 5/min wall that caused the 10.8-day stall is GONE.
#   * 20 real fetch_corporate_actions() calls (splits + dividends + pagination per instrument):
#     0.384 s/instrument => ~156 instruments/min => a FULL 17,937-id pass projects to ~1.9 h.
#   * the vendor is not the limit any more; per-instrument round-trip latency is.
#
# COST OF THE CADENCE, STATED PLAINLY: src/alphaforge/cli/data_cmds.py skips any key confirmed
# within a 5-day recheck cooldown and fetches 45 days FORWARD of `until`, so an announced split is
# always in the lake weeks before its ex-date. A 7-day cadence is longer than that 5-day cooldown,
# so in steady state essentially EVERY key is due each week and this job pays the full ~2 h pass
# every Sunday. That is accepted, not hidden: 2 h of off-path vendor calls is the price of never
# again marking a split at raw prices. The cheap fix is the vendor's UNFILTERED /v3/reference/
# splits+dividends endpoints (every ticker's actions in ~1 call per window), but that needs a
# source-adapter change in src/alphaforge/data/sources/, outside this script.
#
# NO STRATEGY KNOB LIVES HERE. This job writes only the corporate_actions dataset + its
# per-instrument watermarks. Alphas, K, cadence, weights, universe and costs are untouched.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks
# Single-runner lock (atomic mkdir; no flock on macOS). A full pass is ~2 h, so an overlapping run
# would mean two processes hammering the same reference endpoints and racing the same watermarks.
LOCK="var/locks/corp_actions_weekly.lock"
# Stale-lock reap: 8 h, deliberately LONGER than the watchdog below, so a healthy long pass is
# never mistaken for a dead one. Only a kill -9 (which skips the EXIT trap) can leave one behind.
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +480 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== corp_actions_weekly $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" >> var/log/corp_actions_weekly.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# Hard cap: 6 h. A healthy full pass measured ~1.9 h, so this is ~3x headroom; anything past it is
# a vendor stall, not work, and a stall must be killed rather than allowed to run into next week.
CA_WATCHDOG_S=21600
# macOS keeps the box awake for the pass; on the Linux box caffeinate is absent, so resolve it
# instead of hardcoding a path that would make the whole command "not found" there. It is an ARRAY,
# not a string: zsh does NOT word-split unquoted scalars, so a string here would be looked up as one
# command literally named "/usr/bin/caffeinate -s" (observed: the first run of this script failed
# exactly that way). An empty array expands to zero words, which is the Linux case.
CAFFEINATE=()
[ -x /usr/bin/caffeinate ] && CAFFEINATE=(/usr/bin/caffeinate -s)
CA_OUT="var/log/corp_actions_weekly.last"   # full transcript of the most recent pass (overwritten)
# The pass makes ~36,000 httpx calls and the shared logging config logs every request line at INFO
# WITH ITS QUERY STRING — which carries ``apiKey=<live Polygon key>`` in cleartext. That is a
# credential in a log file. This job refuses to write one: its transcript is filtered through the
# redactor below, and only a short digest (never the request lines) reaches the rolling job log.
# NOTE for the operator, reported not silently patched: the SHARED sink var/log/alphaforge.jsonl,
# written by src/alphaforge/core/logging.py for every job on this box, already contains the key in
# cleartext (3,042 occurrences on 2026-08-01 alone). Fixing that needs a filter in core/logging.py,
# outside this script's scope. var/ is gitignored, so it has not left the box.
REDACT='s/apiKey=[A-Za-z0-9_.-]*/apiKey=REDACTED/g'
setopt pipefail   # ...so the redactor's exit status can never mask a failed ingest below

{
  echo "=== corp_actions_weekly $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  set -a; . "$HOME/.config/alphaforge/polygon.env" 2>/dev/null; set +a

  TODAY="$(date -u +%F)"

  echo "--- corporate actions (splits/dividends) for every equity id in the lake ---"
  # --start == --until => an EMPTY bar window: available_sessions() returns [] for until <= start,
  # so the flat-files phase does zero S3 work and this job is corp-actions ONLY, exactly as
  # designed. Bars stay the daily tick's responsibility and are unaffected by whatever this does.
  # --profile equity so the actions land in the SAME lake (data/lake) the live sleeve reads.
  # --corp-actions is the whole point of the job and is the flag the daily tick must never carry.
  #
  # WATCHDOG PATTERN: it matches "--corp-actions" specifically. The daily tick runs
  # "--no-corp-actions", which does NOT contain the literal "--corp-actions" (the two dashes sit
  # before "no", not before "corp"), so this watchdog can never reach across and kill the trading
  # tick's bar ingest if the two ever overlap. That cross-kill is exactly the sort of coupling this
  # split-out job exists to remove.
  ( sleep "${CA_WATCHDOG_S}"; pkill -TERM -f "ingest-equities.*--corp-actions" 2>/dev/null; \
    sleep 10; pkill -KILL -f "ingest-equities.*--corp-actions" 2>/dev/null ) &
  WD=$!
  T0=$SECONDS
  "${CAFFEINATE[@]}" uv run af data ingest-equities \
    --start "${TODAY}" --until "${TODAY}" --profile equity --corp-actions \
    2>&1 | sed -E "${REDACT}" > "${CA_OUT}" \
    || echo "WARN: corp-actions ingest returned non-zero (vendor/network) — non-fatal, retries next week"
  ELAPSED=$((SECONDS - T0))
  kill "${WD}" 2>/dev/null; wait "${WD}" 2>/dev/null

  # Digest, not transcript: ~36k request lines belong in CA_OUT, not in the rolling job log.
  grep -m1 '\[ingest-equities\]:' "${CA_OUT}" 2>/dev/null
  echo "  per-instrument failures (isolated, never abort the pass): $(grep -c 'corp_actions_failed' "${CA_OUT}" 2>/dev/null)"
  echo "  cooldown-skipped keys (confirmed <5d ago): $(grep -o 'n_skipped=[0-9]*' "${CA_OUT}" 2>/dev/null | tail -1)"
  SUMMARY="$(grep -m1 '^corporate-actions:' "${CA_OUT}" 2>/dev/null)"
  if [ -n "${SUMMARY}" ]; then
    echo "RESULT: ${SUMMARY} elapsed=${ELAPSED}s"
  else
    # No summary line means the pass never reached the corp-actions step (credential/vendor/kill).
    # Say so loudly: a silent green log here is how the sleeve went dark for 11 days last time.
    echo "RESULT: NO corp-actions summary emitted after ${ELAPSED}s — the pass did not complete;"
    echo "RESULT: splits after the last successful pass are NOT in the lake until this succeeds."
  fi
  echo "=== corp_actions_weekly done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/corp_actions_weekly.log 2>&1

# Non-fatal posture, matching every other tick on this box: a data job must never leave a failed
# unit behind that an operator has to reset before the next cycle can run.
exit 0
