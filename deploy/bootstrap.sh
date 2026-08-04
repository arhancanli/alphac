#!/usr/bin/env bash
# AlphaForge VPS bootstrap — idempotent. Installs uv + system deps + the venv and runs the
# test suite. Does NOT move secrets/data and does NOT enable any timer (see VPS_DEPLOY.md
# §2/§3/§5) so nothing trades before the box is verified.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. system deps (Ubuntu) =="
if command -v apt-get >/dev/null; then
  sudo apt-get update -y
  # build essentials for any source wheels; sqlite3 CLI (health_check + probes shell out to it);
  # git; curl; tzdata (UTC scheduling). No libomp needed unless the ML phase is built.
  sudo apt-get install -y build-essential git curl sqlite3 tzdata ca-certificates
fi

echo "== 2. uv (standalone, no system python needed) =="
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

echo "== 3. resolve the environment on THIS arch =="
# uv reads pyproject + uv.lock; on x86 it resolves x86 wheels (pyarrow/duckdb/clarabel all have
# them). If a wheel is missing for the arch, this is where it surfaces — fix before going live.
uv sync --frozen 2>/dev/null || uv sync

echo "== 4. sanity: imports + golden master + full unit suite =="
uv run python -c "import alphaforge; print('alphaforge imports OK')"
uv run pytest tests/integration/test_golden_master.py -q --no-cov -p no:cacheprovider
uv run pytest tests/unit -q --no-cov -p no:cacheprovider

cat <<'NEXT'

== bootstrap OK ==
Next (manual, deliberate — nothing trades yet):
  1. move secrets      -> VPS_DEPLOY.md §2
  2. move the record   -> VPS_DEPLOY.md §3  (crypto DB, ledger, SIGNED CHAIN + key)
  3. Sharadar re-point -> VPS_DEPLOY.md §4  (validate + disclose)
  4. install timers    -> VPS_DEPLOY.md §5  (enable ONE sleeve, verify, then the rest)
  5. dry-run each sleeve, verify the golden master + chain, THEN enable timers
  6. DISABLE the laptop's launchd jobs so two clocks never double-submit
NEXT
