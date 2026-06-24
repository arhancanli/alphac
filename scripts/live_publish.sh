#!/bin/zsh
# Canli Capital - daily PUBLISH of the live track record to the public sites.
#
# Regenerates the glass-box + paper-state JSONs from the realized NAV, then redeploys
# both Vercel sites so the public "Proven in the Open" track record + the app dashboard
# reflect the accrued live marks. Daily cadence (a track record needs no faster).
#
# Resilience: deploys to Vercel from this box hit intermittent TLS faults
# ("self-signed certificate in certificate chain", EPROTO, upload aborts). Each leg is
# retried up to 3 times, and a failure on one site never blocks the other or the job.
# `vercel deploy --prod` auto-promotes the project's production domain
# (canlicapital.com / app.canlicapital.com), so the explicit legacy *.vercel.app aliases
# are best-effort only.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log

FAIL=0

# deploy_prod <project_dir> <label> [legacy_alias ...]
# Retries the production deploy up to 3x; echoes the resulting URL; best-effort aliases.
deploy_prod() {
  local dir="$1" label="$2"; shift 2
  local url="" attempt
  cd "$dir" || { echo "  [$label] cd failed: $dir"; FAIL=1; return 1; }
  for attempt in 1 2 3; do
    url=$(vercel deploy --prod --yes 2>&1 | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
    if [ -n "$url" ]; then
      echo "  [$label] prod: $url (attempt $attempt)"
      break
    fi
    echo "  [$label] deploy attempt $attempt failed; retrying in $((attempt*8))s"
    sleep $((attempt * 8))
  done
  if [ -z "$url" ]; then
    echo "  [$label] DEPLOY FAILED after 3 attempts"
    FAIL=1
    return 1
  fi
  # best-effort legacy aliases (the prod deploy already promoted the real domain)
  local a
  for a in "$@"; do
    vercel alias set "$url" "$a" >/dev/null 2>&1 && echo "  [$label] aliased $a" || echo "  [$label] alias $a skipped"
  done
  return 0
}

{
  echo "=== live_publish $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

  # 1) regenerate the published artifacts from the realized NAV
  uv run python scripts/glassbox_export.py || { echo "glassbox_export FAILED"; FAIL=1; }
  uv run python scripts/paper_trading_state.py || { echo "paper_trading_state FAILED"; FAIL=1; }

  # 2) publish both sites (each leg independent + retried)
  echo "--- deploy landing ---"
  deploy_prod "$HOME/meridian" landing ac-capital.vercel.app meridian-pearl-mu.vercel.app

  echo "--- deploy app ---"
  deploy_prod "$HOME/meridian-app" app ac-capital-app.vercel.app

  if [ "$FAIL" -eq 0 ]; then
    echo "=== publish OK $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  else
    echo "=== publish COMPLETED WITH ERRORS $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  fi
} >> var/log/live_publish.log 2>&1

exit $FAIL
