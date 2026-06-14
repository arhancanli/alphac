# AlphaForge -- 30-Day PAPER Soak Runbook (Phase 8)

This is the operator's guide for running AlphaForge UNATTENDED for a 30-day PAPER
soak. The soak itself is owner-operated calendar time; this runbook + the Phase-8
machinery (backups, restore drill, clock sanity, slippage report, launchd
auto-restart, log rotation) is what makes that calendar time SAFE.

PAPER money only. Real trading is a NotArmed Phase-8+ flip
(`af paper arm` prints the contract and refuses); nothing in this runbook can
place a real order.

---

## The Phase-8 gate (what "soak passed" means)

From `docs/design/buildabilityCritique.md` section 4 (Phase-8 gate). The soak
PASSES only when ALL of:

1. **>= 99% of expected cycles executed** over the 30 days
   (`af paper status` N/M accounting -- see below). On a laptop that naps this is
   typically UNREACHABLE; that is the single biggest reason to run the soak on a
   VPS, not a MacBook.
2. **The ledger rebuilds from backups alone on a clean machine**
   (`af ops restore-drill`, run WEEKLY -- the gate command, exits 1 on failure).
3. **The modeled-vs-realized slippage report is reviewed**
   (`af ops slippage`). This is the genuine validation signal from
   `docs/design/leakageCritique.md` finding 8: paper fills WALK the real order
   book, so walked-vs-modeled slippage compares the cost model against reality,
   not against itself. A model that is systematically optimistic shows up here
   BEFORE any real money is at risk.

Demonstrate the missed-cycle and reconciliation alerts end-to-end at least once
during the soak (engage and clear the KILL sentinel; confirm the WARN/CRITICAL
arrives on Telegram or, token-less, in `var/log/alphaforge.jsonl`).

---

## 0. Honest caveats -- read before you start

- **A MacBook with the lid CLOSED does not run the loop.** `caffeinate -i`
  prevents IDLE sleep on AC with the lid OPEN; clamshell mode (lid closed) naps
  the machine unless an external display AND power are attached. A napped laptop
  misses cycles -- which is SAFE (missed cycles are skipped + counted, never
  back-filled) but will fail the >= 99% gate.
- **The real soak target is a small always-on arm64 VPS** (e.g. a Hetzner
  CAX-class box, ~EUR 4/mo) running the identical wheels. Laptop = development +
  short rehearsal; VPS = the 30-day soak. On the VPS, replace the macOS launchd
  agent with a systemd unit running the same `caffeinate`-less command, and
  enable `chrony` for clock discipline.
- **The repo MUST NOT live in an iCloud-synced folder.** iCloud sync corrupts the
  live SQLite WAL files. The home root (`~/alphaforge`) is safe by default;
  `~/Desktop` and `~/Documents` are iCloud-synced -- never put the repo there.

---

## 1. Pre-flight (once, before the soak)

```sh
cd ~/alphaforge
export PATH="$HOME/.local/bin:$PATH"

# 1a. Confirm the repo is NOT under an iCloud-synced path.
#     Expect NO match (an empty result is good).
pwd | grep -E '/(Desktop|Documents|Mobile Documents)/' \
  && echo "STOP: repo is in an iCloud-synced folder -- move it to ~/alphaforge" \
  || echo "ok: repo not in iCloud"

# 1b. Sanity: the CLI resolves and the venv is built.
uv run af --help

# 1c. Confirm clock discipline NOW (before trusting the per-cycle check).
#     macOS NTP is on by default; on a VPS run `sudo chronyc tracking` instead.
uv run af ops clock      # prints local-vs-exchange skew; ok iff |skew| <= max_skew
```

`af ops clock` compares the local wall clock against the exchange server time and
reports the signed skew. The live loop ALSO performs this check once per cycle (it
WARN-alerts + counts a breach but never halts -- see section 5); running it by
hand first confirms the baseline is clean.

---

## 2. Backfill / update the data lake

The loop drives incremental ingest itself (one timer), but start from a warm lake
so the first cycles are not all stale-skips.

```sh
# Backfill history for the universe (idempotent; safe to re-run).
uv run af data backfill --profile paper

# A quick forward update to pull the most recent closed bars.
uv run af data update --profile paper
```

The lake is re-derivable from the exchange, so it is NOT what you back up
(section 4 backs up the NON-derivable trading state instead).

---

## 3. Run the loop

### 3a. Foreground rehearsal (a few cycles, watch it work)

```sh
# One cycle for the current bar, then exit (soak/cron/crash-test mode):
uv run af paper run --once --profile paper

# Or run the single-timer 24/7 loop in the foreground under caffeinate
# (ctrl-c or `touch var/KILL` to stop):
caffeinate -i uv run af paper run --forever --profile paper
```

### 3b. Unattended via launchd (the laptop auto-restart)

The LaunchAgent keeps the loop alive across logout and crash, wrapped in
`caffeinate -i`, with output to `var/log`. Fill the two placeholders from the
template and load it:

```sh
mkdir -p var/log
sed -e "s|{{REPO_DIR}}|$PWD|g" -e "s|{{UV_BIN}}|$(command -v uv)|g" \
    deploy/com.alphaforge.paper.plist.template \
    > ~/Library/LaunchAgents/com.alphaforge.paper.plist
# Also replace the CHANGE_ME PATH home in the plist's EnvironmentVariables.
launchctl load -w ~/Library/LaunchAgents/com.alphaforge.paper.plist

# Confirm it is running:
launchctl list | grep com.alphaforge.paper
```

`KeepAlive=true` + `RunAtLoad=true` + `ProcessType=Background` mean launchd
relaunches the loop whenever it exits and starts it at login. `ThrottleInterval`
prevents a restart storm on a config error. The loop's OWN wall-clock scheduling
(short ticks, deadline recomputed from `now_ms` on every wake) self-heals after a
nap: bars slept through are SKIPPED and COUNTED, never trade-back-filled. See
`deploy/com.alphaforge.paper.plist.template` for the full lid-close caveat.

To STOP trading without unloading (graceful, observable halt): `touch var/KILL`
(section 7). To unload entirely:

```sh
launchctl unload -w ~/Library/LaunchAgents/com.alphaforge.paper.plist
```

On a VPS, skip launchd: run the same `uv run af paper run --forever` under a
systemd unit (`Restart=always`), no `caffeinate` needed.

---

## 4. Backups -- NIGHTLY backup, WEEKLY restore drill

The Parquet lake is re-derivable; `var/trading.sqlite` (fills, equity, risk
events, slippage audit), `var/ops.sqlite`, and `data/predictions/` are NOT. Back
them up nightly to an OFF-BOX location (the backup target should not share a disk
or an iCloud folder with the repo).

### 4a. Nightly backup (cron or launchd)

```sh
# Manual:
uv run af ops backup --profile paper
```

`af ops backup` does a `sqlite3 .backup` of `trading.sqlite` and `ops.sqlite`
(a hot, consistent copy even while the loop writes), copies `data/predictions/`
if present, and writes a timestamped set into the configured backup dir.

Schedule it nightly. A simple cron line (replace the path):

```sh
# crontab -e  -- nightly at 03:17 local
17 3 * * * cd ~/alphaforge && PATH="$HOME/.local/bin:$PATH" uv run af ops backup --profile paper >> var/log/backup.cron.log 2>&1
```

After the soak you should also PRUNE old backups (the manager keeps `keep_days`
of history; pruning is part of `af ops backup`'s retention or run it on a
schedule per the ops config). COPY the backup dir off-box (rsync/scp to the VPS
or another machine) -- a backup on the same dying laptop is not a backup.

### 4b. WEEKLY restore drill (the gate)

```sh
uv run af ops restore-drill --profile paper
# or restore into a specific CLEAN dir:
uv run af ops restore-drill --into /tmp/af-restore-check --profile paper
```

This restores the LATEST backup into a CLEAN directory, REBUILDS the ledger/equity
from the restored `TradingStore`, and asserts internal consistency (equity == cash
+ position marks; fills replay). It EXITS 1 if the drill is not ok -- this is the
gate command that FAILS the soak when backups cannot be restored on a clean
machine. Run it weekly and keep the output.

---

## 5. Clock discipline

```sh
uv run af ops clock --profile paper     # on-demand skew check
```

- macOS NTP is on by default and is adequate for the soak.
- On a VPS, enable and verify `chrony`: `sudo systemctl enable --now chronyd`
  then `chronyc tracking` (the "System time" offset should be sub-second).
- The LIVE loop checks the clock once per cycle. On a breach
  (`|local - exchange| > max_skew_ms`) it fires a WARN alert and increments a
  `clock_skew_alerts` counter -- it does NOT halt (the staleness breaker + ingest
  grace already guard the DATA path; a skew is a TIMING warning that the bar-close
  decision instant is unreliable). A non-zero, climbing `clock_skew_alerts` over
  the soak means fix NTP/chrony before the drift widens.

---

## 6. Daily monitoring -- N/M cycle accounting

```sh
uv run af paper status --profile paper                     # last 24h
uv run af paper status --window-hours 168 --profile paper  # last 7 days
```

`af paper status` prints: the last cycle + status, the **N/M expected-vs-run cycle
accounting** (`cycles last 24h: 23/24 run (1 skipped/missed)`), the paper book +
equity, the drawdown-ladder state, and any open intents. The N/M line is the
Phase-8 >= 99% gate metric -- a soak that does not clear 99% over the 30 days does
not pass. Missed cycles are NEVER silent: they appear here and (for live
degradation) as WARN alerts.

Also review weekly:

```sh
uv run af ops slippage --profile paper   # modeled-vs-realized slippage report
```

`af ops slippage` reads the fills' walked-vs-modeled audit columns
(`walked_price`, `modeled_price`, `slippage_bps`, `book_exhausted`) and reports
n_fills, mean/median/p90/p99 slippage_bps, count of book-exhausted fills, and a
per-instrument breakdown. This is the leakageCritique.md finding-8 validation
signal -- review it before trusting the cost model with real money.

---

## 7. Halting -- the kill switch

```sh
touch var/KILL      # stop TRADING immediately (the loop keeps a heartbeat)
rm var/KILL         # resume trading on the next cycle
```

The KILL sentinel is the v1 brake. With it engaged the loop STOPS placing orders
but keeps its heartbeat tick alive (a halted system is still observable) and
announces the halt CRITICAL. There is deliberately NO inbound command channel
(no `/halt` over Telegram) -- the file sentinel over SSH is the entire control
surface, by design.

---

## 8. Alerts -- Telegram env vars

Outbound alerts (INFO/WARN/CRITICAL + the daily tearsheet) go to Telegram when
configured, otherwise to the structlog JSONL log. Set, in the environment the
loop runs under (your shell profile, or the launchd/systemd unit's environment):

```sh
export TELEGRAM_BOT_TOKEN="<token from @BotFather>"
export TELEGRAM_CHAT_ID="<your chat id>"
```

Token-less, alerts still land in `var/log/alphaforge.jsonl` -- nothing is silently
dropped. Do NOT hard-code these in the plist (it is world-readable); source them
from a profile or a secrets file the loop's environment reads.

---

## 9. Logs -- rotation and retention

`setup_logging` writes structured JSONL to `var/log/alphaforge.jsonl` with a
size+time rotation policy and ~30-day retention (rolled files older than the
retention window are pruned, bounded by both a file count and an age). The only
unbounded-growth risk in the system is this log; rotation makes it bounded, so no
manual log cleanup is needed during the soak. The launchd agent additionally
captures the process stdout/stderr to `var/log/paper.launchd.{out,err}.log`.

---

## 10. End-of-soak checklist (the gate, restated)

- [ ] `af paper status --window-hours 720` shows **>= 99%** of expected cycles run.
- [ ] The most recent **`af ops restore-drill`** passed (exit 0) on a clean dir.
- [ ] **`af ops slippage`** reviewed: walked-vs-modeled slippage is within
      tolerance and not systematically optimistic; book-exhausted fills are rare.
- [ ] `clock_skew_alerts` stayed at 0 (or any breaches were explained + fixed).
- [ ] The missed-cycle and reconciliation/halt alerts were demonstrated
      end-to-end at least once.

Pass all five and the Phase-8 soak is complete.
