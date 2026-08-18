#!/bin/zsh
# EIA-930 forward vintage sweep. Scheduled by com.accapital.eia930.
#
# The credential lives OUTSIDE the repo at ~/.config/alphaforge/eia.env (chmod 600), the same
# convention as every other secret here, so it can never be committed by a `git add -A`.
#
# `set -a` exports everything the file defines; the capture script HARD-FAILS if EIA_API_KEY is
# absent rather than degrading to the public DEMO_KEY, because a silently rate-limited sweep
# leaves an invisible hole in an append-only record and those hours cannot be re-fetched later.
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/bin:/bin"
cd "$HOME/alphaforge"

if [[ ! -r "$HOME/.config/alphaforge/eia.env" ]]; then
  echo "FAIL: ~/.config/alphaforge/eia.env missing or unreadable; refusing to sweep blind" >&2
  exit 1
fi
set -a; . "$HOME/.config/alphaforge/eia.env"; set +a

# 7-day lookback: long enough to catch the revision window EIA actually uses, short enough that
# each sweep is ~1.4k rows. Revisions older than 7 days are caught by the weekly deep sweep below.
exec uv run python scripts/capture_eia930_vintages.py --mode sweep --days 7
