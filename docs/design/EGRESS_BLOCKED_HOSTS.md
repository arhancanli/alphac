# Hosts unreachable from the research machine, and what they block

Measured 2026-08-18 from the primary macOS research host. This file exists because two separate
pieces of planned work have now been stopped by the same thing — network egress, not code — and
the second one wasted a design cycle before that was noticed. A blocked host looks exactly like a
bug until you check.

## Method

`curl -s -o /dev/null -w "%{http_code}" --max-time 25 <host>`, three attempts, plus `nslookup`
to separate DNS failure from connection failure.

| host | code | DNS | verdict |
|---|---|---|---|
| `https://web.archive.org` | **000** ×3 | resolves → 207.241.237.3 | **BLOCKED at connection level** |
| `https://archive.org` | 200 | resolves | reachable |
| `https://publicreporting.cftc.gov` | 200 | resolves | reachable |
| `https://api.eia.gov` | 403 (no key on bare path) | resolves | reachable |
| `https://www.deribit.com` | `RequestTimeout` via ccxt | resolves | **BLOCKED** (long-standing) |

DNS resolving while every connection fails means a firewall/ISP path block, not a name-resolution
or outage problem. `archive.org` answering while `web.archive.org` does not points at per-host
filtering rather than a whole-domain block.

## What this blocks

**CFTC hedging-pressure release lineage.** The candidate's own feasibility result records
`exact_release_timestamp_lineage_rate: 0.0` — the Socrata dataset carries the Tuesday `report_date`
and no release timestamp, so keying on the report date is three days of lookahead. CFTC publishes
only the CURRENT year's release schedule with no prior-year archive, so reconstructing 2006–2026
release instants requires Wayback captures. That is the identical technique
`audit_treasury_wayback_schedule_lineage.py` used to reach 92.9% combined coverage on treasury
auctions — and it cannot run here now.

Note the timing: `artifacts/feasibility/treasury_auction_concession/wayback_schedule_audit.json`
was written 2026-08-16 05:42, so the host was reachable two days ago. This is a NEW block, and any
Wayback-dependent audit committed before today may not be re-runnable on this machine.

**Deribit options capture.** Long-standing and already documented as structural.

## The fix is the one already chosen for venue data

Egress-blocked collection is exactly why venue data is collected from the Frankfurt host rather
than locally. Wayback-dependent lineage work belongs on the same host for the same reason. This is
an operational placement question, not a research one, and it consumes no hypothesis budget.

## The rule this file is really for

**Before diagnosing a data-acquisition failure as a bug, check whether the host answers at all.**
Both blocks above present as timeouts deep inside a library stack — `ccxt.base.errors.RequestTimeout`
for Deribit, an empty body and `HTTP 000` for Wayback — and neither says "you cannot reach this
network from here." Re-run the table above first.
