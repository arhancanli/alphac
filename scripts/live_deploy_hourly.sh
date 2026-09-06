#!/bin/zsh
# Canli Capital - HOURLY light web deploy (rides the hourly live tick).
#
# The live tick regenerates paper-state.json + the glassbox JSONs every hour, but the public
# sites only redeployed once a day (live_publish.sh @ 02:10) — so the web app could serve data
# up to ~24h stale. This script closes that gap: after each tick, if the SERVED data actually
# changed, redeploy both Vercel projects (prod). Change-gated by a content hash so idle hours
# (no new daily mark, market closed) are a no-op — typically a handful of real deploys per day.
#
# ACCURACY GUARDS (never publish wrong/stale data):
#   - state.json must parse AND be generated within the last 2h (a partial tick failure must
#     not push stale data with a fresh deploy timestamp);
#   - the deploy only stamps the last-deployed hash AFTER both projects deploy successfully,
#     so a failed deploy retries naturally on the next hour.
# The nightly live_publish.sh remains the full ceremony (anchoring, reproduce, capacity).

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
AF="$HOME/alphaforge"
cd "$AF" || exit 1
mkdir -p var/log
. "$HOME/alphaforge/scripts/lib/bounded.sh"
. "$HOME/alphaforge/scripts/lib/indexnow.sh"
. "$HOME/alphaforge/scripts/lib/site_snapshot.sh"
LOG="var/log/live_deploy.log"
HASH_FILE="var/last_web_deploy.hash"

{
  echo "=== live_deploy_hourly $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

  # accuracy guard: fresh, parseable state only
  if ! .venv/bin/python3 - <<'PY'
import datetime as dt, json, sys
s = json.load(open("data/paper/state.json"))
gen = dt.datetime.fromisoformat(s["generated_at"])
age_h = (dt.datetime.now(dt.UTC) - gen).total_seconds() / 3600
sys.exit(0 if age_h <= 2.0 else 1)
PY
  then
    echo "SKIP: state.json stale (>2h) or invalid — not deploying stale data"
    exit 0
  fi

  # change gate: hash EVERY served data artifact, not just two of them.
  # FIXED 2026-08-05: the gate previously hashed only paper-state.json and transparency_log.json.
  # That meant a change to kill_log.json alone — i.e. a CORRECTION to the public research record —
  # did not count as "data changed", so the deploy skipped and the correction sat on disk
  # indefinitely while the wrong number stayed live. A fund whose product is the honesty of its
  # record must never have a publication path that can silently swallow a correction.
  # FIXED AGAIN 2026-08-06: the gate hashed only the DATA, so a change to the SITE ITSELF
  # never counted as a change. A full landing-page rewrite (sections cut, a factual
  # contradiction removed, a missing risk caveat added) was built, tested and committed to
  # disk, and the hourly deploy skipped it with "no data change" because paper-state.json
  # happened to be identical. The site can go stale for exactly the same reason a correction
  # could before yesterday's fix. Hash the SOURCE as well as the data: any edit to markup,
  # styles, scripts or per-page config is a publishable change.
  # THIRD FIX, same day: the first version hashed only the DATA, the second added markup,
  # styles and scripts -- and still missed public/, so a corrected social card (the old one
  # advertised a forward Sharpe of "0.7 to 1.0" against a published 0.3 to 0.9) sat undeployed.
  # Enumerating directories keeps losing. Hash EVERY source file in the site tree instead, so
  # the gate cannot be wrong again by omission. Excludes only the derived/vendored dirs
  # (node_modules, dist, .git, .bak) -- everything else that could reach a visitor is in.
  # FOURTH fix, same day, same class: the previous version hashed the LANDING tree only, so
  # dashboard-only changes (the +20% overlay finally rendered, a live dot that stopped pulsing
  # over a dark sleeve) deployed nothing. This script deploys TWO projects; it must watch both.
  # Also excludes .next and .vercel, which are build/CI output for the Next.js app.
  # FIFTH fix, 2026-08-23: each site's root artifacts/ directory contains unserved QA and SEO
  # receipts. IndexNow writes a timestamped receipt there after deploy; hashing that receipt made
  # the next hourly run see a source change, redeploy, and submit the same URL set again forever.
  # Exclude only the two unserved ROOT artifact directories. A public/artifacts directory, if one
  # is ever added, remains covered because it can reach visitors.
  NEW_HASH=$(site_source_hash)
  OLD_HASH=$(cat "$HASH_FILE" 2>/dev/null)
  if [ -n "$NEW_HASH" ] && [ "$NEW_HASH" = "$OLD_HASH" ]; then
    echo "no data or source change since last deploy — skipping"
    exit 0
  fi

  # shared lock: never deploy while the nightly full publish is deploying (they overlap by
  # schedule — hourly :05 vs publish 02:10 — and would otherwise race on the same two projects).
  if ! deploy_lock_acquire; then
    echo "SKIP: nightly publish holds the deploy lock — next hour retries"
    exit 0
  fi
  SNAPSHOT_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/canli-publish.XXXXXX") || {
    echo "SKIP: could not create a temporary publication snapshot"
    exit 1
  }
  trap 'site_snapshot_cleanup "$SNAPSHOT_TEMP"; deploy_lock_release' EXIT
  if ! site_snapshot_create "$SNAPSHOT_TEMP"; then
    echo "SKIP: site source changed continuously while taking a publication snapshot"
    exit 1
  fi
  # Stamp the exact frozen source deployed below. If the working trees change after this point,
  # their new hash remains different and the next hourly run publishes the newer snapshot.
  NEW_HASH="$SITE_SNAPSHOT_HASH"

  FAIL=0
  deploy_prod() {
    local dir="$1" label="$2"; shift 2
    local url="" attempt a
    cd "$dir" || { echo "  [$label] cd failed: $dir"; FAIL=1; return 1; }
    # DIAGNOSABILITY (2026-08-06): the previous form piped vercel's output straight into
    # grep, so on failure the CLI's own error message was discarded and the log recorded
    # only "deploy attempt N failed". A 23h publication outage (2026-08-05 08:00Z onward)
    # was therefore undiagnosable after the fact — the site served stale data and the log
    # could not say why. Capture the raw output and echo its tail on every failed attempt.
    local raw=""
    for attempt in 1 2 3; do
      # BOUNDED (see scripts/lib/bounded.sh): this exact call hung for 28h and blocked trading.
      # --archive=tgz: upload one tarball instead of one request per file. On 2026-09-06 the
      # landing upload reached Vercel's 15,000-file cap (agent worktrees and dist/ rode along;
      # .vercelignore in the site repo now excludes them) and failed three times. The archive
      # form has no such cap, so a future growth in pages cannot repeat the failure mode.
      raw=$(run_bounded 600 vercel deploy --prod --yes --archive=tgz 2>&1)
      url=$(printf '%s\n' "$raw" | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
      # A URL IS NOT SUCCESS (2026-09-06). Vercel prints the deployment URL before it builds, and
      # a build that dies (that day: ENOENT on a file .vercelignore had hidden) still leaves a URL
      # in the output with status Error. This loop took the URL as proof and reported "prod: ..."
      # while the domain kept serving the previous build. So: the CLI must exit clean, the output
      # must not carry a build error, and the new deployment must answer 200 for the homepage.
      if [ -n "$url" ] && printf '%s\n' "$raw" | grep -qE "Error: Command .* exited|Build Failed|status.*Error"; then
        echo "  [$label] deployment $url reported a build error; not treating the URL as success"
        url=""
      fi
      if [ -n "$url" ]; then
        served=$(curl -s -o /dev/null --max-time 30 -w '%{http_code}' "$url/" 2>/dev/null || echo 000)
        if [ "$served" != "200" ]; then
          echo "  [$label] deployment $url answers HTTP $served for /; the build did not complete"
          url=""
        fi
      fi
      if [ -n "$url" ]; then echo "  [$label] prod: $url (attempt $attempt)"; break; fi
      echo "  [$label] deploy attempt $attempt failed; retrying in $((attempt*8))s"
      printf '%s\n' "$raw" | tail -20 | sed "s/^/    [$label:err] /"
      sleep $((attempt * 8))
    done
    [ -z "$url" ] && { echo "  [$label] DEPLOY FAILED after 3 attempts"; FAIL=1; return 1; }
    for a in "$@"; do
      run_bounded 120 vercel alias set "$url" "$a" >/dev/null 2>&1 && echo "  [$label] aliased $a" || echo "  [$label] alias $a skipped"
    done
    return 0
  }

  deploy_prod "$SITE_SNAPSHOT_ROOT/meridian" "landing" "ac-capital.vercel.app" "meridian-pearl-mu.vercel.app"
  LANDING_OK=$?
  deploy_prod "$SITE_SNAPSHOT_ROOT/meridian-app" "app" "ac-capital-app.vercel.app"

  # Tell the search engines, but ONLY if the landing deploy actually succeeded: submitting URLs
  # against a deploy that failed would advertise pages that may not be there. Loud on failure,
  # never fatal — see scripts/lib/indexnow.sh for why that is the right shape here and how a
  # persistent failure stops being silent.
  if [ "$LANDING_OK" = "0" ]; then
    indexnow_submit "$SITE_SNAPSHOT_ROOT/meridian"
  else
    echo "  [indexnow] skipped: the landing deploy failed, so there is nothing new to announce"
  fi
  indexnow_warn_if_stale

  if [ "$FAIL" = "0" ]; then
    echo "$NEW_HASH" > "$AF/$HASH_FILE"
    echo "=== hourly deploy OK $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  else
    echo "=== hourly deploy INCOMPLETE (will retry next hour) ==="
  fi
} >> "$AF/$LOG" 2>&1
