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
  uv run python scripts/glassbox_export.py
  uv run python scripts/paper_trading_state.py
  # anchor the day's track record into the signed append-only transparency chain (no-op if
  # nothing changed since the last entry) — the tamper-evident proof the record isn't rewritten
  uv run python scripts/transparency_log.py
  # RETRACTED-CLAIM GATE. Runs after regeneration and BEFORE the deploy below, because a signed
  # retraction that only appends to the log is a footnote, not a retraction: AlphaTrend's DSR 0.83
  # was withdrawn on 2026-08-06 in entry [24] and was still on the homepage, still in the /progress
  # unfurl card, and still asserted in three glass-box artifacts six days later. The pipeline was
  # publishing the correction and the error in the same run. Non-fatal to TRADING (this whole block
  # is downstream of it) but it must be loud, and it must be able to fail.
  uv run python scripts/check_retracted_claims.py \
    || echo "WARN: RETRACTED CLAIM IS BEING PUBLISHED — see output above, fix before it spreads"
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
  /bin/zsh scripts/live_deploy_hourly.sh || echo "WARN: hourly web deploy failed (next hour retries)"
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
