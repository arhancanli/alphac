# Frankfurt VPS scripts — the crypto ingest/trade host

These five files run on the Binance-reachable droplet (`201.79.12.40`, DigitalOcean FRA1), **not**
on the Mac. They were authored directly on that host on 2026-08-10/11 and lived nowhere else until
2026-08-12, which made a single rented server the only copy of the crypto sleeve's operating code.
This directory is the recovery copy. It is not deployed from here — the host is the running
authority — so **any edit made on the droplet must be pulled back here** or the two will diverge.

## Why a second host exists at all

AlphaForge (crypto funding carry) is one of four sleeves and had ~27% lifetime uptime because
Binance is unreachable from every other machine we own, for two *different* reasons, both measured
2026-08-10:

* **the Mac (Turkey):** `fapi.binance.com` returns HTTP 000 in 0.03s — an instant connection reset.
  Bybit, OKX and Kraken fail identically, so it is a network-layer block on exchange endpoints, not
  a Binance decision and not DNS (DNS resolves, TCP 443 connects).
* **the original MoonShot droplet (US):** HTTP 451, *"Service unavailable from a restricted
  location"* — Binance geo-blocks US IPs. That host can never be the fix, whatever runs on it.

Frankfurt answers HTTP 200. That is the only reason this host exists.

## What runs here, and what deliberately does not

| file | role |
|---|---|
| `ingest.sh` | daily 03:15 — full 777-instrument funding/OHLCV ingest (`af data update`) |
| `trade.sh` | hourly :10 — the crypto paper loop (`af paper run --once`), then the maker shadow |
| `collect_positioning.py` | the positioning/order-flow archive (see below) |
| `collect.sh` | hourly :40 — wraps the collector with a lock and a bound |
| `stale_lock.py` | releases the ingest PID lock **only** when its holder is provably gone |

**This host holds no secrets.** The crypto sleeve is paper-only on public market data: there is no
Binance credential file anywhere in the system, and `CCXTBroker` refuses to act unless *both*
`live.paper=False` in config and `ALPHAFORGE_ARMED=1` in the environment. Neither is set here and
neither should ever be. The Alpaca-trading sleeves and the ed25519 transparency key stay on the Mac.

**The signed transparency chain has exactly one writer, and it is the Mac.** Two hosts appending to
an append-only tamper-evident record is a worse integrity problem than any staleness it would fix.
This host produces a track record; only the Mac publishes one.

## Data flow

```
:05  (VPS) ingest — funding + OHLCV into /opt/alphaforge/data/lake
:10  (VPS) trade  — paper cycle on the fresh lake, then maker-shadow record/evaluate
:40  (VPS) collect — positioning archive
:25  (Mac) scripts/vps_crypto_sync.sh — stages, MERGES row-wise, then publishes
```

The Mac pull **merges at row level and never copies files**: the VPS holds recent rows only, the Mac
holds years, and a file-level copy would replace history with the recent slice and silently destroy
the difference. That bug was caught before it ever ran; see `scripts/vps_crypto_sync.sh`.

## The positioning archive

`collect_positioning.py` captures five Binance endpoints that carry **positioning and order flow**
rather than price — including the top-trader-versus-all-accounts spread, an exchange-published
smart-money/retail signal. Nothing in the main lake carries anything like it.

It deliberately makes **no claim and runs no test**: these endpoints serve only ~21 days of history
and return empty at 200 days back, so nothing here can support a walk-forward yet. Its whole value
is that this history is **unbuyable retroactively** — Binance does not sell it and no vendor here
carries it. In a year the book either has twelve months of it or twenty-one days, and the only
difference is whether this job kept running.

Rows are partitioned by **observation** date, not fetch date. Naming files after the fetch date put
~21 days of observations in every file and produced 1.84x duplication after two days, on track for
~21x by day 21.

## Rebuilding this host from scratch

1. Provision a droplet in a Binance-served region — **Frankfurt, Amsterdam or Singapore**. Not the
   US (451) and not the UK (FCA restrictions).
2. From the Mac: `./scripts/vps_crypto_bootstrap.sh <ip>`. Its first action curls Binance and
   **aborts without installing anything** if the region is blocked — provisioning in the wrong place
   is the likeliest way to waste money here.
3. Copy these five files to `/opt/alphaforge/`, recreate the three systemd timers
   (`af-ingest` 03:15, `af-trade` `*:10`, `af-collect` `*:40`).
4. Seed the lake from the Mac (the Mac is the superset after any merge) and ship `var/ops.sqlite`
   **pruned to `BINANCE:PERP:%`** — leaving the equity rows in makes `af data update` walk 20,663
   instruments Binance has never heard of and burn the whole window, and makes the paper loop chase
   `XUSE:CASH:*` symbols on Binance Vision for 404s.

## Every lock here is age-guarded, and that was learned the hard way

A `mkdir` lock is released by a trap on EXIT, and a trap does not fire for SIGTERM, an OOM kill, or
a reboot. On 2026-08-11 `collect.lock` was orphaned at 06:40 and every hourly run for the next
**15 hours** exited instantly with "another collect run holds the lock" — the archive collected
nothing all day and said nothing about it. Thresholds are set well above each job's *measured*
runtime (collect 303s → 45 min; trade ~11s → 45 min; ingest ~40 min → 90 min), because releasing a
live job's lock would let two writers race the same lake, which is far worse than lost collection.
