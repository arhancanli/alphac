#!/bin/zsh
# Canli Capital - hourly live PAPER cycle (the running track record).
#
# Runs one idempotent paper cycle for the just-closed bar (scheduled a few minutes
# past the hour by launchd so the bar has closed), then regenerates the published-state
# JSONs from the REALIZED marks in trading.sqlite. Only ACCRUES + regenerates locally;
# publishing to the live sites is the separate daily live_publish.sh step.
#
# HARD WATCHDOG: a hung network fetch must never block forever. If the cycle overruns
# WATCHDOG_S, it is killed and the next hour retries (every cycle is idempotent +
# crash-safe by the Phase-8 gates, so an abandoned cycle costs nothing but a gap).

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks
# Single-runner lock (mkdir is atomic on macOS; no flock here). Prevents an overlapping run from
# double-submitting — required now that live_cycle uses per-cycle order ids. A SIGKILL'd run can't
# clear its lock, so steal one older than the watchdog window.
LOCK="var/locks/live_tick.lock"
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +60 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== live_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" >> var/log/live_tick.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
WATCHDOG_S=2400   # 40 min cap: hourly cache-hit cycles are ~3 min; the once-daily
                  # blend-weight refresh (cache miss) is ~25 min -- 40 min bounds a
                  # hang while clearing the daily refresh with comfortable margin.

{
  echo "=== live_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  # ============================================================================================
  # THE CRYPTO LOOP NO LONGER RUNS HERE. It runs on the Frankfurt VPS (201.79.12.40), hourly at
  # :10, and this step PULLS its track record instead of producing one.
  #
  # WHY IT MOVED (measured 2026-08-10): Binance is unreachable from this Mac — HTTP 000, instant
  # connection reset, and Bybit/OKX/Kraken fail identically, so it is a network-layer block on
  # exchange endpoints in this location rather than anything Binance decided. The sleeve's lifetime
  # uptime was 27% because reachability depended on which country the laptop was in. The US droplet
  # could never be the fix either: Binance geo-blocks it with HTTP 451. Frankfurt answers 200.
  #
  # *** EXACTLY ONE HOST MAY RUN THIS LOOP. *** Two writers to trading_crypto_perp.sqlite would
  # produce two divergent track records for the same sleeve and there would be no way to say which
  # was real — the same class of integrity failure as two writers on the transparency chain. The
  # `af paper run --once` call that used to live on this line is therefore DELETED, not commented
  # out and not conditionalised, so it cannot be revived by accident. If the crypto loop must ever
  # come back here, stop the VPS timer FIRST:
  #     ssh root@201.79.12.40 'systemctl disable --now af-trade.timer'
  #
  # WHAT STAYS HERE: everything below — the glass-box export, the published state, and the signed
  # transparency chain. Those keep exactly one writer, and it is this machine.
  #
  # ORDERING: this pull must precede the state regeneration below, because glassbox_export.py and
  # paper_trading_state.py read the crypto track record it fetches. The pull is guarded — it only
  # copies when the VPS database is strictly NEWER than the local one, so a VPS that is down, stale
  # or mid-write can never roll this sleeve's history backwards.
  echo "--- pull crypto track record + lake from the VPS (loop runs there now) ---"
  ( sleep 900; pkill -f "vps_crypto_sync.sh" 2>/dev/null ) &
  WD=$!
  ./scripts/vps_crypto_sync.sh 201.79.12.40 \
    || echo "WARN: VPS sync returned non-zero — state below is regenerated from the LAST GOOD pull"
  kill "$WD" 2>/dev/null; wait "$WD" 2>/dev/null
  echo "--- regenerate published state from realized NAV ---"
  # GET-ONLY broker refresh. Closed-market days must remain order-free, but Alpaca finalizes the
  # prior session's portfolio-history mark after the pre-open trading tick. Without this separate
  # read path, Saturday's calendar skip also skipped the only chance to publish Friday's close.
  uv run python scripts/export_alpaca_broker_reconciliation.py \
    || echo "WARN: Alpaca broker reconciliation FAIL_CLOSED — local curves were preserved"
  # ORDER IS LOAD-BEARING (fixed 2026-08-19). paper_trading_state.py WRITES data/paper/state.json;
  # glassbox_export.py READS it. Both jobs used to call glassbox FIRST, so every glass-box artifact
  # derived from that state -- track_record.json above all, the site's headline "Proven in the
  # Open" record -- was rendered from the PREVIOUS cycle. When prose changed, the two files the
  # dashboard shows side by side could not agree within a run: the AlphaVintage correction landed
  # in paper-state.json and track_record.json kept asserting the withdrawn 0.3403 for another
  # cycle. The dependency is file-mediated and therefore invisible in the call order; pinned by
  # tests/unit/test_publish_pipeline_order.py.
  uv run python scripts/paper_trading_state.py
  uv run python scripts/glassbox_export.py
  # research.json IS part of the served bundle and was NOT regenerated here until 2026-08-19.
  # It is owned by the nightly ceremony, which last fired on 2026-08-18 -- the 02:10 schedule
  # lands while this laptop is asleep -- so research.json went a full day stale while paper-state
  # refreshed hourly, and it was still asserting AlphaVintage's withdrawn 0.3403 after the
  # correction had already shipped in the file next to it.
  #
  # That is also what made the retracted-claim gate below unable to see the problem: THIS job runs
  # the gate but did not regenerate research.json, and the NIGHTLY job regenerated research.json
  # but did not run the gate. Two jobs, each covering what the other checked. Split coverage reads
  # as coverage right up until you ask which job checks which file. It costs ~1s.
  # The family-lineage audit is FAIL-CLOSED evidence and was never run by any publish job --
  # research_export.py merely COPIES artifacts/discovery/sleeve_family_lineage_audit.json into the
  # bundle. So the site published whatever verdict a human last produced by hand. On 2026-08-18 a
  # new evidence reference made the audit FAIL_CLOSED; the published copy was from 2026-08-16 and
  # said PASS, so canlicapital.com asserted a passing lineage audit for three days while the audit
  # itself failed. An artifact nothing regenerates is a screenshot, not a check.
  #
  # Deliberately NON-fatal: a FAIL_CLOSED verdict is meant to be PUBLISHED, not suppressed. The
  # artifact carries its own decision, so shipping it is the honest outcome and hiding it is not.
  # It must be loud, and it must be current.
  uv run python scripts/audit_sleeve_family_lineage.py >/dev/null \
    || echo "NOTE: sleeve-family lineage audit is FAIL_CLOSED — publishing that verdict as measured"
  # SAME CLASS AS THE PARAGRAPH ABOVE, different artifact — found 2026-08-20.
  # research_export.py also merely COPIES artifacts/engineering/lint_debt_contract.json into the
  # bundle, and scripts/export_lint_debt_contract.py was invoked from exactly one place in the
  # whole system: .github/workflows/ci.yml, where the output is checked for non-emptiness and
  # then thrown away with the runner. No publish path rebuilt it. So the site published
  # "PRODUCTION_AND_TESTS_CLEAN_HISTORICAL_SCRIPTS_DEBT" bound to source_sha256 values that were
  # only ever as fresh as the last hand-run of the exporter — a clean-code claim that could not
  # go stale loudly, because nothing re-derived it from the code it names.
  # An artifact nothing regenerates is a screenshot, not a check.
  # Soft-fail: broken lint tooling is an engineering problem and must not stop the track record
  # from publishing. Loud instead, and named precisely enough to act on.
  uv run python scripts/audit_record_continuity.py >/dev/null \
    || echo "WARN: record-continuity audit failed — the published report will be stale"
  uv run python scripts/export_lint_debt_contract.py >/dev/null \
    || echo "WARNING: lint debt contract NOT rebuilt — publishing one bound to older source hashes"
  uv run python scripts/build_identity_trial_packets.py
  uv run python scripts/build_trial_packet_manifest.py
  uv run python scripts/seal_legacy_research_epoch.py
  # Bind next-sleeve selection to the current unopened review packet before research_export copies
  # the receipt. This does not open labels, machine predictions, prices, or returns.
  uv run python scripts/seal_next_sleeve_selection.py
  # Publish the exact canonical payload into the signed chain BEFORE evaluating maturity. The
  # evaluator requires the chain head to equal this cycle's paper state byte-for-byte in canonical
  # form; reversing these calls would certify the previous cycle's payload.
  uv run python scripts/transparency_log.py
  uv run python scripts/export_crypto_position_attribution.py
  uv run python scripts/verify_crypto_position_attribution_rollout.py
  uv run python scripts/analyze_current_book_drawdown.py
  uv run python scripts/analyze_current_book_diversification.py
  uv run python scripts/seal_forward_drawdown_evidence.py
  uv run python scripts/evaluate_forward_evidence_maturity.py
  uv run python scripts/sync_readme_forward_evidence.py
  uv run python scripts/analyze_forward_sleeve_contribution.py
  uv run python scripts/audit_crypto_lab_carry_crash.py
  uv run python scripts/research_export.py
  # RETRACTED-CLAIM GATE. Runs after regeneration and BEFORE the deploy below, because a signed
  # retraction that only appends to the log is a footnote, not a retraction: AlphaTrend's DSR 0.83
  # was withdrawn on 2026-08-06 in entry [24] and was still on the homepage, still in the /progress
  # unfurl card, and still asserted in three glass-box artifacts six days later. The pipeline was
  # publishing the correction and the error in the same run. Non-fatal to TRADING (this whole block
  # is downstream of it) but it must be loud, and it must be able to fail.
  #
  # IT NOW BLOCKS THE DEPLOY (2026-08-19). For its whole life this gate printed a WARN and the
  # deploy ran anyway: `grep -c` over var/log/live_tick.log counts 41 ticks that announced
  # "RETRACTED CLAIM IS BEING PUBLISHED" and published it 41 times. That is the failure this repo
  # keeps rediscovering under different names -- a check that cannot stop the thing it checks is
  # not a gate, it is a log line. AlphaVintage's withdrawn Sharpe reached the live site through
  # exactly this hole and stayed for three days.
  #
  # WHAT BLOCKING ACTUALLY BUYS, stated honestly: skipping the deploy does NOT remove a bad claim
  # that is already live -- the site simply keeps serving the previous bundle. What it buys is
  # that the failure stops being invisible. The published `generated_at` freezes, which is a
  # symptom somebody notices, instead of a warning in a log nobody reads. Trading is untouched:
  # this whole block is downstream of the trading loop and the deploy is cosmetic.
  _BLOCKED_BY=""
  if uv run python scripts/check_retracted_claims.py; then
    _PUBLISHABLE=1
  else
    _PUBLISHABLE=0
    _BLOCKED_BY="the retracted-claim gate"
    echo "BLOCKED: A RETRACTED CLAIM IS IN THE REGENERATED BUNDLE — SKIPPING THE WEB DEPLOY."
    echo "         The site will serve the PREVIOUS bundle and its generated_at will go stale"
    echo "         until this is fixed. Fix the source prose; do NOT weaken the blocklist."
  fi
  # LIVE-CHANGE CEREMONY (added 2026-08-21). The same blocking shape, for a different asset.
  #
  # On 2026-08-21 a BlendStrategy default was changed. No call site passes that argument, the
  # walk-forwards are regenerated by THIS tick, and live_cycle.py submits the last leg's weights
  # to the broker — so it would have re-sized two broker-executed sleeves on the next cycle, and
  # nothing here would have noticed. There were 85 evidence checks around admitting a sleeve and
  # none around re-sizing the entire book.
  #
  # WHAT THIS BUYS, honestly: by the time it runs, an undeclared change has already traded. It
  # cannot prevent contamination of the forward record — tests/unit/test_live_change_is_declared.py
  # is the defense that does, by failing before the change is ever committed. What it buys is that
  # the contamination stops being invisible: the published bundle freezes and generated_at goes
  # stale, which somebody notices. It deliberately does NOT halt trading, because a gap in the
  # forward record is the same harm, and the record's whole value is its continuity.
  if uv run python scripts/check_live_change_declared.py; then
    :
  else
    _PUBLISHABLE=0
    _BLOCKED_BY="${_BLOCKED_BY:+${_BLOCKED_BY} and }the live-change gate"
    echo "BLOCKED: THE LIVE TRADING CONFIGURATION IS UNDECLARED — SKIPPING THE WEB DEPLOY."
    echo "         Declare it in config/live_change_contract.json and mark the forward record."
  fi
  # HOURLY web refresh: redeploy the public sites when the served data changed (change-gated,
  # freshness-guarded; see live_deploy_hourly.sh). The web app now tracks the live book hourly.
  # WATCHDOGGED (added 2026-08-03 after a real incident): `vercel deploy` has no timeout of its
  # own, so a hung deploy held this tick's single-runner lock for 28 HOURS and blocked ALL trading
  # — a purely cosmetic web publish stopping the critical path, the same failure class as the
  # corp-actions ingest that once buried the equity tick for 10.8 days. The web can always catch up
  # next hour; trading cannot. Hard-bound it and treat any failure as non-fatal.
  # (This no longer broad-kills `vercel deploy`: that would also kill the nightly publish,
  #  which overlaps this job by schedule. The deploy is now bounded by PID inside the
  #  script itself and the two jobs share a lock — see scripts/lib/bounded.sh.)
  ( sleep 600; pkill -TERM -f "live_deploy_hourly" 2>/dev/null; \
    sleep 15; pkill -KILL -f "live_deploy_hourly" 2>/dev/null ) &
  _DWD=$!
  if [ "$_PUBLISHABLE" -eq 1 ]; then
    /bin/zsh scripts/live_deploy_hourly.sh || echo "WARN: hourly web deploy failed (next hour retries)"
  else
    echo "  (deploy skipped by ${_BLOCKED_BY:-a publish gate})"
  fi
  kill "$_DWD" 2>/dev/null; wait "$_DWD" 2>/dev/null
  # MAKER SHADOW — DELIBERATELY NOT RUN HERE ANY MORE. Read this before re-enabling it.
  #
  # The measurement itself still matters (it is how the modelled +0.04-0.09 Sharpe maker/post-only
  # edge gets an HONEST forward test instead of being booked on assumption). It now runs ON THE VPS,
  # inside af-trade, and /opt/alphaforge/var/maker_shadow.sqlite is the SOLE authoritative record.
  #
  # WHY THE MAC MUST NOT ALSO RECORD. Both hosts wrote to a file of the same name, so the experiment
  # silently ran twice against two different populations. On 2026-08-12 the VPS held 306 matured
  # quotes at a 93.1% fill and +5.21bps, while the Mac held 18 at 83.3% and +4.47bps — same schema,
  # same experiment name, materially different answer. A promote decision that happened to read the
  # local file would have read the wrong one.
  #
  # And the Mac's copy was not merely smaller, it was BIASED. This host reaches Binance only
  # intermittently (the tick log is full of SSL WRONG_VERSION_NUMBER against fapi.binance.com), so
  # it sampled top-of-book precisely in the windows when its own connection happened to be working
  # — a fill rate conditioned on our network, not on the venue's queue. The VPS sits in Frankfurt
  # and reaches the venue continuously, which is also where the sleeve actually trades from, so its
  # fills are the only ones that describe orders we could really have placed.
  #
  # The local var/maker_shadow.sqlite is now a read-only MIRROR pulled by vps_crypto_sync.sh.
  echo "=== tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/live_tick.log 2>&1
