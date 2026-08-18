# AlphaForge → VPS deployment runbook

Purpose: move the live trading system off the laptop onto an always-on VPS. This is the
fix for the *substrate* fragility that caused every incident in late July 2026 — laptop
sleep, home-network drops, missed cycles. The strategy code is unchanged; only where it
runs changes.

**What this does NOT fix (be honest about it):**
- **Venue access / compliance.** If a droplet in region X reaches a venue your own
  jurisdiction blocks, that is a *compliance* decision (same as a VPN), not an ops win.
  Pick the server region for latency/reliability, not to route around a geo-block. Decide
  venue legality separately, with real advice.
- **Data-tier limits.** Rate limits live on the API *key/plan*, not the machine. See the
  Sharadar re-point below — the equity data fix is a source change, not a host change.

---

## 0. Target box

- Ubuntu 24.04 LTS, **x86-64** (the laptop is arm64; deps have clean x86 wheels — the
  Clarabel optimizer, pyarrow, duckdb all resolve). ARM droplets also work if preferred.
- 2 vCPU / 4 GB RAM / 40 GB disk is ample — this is not compute-heavy (walk-forwards run
  in minutes). ~$18–24/mo on DigitalOcean, less on Hetzner.
- A non-root sudo user `af`. Everything below runs as `af`, never root.

## 1. Bootstrap (once)

    ssh af@<box>
    git clone <repo-url> ~/alphaforge && cd ~/alphaforge
    bash deploy/bootstrap.sh        # installs uv + system deps + the venv, runs the test suite

`bootstrap.sh` is idempotent. It does NOT start any timer or touch secrets/data — those are
deliberate manual steps (2 and 3) so nothing trades before the box is verified.

## 2. Secrets (manual, never in git)

12 env files live under `~/.config/alphaforge/` on the laptop. Move them over a secure
channel (scp over the SSH key, or paste into `install -m600`), never through the repo:

    # on the laptop:
    # note the chmod covers *.env AND the Ed25519 signing key — an earlier version chmod'd only
    # *.env, which left the key's mode dependent on what tar happened to preserve.
    tar czf - -C ~/.config alphaforge | ssh af@<box> 'mkdir -p ~/.config && tar xzf - -C ~/.config && chmod 600 ~/.config/alphaforge/*.env ~/.config/alphaforge/*.key'

Required for the live sleeves: `alpaca.env` (MF broker), `alpaca_equity.env` (equity
broker), `sharadar.env` (equity DATA — see §4), `resend.env` (alerts). The crypto sleeve
reads its Binance/exchange keys from the loop's own env. `polygon.env` is **no longer
needed for the live path** after the Sharadar re-point (§4) — keep it only if any research
script still calls it.

## 3. Data (the record moves; the lakes re-download)

- **MUST transfer (this is the live record):** `var/trading_crypto_perp.sqlite` (the accruing
  crypto equity curve + cycles), `var/trading_equity.sqlite`,
  `var/trading_managed_futures.sqlite`, `var/experiments.jsonl` (the trial ledger),
  `var/transparency_log.jsonl` (the SIGNED CHAIN).

  > **The signing key is NOT under `var/`.** It lives at
  > `~/.config/alphaforge/transparency_ed25519.key` (see `scripts/transparency_log.py:46`), so
  > it travels with the §2 config tarball, **not** with the command below. An earlier version of
  > this runbook listed `var/*.key` here; that glob matches nothing, and because the command
  > ends in `2>/dev/null` it failed **silently** — following §3 alone would leave you believing
  > the key had moved when it had not. Losing this key breaks the tamper-evident record
  > permanently: the chain can no longer be extended under the same identity. **Do §2 first,
  > and verify the key landed with mode 600 before running any tick.**

      # on the laptop — the small, irreplaceable state (~7 MB):
      tar czf - var/trading_*.sqlite var/experiments.jsonl var/*sharadar*/experiments.jsonl \
        var/transparency_log.jsonl | ssh af@<box> 'cd ~/alphaforge && tar xzf -'

      # then CONFIRM the key arrived (it comes from §2, not the line above):
      ssh af@<box> 'test -s ~/.config/alphaforge/transparency_ed25519.key && \
        stat -c "%a %n" ~/.config/alphaforge/transparency_ed25519.key'   # expect: 600

- **RE-DOWNLOAD on the box (do not scp 6 GB):** the Sharadar lake (~2.8G) and any Polygon
  lake are rebuildable from their vendor bundles:

      uv run python scripts/sharadar_load.py            # rebuilds data/lake_sharadar from the bundle

  The crypto lake (Binance bars) backfills from the exchange the same way it did originally.

- After transfer, verify the chain is intact and the ledger N matches the laptop before any
  tick runs:

      uv run python scripts/transparency_log.py --verify   # chain head + entry count
      wc -l var/experiments.jsonl                          # must equal the laptop's N

## 4. The equity data fix — Sharadar re-point (do this here, once)

The live equity tick (`scripts/alphamax_tick.sh`) still runs `--profile equity`, which reads
the old Polygon-era lake and hammers free-tier Polygon for corporate actions (the 2026-07
AlphaMax wall). Research already runs `--profile sharadar` (the unlimited bundle, corp-actions
included, bulk download — no rate limit). The fix is to point the *live* tick at the same
source. **This changes the live traded universe (Sharadar ~8,400 names 1997+), so it is a
validated migration, not a toggle — and it earns a dated public disclosure that the live data
source changed.** Sequence (see the checklist in §6):

1. Point the equity tick + live_cycle equity profile at the Sharadar lake/var.
2. Regenerate the equity forward curve on Sharadar data; diff the book vs the last Polygon-based
   one (expect a *different* universe, not a broken one).
3. Publish the disclosure, then enable the timer.

Once live runs on Sharadar, **Polygon is fully retired** — one equity vendor, the one already
paid for.

## 5. Scheduling (systemd replaces launchd)

The laptop uses launchd; the box uses systemd user timers (survive reboot, log to journald,
no "laptop asleep" failure mode). Units are in `deploy/systemd/`, mirroring the exact launchd
schedule:

| job | cadence (UTC) | unit |
|---|---|---|
| live tick (crypto hourly) | every hour :05 | `alphaforge-livetick` |
| equity (AlphaMax) | daily 09:00 | `alphaforge-alphamax` |
| managed-futures (AlphaTrend) | daily 09:30 | `alphaforge-alphatrend` |
| health check | daily 03:10 | `alphaforge-health` |
| publish (web deploy) | daily 02:10 | `alphaforge-publish` |
| deribit capture | daily 13:00 | `alphaforge-deribit` |

    mkdir -p ~/.config/systemd/user
    cp deploy/systemd/* ~/.config/systemd/user/
    systemctl --user daemon-reload
    loginctl enable-linger af          # timers run even when logged out
    # enable ONE sleeve first, verify a clean cycle, THEN enable the rest:
    systemctl --user enable --now alphaforge-alphatrend.timer

## 6. Go-live checklist (verify before each sleeve trades)

- [ ] `bootstrap.sh` green (deps + full test suite pass on the box's arch)
- [ ] golden master byte-identical: `uv run pytest tests/integration/test_golden_master.py`
- [ ] secrets present + `chmod 600`; `alpaca_equity.env` reaches Alpaca (dry-run below)
- [ ] signed chain verified + ledger N matches the laptop
- [ ] **dry-run each sleeve before enabling its timer** — submits nothing:
      `uv run python scripts/live_cycle.py --profile managed_futures --dry-run`
      `uv run python scripts/live_cycle.py --profile equity --dry-run`
- [ ] Sharadar re-point (§4) validated + disclosed before the equity timer is enabled
- [ ] health check delivers a real alert (fix the sender domain so it is not spam-filtered):
      `python3 scripts/health_check.py --selftest-fail`  → expect a delivered RED
- [ ] the LAPTOP's launchd jobs are DISABLED once the box is confirmed (never run both — two
      clocks submitting to the same Alpaca accounts = double orders):
      `launchctl bootout gui/$(id -u)/com.accapital.<job>` for each

## 7. Backups (trivial on a VPS)

Nightly off-box snapshot of the irreplaceable state (the lakes rebuild, so back up `var/`):

    # a systemd timer or the provider's snapshot feature; minimum:
    tar czf /tmp/af-var-$(date +%F).tgz var/trading_*.sqlite var/experiments.jsonl var/transparency_log.jsonl var/*.key
    # ship to object storage / provider snapshots

## 8. What each incident this month becomes on the VPS

- Laptop sleep / missed cycles → **gone** (always-on + systemd).
- Home network drop → **gone** (datacenter networking).
- Polygon corp-actions wall → **gone** (Sharadar re-point, §4 — bulk, unlimited, already paid).
- Silent 13-day outage → the health timer + fixed alert delivery pages on day one.
- Binance venue reach → **unchanged** — still a compliance decision, not solved by hosting.
