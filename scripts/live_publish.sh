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
. "$HOME/alphaforge/scripts/lib/bounded.sh"

FAIL=0

# deploy_prod <project_dir> <label> [legacy_alias ...]
# Retries the production deploy up to 3x; echoes the resulting URL; best-effort aliases.
deploy_prod() {
  local dir="$1" label="$2"; shift 2
  local url="" attempt
  cd "$dir" || { echo "  [$label] cd failed: $dir"; FAIL=1; return 1; }
  # WHY THE OUTPUT IS TEE'd (2026-08-10). This previously piped the deploy straight into
  # `grep -oE 'https://...'`, which matches ONLY a success URL and therefore DISCARDED the reason
  # for every failure. The publish job failed 10 times between 2026-07-10 and 2026-08-09 and the
  # log recorded nothing but "attempt N failed" — a failure that cannot be read is a failure that
  # cannot be fixed, which is the same defect class as a check that cannot fail. The transcript now
  # survives in var/log/deploy_<label>.out and its tail is echoed inline on the final failure.
  local out="$HOME/alphaforge/var/log/deploy_${label}.out"
  for attempt in 1 2 3; do
    # BOUNDED (see scripts/lib/bounded.sh): unbounded, this is a 28h-outage-class hang.
    url=$(run_bounded 600 vercel deploy --prod --yes 2>&1 | tee "$out" | grep -oE "https://[a-z0-9-]+\.vercel\.app" | tail -1)
    if [ -n "$url" ]; then
      echo "  [$label] prod: $url (attempt $attempt)"
      break
    fi
    echo "  [$label] deploy attempt $attempt failed; retrying in $((attempt*8))s"
    sleep $((attempt * 8))
  done
  if [ -z "$url" ]; then
    echo "  [$label] DEPLOY FAILED after 3 attempts — vercel said:"
    sed 's/^/      | /' "$out" 2>/dev/null | tail -25 || echo "      | (no output captured)"
    FAIL=1
    return 1
  fi
  # best-effort legacy aliases (the prod deploy already promoted the real domain)
  local a
  for a in "$@"; do
    run_bounded 120 vercel alias set "$url" "$a" >/dev/null 2>&1 && echo "  [$label] aliased $a" || echo "  [$label] alias $a skipped"
  done
  return 0
}

{
  echo "=== live_publish $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

  # 0) bound var/log BEFORE the ceremony touches anything. There was no rotation at all until
  # 2026-08-20 and var/log had reached 284MB. Deliberately first and deliberately incapable of
  # failing the job: a disk-hygiene chore must never be the reason a publish did not happen.
  "$HOME/alphaforge/scripts/rotate_logs.sh" || echo "  log rotation skipped (non-fatal)"

  # 1) regenerate the published artifacts from the realized NAV
  # ORDER IS LOAD-BEARING (fixed 2026-08-19). paper_trading_state.py WRITES data/paper/state.json;
  # glassbox_export.py READS it. Both jobs used to call glassbox FIRST, so every glass-box artifact
  # derived from that state -- track_record.json above all, the site's headline "Proven in the
  # Open" record -- was rendered from the PREVIOUS cycle. When prose changed, the two files the
  # dashboard shows side by side could not agree within a run: the AlphaVintage correction landed
  # in paper-state.json and track_record.json kept asserting the withdrawn 0.3403 for another
  # cycle. The dependency is file-mediated and therefore invisible in the call order; pinned by
  # tests/unit/test_publish_pipeline_order.py.
  uv run python scripts/paper_trading_state.py || { echo "paper_trading_state FAILED"; FAIL=1; }
  uv run python scripts/glassbox_export.py || { echo "glassbox_export FAILED"; FAIL=1; }
  # keep capacity.json fresh + hash-consistent (it grounds the commitment AND the reproducibility kit;
  # leaving it out of the pipeline is what let it go stale once). Soft-fail: it is near-static.
  uv run python scripts/capacity_export.py || echo "capacity_export soft-failed — non-fatal"
  # signed public capacity commitment (grounded in capacity.json). Soft-fail: it is near-static.
  uv run python scripts/capacity_commitment.py || echo "capacity_commitment soft-failed — non-fatal"
  # signed founder skin-in-the-game disclosure. Soft-fail: it is near-static.
  uv run python scripts/founder_commitment.py || echo "founder_commitment soft-failed — non-fatal"
  # research.json is a separate comprehensive contract. It once stayed frozen for nine days while
  # paper-state moved from two to four sleeves because this pipeline never invoked its exporter.
  # Generate it after paper-state so composition, weights, tilt and evidence timestamps are from
  # the same canonical state that the public dashboard will serve.
  # See live_tick.sh: this audit is fail-closed evidence that no publish job used to run, so the
  # bundle carried a hand-produced verdict. Non-fatal on purpose — a FAIL_CLOSED is published.
  uv run python scripts/audit_sleeve_family_lineage.py >/dev/null \
    || echo "NOTE: sleeve-family lineage audit is FAIL_CLOSED — publishing that verdict as measured"
  # REBUILD the lint-debt contract before research_export COPIES it to both sites.
  # Found 2026-08-20, and it is the same defect the research.json note above describes, recurring
  # on a different artifact: scripts/export_lint_debt_contract.py was invoked from exactly one
  # place, .github/workflows/ci.yml, where its output is checked for non-emptiness and then
  # thrown away with the runner. NOTHING here rebuilt it. research_export.py line ~1269 simply
  # copies artifacts/engineering/lint_debt_contract.json into public/glassbox on both hosts, so
  # the site published "PRODUCTION_AND_TESTS_CLEAN_HISTORICAL_SCRIPTS_DEBT" bound to
  # source_sha256 values that were only as fresh as the last time a human ran the exporter by
  # hand. The claim could not go stale loudly: it would keep publishing clean while the code it
  # names drifted underneath it, because no publish path ever re-derived it.
  # tests/unit/test_lint_debt_contract.py pins persisted == freshly built, and it does catch this
  # — but it is marked workspace_evidence, so CI skips it, and it lives in the full local suite
  # that had been timing out for eight days. A guard nothing can run is a guard that does not
  # exist. Rebuilding it here is what makes the published claim true by construction.
  # Soft-fail deliberately: if ruff or the exporter is broken, that is an engineering-tooling
  # problem and it must not stop the track record from publishing. It is loud instead.
  uv run python scripts/export_lint_debt_contract.py >/dev/null \
    || echo "WARNING: lint debt contract NOT rebuilt — publishing one bound to older source hashes"
  uv run python scripts/research_export.py || { echo "research_export FAILED"; FAIL=1; }
  # sign the day's record into the tamper-evident transparency chain before deploying it
  uv run python scripts/transparency_log.py || { echo "transparency_log FAILED"; FAIL=1; }
  # externally anchor the signed chain head into Bitcoin via OpenTimestamps (un-forgeable timestamp).
  # Soft-fail: a slow calendar / no network must never block the publish — the head anchors next run.
  # WATCHDOGGED 2026-08-03: the OpenTimestamps calendars are third-party servers we do not
  # control, and the library has no timeout of its own. Soft-failing on a hang is not enough —
  # it has to be ABLE to fail. Same lesson as the 28h hung deploy: bound every external call.
  ( sleep 300; pkill -TERM -f "anchor_transparency.py" 2>/dev/null; \
    sleep 15; pkill -KILL -f "anchor_transparency.py" 2>/dev/null ) &
  _AWD=$!
  uv run python scripts/anchor_transparency.py || echo "anchor_transparency soft-failed (calendars/network) — non-fatal"
  kill "$_AWD" 2>/dev/null; wait "$_AWD" 2>/dev/null
  # publish the downloadable verifier, then SELF-CHECK that our own published record reproduces
  # (content hashes + signatures + golden master) before we ship it. A failure here means we'd be
  # publishing a record that doesn't reproduce -- warn loudly, do not silently deploy a broken claim.
  for d in "$HOME/meridian/public/glassbox" "$HOME/meridian-app/public/glassbox"; do
    cp scripts/reproduce.py "$d/reproduce.py" 2>/dev/null
  done
  PUBLISHABLE=1
  uv run python scripts/reproduce.py || {
    echo "BLOCKED: reproduce.py self-check FAILED — the published record does not reproduce"
    PUBLISHABLE=0
  }

  # RETRACTED-CLAIM GATE. This job did not run it at all until 2026-08-19, which is how the hole
  # stayed open: the hourly tick runs the gate but never regenerates research.json, and THIS job
  # regenerates research.json but never ran the gate. AlphaVintage's withdrawn net Sharpe 0.3403
  # therefore lived in the one artifact that no run checked. Split coverage reads as coverage
  # right up until you ask which job checks which file.
  uv run python scripts/check_retracted_claims.py || {
    echo "BLOCKED: a RETRACTED CLAIM is in the regenerated bundle"
    PUBLISHABLE=0
  }

  # NEITHER FAILURE IS A WARNING ANY MORE. Both were, and both were ignored by the deploy that
  # followed them in the same run: the 2026-08-18 publish logged "1 CHECK(S) FAILED — the
  # published record does not reproduce" and then shipped, so the verifier we advertise on the
  # site returned a FAIL to anyone who downloaded it. A record whose only asset is that it checks
  # out cannot ship a bundle that does not check out. The artifacts above are already written and
  # signed; the next run publishes them once the cause is fixed.
  if [ "$PUBLISHABLE" -eq 0 ]; then
    echo "=== publish HALTED BEFORE DEPLOY $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
    echo "    Artifacts are regenerated and signed. The SITE IS UNCHANGED and will go stale."
    echo "    Fix the cause; do not weaken the check."
    exit 1
  fi

  # 2) publish both sites (each leg independent + retried)
  # shared lock with the hourly deploy (schedules overlap: hourly :05, this job 02:10). An hourly
  # deploy takes a couple of minutes, so wait it out rather than skipping the nightly ceremony.
  # If it is STILL held after 10 min, skip the deploy legs only — the artifacts above are already
  # written and signed, and the next hourly deploy publishes exactly this data.
  if deploy_lock_wait 600; then
    trap 'deploy_lock_release' EXIT
  else
    echo "  SKIP DEPLOY: hourly deploy still holds the lock after 10m — it publishes this same data"
    if [ "$FAIL" -eq 0 ]; then
      echo "=== publish OK (artifacts signed; deploy deferred to hourly) $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
    else
      echo "=== publish COMPLETED WITH ERRORS $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
    fi
    exit $FAIL
  fi
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
