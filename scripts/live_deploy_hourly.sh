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
  NEW_HASH=$(find "$HOME/meridian" "$HOME/meridian-app" \
                \( -name node_modules -o -name dist -o -name .next -o -name .vercel \
                   -o -name .git -o -name .bak \) -prune -o \
                -type f -print0 2>/dev/null \
              | sort -z | xargs -0 shasum -a 256 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
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
  trap 'deploy_lock_release' EXIT

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
      raw=$(run_bounded 600 vercel deploy --prod --yes 2>&1)
      url=$(printf '%s\n' "$raw" | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
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

  deploy_prod "$HOME/meridian" "landing" "ac-capital.vercel.app" "meridian-pearl-mu.vercel.app"
  deploy_prod "$HOME/meridian-app" "app" "ac-capital-app.vercel.app"

  if [ "$FAIL" = "0" ]; then
    echo "$NEW_HASH" > "$AF/$HASH_FILE"
    echo "=== hourly deploy OK $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  else
    echo "=== hourly deploy INCOMPLETE (will retry next hour) ==="
  fi
} >> "$AF/$LOG" 2>&1
