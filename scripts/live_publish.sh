#!/bin/zsh
# AC Capital - daily PUBLISH of the live track record to the public sites.
#
# Regenerates the glass-box + paper-state JSONs from the realized NAV, then redeploys
# both Vercel sites so the public "Proven in the Open" track record + the app dashboard
# reflect the accrued live marks. Daily cadence (a track record needs no faster).

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log

{
  echo "=== live_publish $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  uv run python scripts/glassbox_export.py
  uv run python scripts/paper_trading_state.py

  echo "--- deploy landing ---"
  cd "$HOME/meridian" || exit 1
  LP=$(vercel deploy --prod --yes 2>&1 | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
  echo "landing prod: $LP"
  [ -n "$LP" ] && vercel alias set "$LP" ac-capital.vercel.app
  [ -n "$LP" ] && vercel alias set "$LP" meridian-pearl-mu.vercel.app

  echo "--- deploy app ---"
  cd "$HOME/meridian-app" || exit 1
  AP=$(vercel deploy --prod --yes 2>&1 | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
  echo "app prod: $AP"
  [ -n "$AP" ] && vercel alias set "$AP" ac-capital-app.vercel.app

  echo "=== publish done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/live_publish.log 2>&1
