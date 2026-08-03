#!/bin/zsh
# Canli Capital - daily AlphaMax (equity) refresh.
#
# AlphaMax is the US-equity 12-1 momentum sleeve. Equity bars are daily (BULK day-agg flat
# files — one object per session covering every ticker), so this runs once per day (after the
# prior US session's file publishes) to:
#   1. ingest the latest equity sessions (catch-up, dedupe-safe, BULK only), and
#   2. regenerate AlphaMax's realized FORWARD curve via the tested walk-forward (momentum-only,
#      ~72s) into artifacts/walkforward/equity_live_fwd.
#
# It does NOT regenerate the published state or deploy: the hourly crypto tick
# (com.accapital.livetick) already re-runs paper_trading_state.py every hour (which reads this
# fresh forward curve + the live crypto NAV and re-combines the 3-algorithm state), and the daily
# publish deploys. So AlphaMax's forward + ALPHAC's combination stay current within the hour.

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v20.20.2/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/alphaforge" || exit 1
mkdir -p var/log var/locks
# Single-runner lock (atomic mkdir; no flock on macOS). Prevents an overlapping AlphaMax run from
# double-submitting to its Alpaca account — required now that live_cycle uses per-cycle order ids.
LOCK="var/locks/alphamax_tick.lock"
[ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ] && rmdir "$LOCK" 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "=== alphamax_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ'): another run holds $LOCK; exiting ===" >> var/log/alphamax_tick.log
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
WF_WATCHDOG_S=1200     # 20 min hard cap (a healthy momentum WF is ~1-2 min)
# Every network phase is now hard-bounded. The 2026-07-21 run proved an UNBOUNDED data phase can
# swallow the whole tick: it ground per-ticker vendor calls for 10.8 days, so the walk-forward and
# the broker step below it never ran and AlphaMax rebalanced ONCE in 11 days. A phase that overruns
# its cap is killed and the tick CONTINUES to the trading path — a stale bar is recoverable, a
# sleeve that never reaches its broker step is not.
DATA_WATCHDOG_S=900    # 15 min hard cap on the bar ingest (a healthy bulk catch-up is <60s)

{
  echo "=== alphamax_tick $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
  set -a; . "$HOME/.config/alphaforge/polygon.env" 2>/dev/null; set +a

  TOMORROW="$(date -u -v+1d +%F)"
  INGEST_START="$(date -u -v-12d +%F)"   # catch up the last ~2 weeks of sessions (dedupe-safe)
  WF_START="$(date -u -v-2y -v-2m +%F)"  # ~2.2yr: 365-session train + test legs through today

  echo "--- ingest equities ${INGEST_START} .. ${TOMORROW} (BULK bars only) ---"
  # DATA-PATH PINNING (2026-08-01 disclosure — a public correction entry accompanies this change).
  #
  # WHAT CHANGED (data path only): the live tick no longer runs the PER-TICKER vendor reference
  # (splits/dividends) pass. `ingest-equities` defaults to --corp-actions, which walks EVERY
  # instrument id present in the lake (17,541 keys as of today) and issues 2 REST calls each,
  # against a key that is now on the vendor's FREE tier (5 req/min) => ~35,000 calls, essentially
  # all of them HTTP 429. Measured cost: the tick launched 2026-07-21T05:00Z did not finish until
  # 2026-08-01T00:56Z — 10.8 days for ONE rebalance. Every daily launchd run in between either
  # exited on the lock or started a second grinder. THIS is why the equity sleeve looked dark.
  # `--no-corp-actions` retires that per-ticker dependency from the LIVE path. Bars keep coming
  # from the BULK day-agg path (one object per session, every ticker in it) which has no
  # per-ticker fan-out and therefore cannot rate-limit-wall.
  #
  # WHAT DID NOT CHANGE: alphas, cadence, horizon, K, universe size/hysteresis, costs, sleeve
  # weights, and the lake the live profile reads (data/lake). No strategy knob was retuned to
  # compensate for anything below. The traded universe is byte-for-byte the same set.
  #
  # OPEN VENDOR GAP (verified 2026-08-01, REPORTED not silently patched — do not paper over it):
  #   * bar feed: the bulk day-agg objects now return HTTP 403 on GetObject for EVERY date
  #     (ListObjects still succeeds, so the credential is valid — the entitlement is gone). The
  #     equity lake is therefore FROZEN at its 2026-07-15 session and the staleness banner below
  #     prints how old it is on every run.
  #   * corporate actions: the same vendor's UNFILTERED /v3/reference/splits + /dividends
  #     endpoints DO work on the free tier and return every ticker's actions in ~1 call per
  #     window — the correct bulk replacement for the retired per-ticker loop, but it needs a
  #     source-adapter change outside this file.
  # Until a bar feed is restored, this tick rebalances DAILY on a lake that stops at 2026-07-15;
  # that staleness is disclosed publicly rather than hidden behind a green log line.
  ( sleep "${DATA_WATCHDOG_S}"; pkill -TERM -f "data ingest-equities" 2>/dev/null; \
    sleep 10; pkill -KILL -f "data ingest-equities" 2>/dev/null ) &
  DWD=$!
  /usr/bin/caffeinate -s uv run af data ingest-equities \
    --start "${INGEST_START}" --until "${TOMORROW}" --profile equity --no-corp-actions \
    || echo "WARN: equity bar ingest returned non-zero (vendor/entitlement) — tick continues"
  kill "${DWD}" 2>/dev/null; wait "${DWD}" 2>/dev/null

  echo "--- equity lake staleness (informational; never blocks the trading path) ---"
  uv run python - <<'PY' || echo "WARN: staleness banner unavailable"
import datetime as dt
import sqlite3

KEY = "__polygon_flatfiles_day_watermark__"  # session watermark written by the bulk bar ingest
con = sqlite3.connect("file:var/ops.sqlite?mode=ro", uri=True)
row = con.execute(
    "SELECT watermark_ms FROM watermarks WHERE dataset='ohlcv_1d' AND instrument_id=?", (KEY,)
).fetchone()
con.close()
if row is None:
    print("LAKE STALENESS: no equity bar watermark found")
else:
    last = dt.datetime.fromtimestamp(row[0] / 1000, dt.UTC).date()
    age = (dt.datetime.now(dt.UTC).date() - last).days
    print(f"LAKE STALENESS: last equity session {last} ({age} calendar days old)")
    if age > 3:
        print("LAKE STALENESS: STALE — the book below is computed on bars that stop at that date")
PY

  echo "--- regenerate AlphaMax forward curve (momentum-only WF) ---"
  # CONSTRUCTION PINNING (2026-07-18 disclosure, defect 3 of the marking-fix campaign).
  # The command below runs the *equity profile defaults*: K=100/side (portfolio.rank_top_k)
  # on the top-2000 universe (universe.size), h=63, alpha eq_mom_252_21. The PUBLIC evidence
  # base cites the frozen k30_dn_63 artifact (K=30 on the older top-500 universe) — a
  # CONSTRUCTION DRIFT between the evidenced sleeve and the live tick. Per campaign protocol
  # this is resolved by DISCLOSURE + pinning, NOT by silently changing either side:
  #   * these parameters are PINNED as-is — do NOT edit K / universe size / alphas / cadence
  #     here without a signed public disclosure entry;
  #   * the drift itself is disclosed on the public record (the forward curve is labelled as
  #     the profile-default construction, not k30_dn_63).

  ( sleep "${WF_WATCHDOG_S}"; pkill -TERM -f "research walkforward" 2>/dev/null; \
    sleep 10; pkill -KILL -f "research walkforward" 2>/dev/null ) &
  WD=$!
  /usr/bin/caffeinate -s uv run af research walkforward --profile equity \
    --start "${WF_START}" --end "${TOMORROW}" \
    --train-days 365 --test-days 91 --alphas eq_mom_252_21 \
    --out artifacts/walkforward/equity_live_fwd
  kill "${WD}" 2>/dev/null; wait "${WD}" 2>/dev/null

  echo "--- submit AlphaMax deltas to Alpaca paper (GENUINE broker execution) ---"
  # Sizes the freshly-regenerated target book to AlphaMax's OWN Alpaca paper account and submits the
  # delta orders (cancel-stale first; whole-share shorts; last-trade pricing when the market is shut).
  # A broker/market hiccup must NOT break the tick, so failure is logged and the state still refreshes.
  # WATCHDOGGED 2026-08-03: this call reaches an external venue/vendor and had no bound.
  # An unbounded external call on the trading path is what let a hung deploy block ALL
  # trading for 28h. Hard-cap it; the tick must always reach its state refresh.
  ( sleep 1200; pkill -TERM -f "live_cycle.py --profile equity" 2>/dev/null; \
    sleep 15; pkill -KILL -f "live_cycle.py --profile equity" 2>/dev/null ) &
  _EQCYCWD=$!
  /usr/bin/caffeinate -s .venv/bin/python3 scripts/live_cycle.py --profile equity \
    || echo "WARN: live_cycle (equity) returned non-zero (broker/market issue) — state still refreshes"
  kill "$_EQCYCWD" 2>/dev/null; wait "$_EQCYCWD" 2>/dev/null

  echo "--- refresh published state now (the hourly tick also does this) ---"
  uv run python scripts/paper_trading_state.py
  echo "=== alphamax_tick done $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
} >> var/log/alphamax_tick.log 2>&1
