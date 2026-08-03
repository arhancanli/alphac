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

  # change gate: hash the actually-served data artifacts
  NEW_HASH=$(cat "$HOME/meridian/public/paper-state.json" \
                 "$HOME/meridian/public/glassbox/transparency_log.json" 2>/dev/null | shasum -a 256 | cut -d' ' -f1)
  OLD_HASH=$(cat "$HASH_FILE" 2>/dev/null)
  if [ -n "$NEW_HASH" ] && [ "$NEW_HASH" = "$OLD_HASH" ]; then
    echo "no data change since last deploy — skipping"
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
    for attempt in 1 2 3; do
      # BOUNDED (see scripts/lib/bounded.sh): this exact call hung for 28h and blocked trading.
      url=$(run_bounded 600 vercel deploy --prod --yes 2>&1 | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
      if [ -n "$url" ]; then echo "  [$label] prod: $url (attempt $attempt)"; break; fi
      echo "  [$label] deploy attempt $attempt failed; retrying in $((attempt*8))s"
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
