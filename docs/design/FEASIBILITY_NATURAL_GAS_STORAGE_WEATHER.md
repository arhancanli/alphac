# Natural-gas storage/weather residual — no-return source-feasibility protocol

**Declared:** 2026-08-16 before downloading historical WNGSR snapshots, enumerating the full NOAA
weekly key set, or requesting CME market records. **Prices and returns are forbidden.**

## Identity and overlap boundary

- Candidate family account: `commodity_inventory_weather`.
- Prior family trial: killed petroleum inventory scarcity; one return hypothesis already spent.
- Prospective identity: EIA Lower-48 first-release weekly net change residualized to a NOAA GEFS
  00Z forecast initialized on the Saturday beginning the storage week.
- The source-feasibility stage spends zero additional return hypotheses.
- A later return trial, if authorized, is family configuration two and must use the full union
  experiment count. It does not qualify as a fresh independent family by relabeling the commodity.

## Frozen period and sources

- Period: storage weeks ending 2017-01-06 through 2025-12-31. NOAA's public GEFS archive does not
  cover the analogous 2016 initializations.
- EIA denominator: official `ngshistory.xls` weekly dates, used only to enumerate expected reports.
- First-release evidence: Internet Archive captures of EIA's `wngsr.csv`. A capture must contain
  its own `Released:` date/time and week-ending date and must precede the next report's release.
  Current/revised history cannot fill an absent first-release snapshot.
- Weather evidence: exact NOAA GEFS object metadata for the control run at forecast hour 24 and the
  final perturbation member at hour 168. Pre-v12 uses the 20-member legacy path; post-upgrade uses
  the 30-member 0.5-degree path. These endpoint probes test both horizon and ensemble availability
  without downloading meteorological payloads.
- Futures evidence: Databento `GLBX.MDP3` metadata only for CME coverage and schemas. No records,
  prices, settlements, spreads, or returns may be requested.

## Locked gates

All are required for `PASS_TO_RETURN_PREREGISTRATION`:

1. At least 450 expected weekly EIA periods in 2017–2025 with no duplicate week endings.
2. At least 90% of expected periods have a hash-bound first-release `wngsr.csv` capture before the
   next report. Values must parse as Lower-48 stocks/net change, but no price join is allowed.
3. At least 95% of expected period-start initializations have both frozen GEFS endpoint objects,
   with byte size and ETag retained.
4. CME metadata covers the full period and exposes daily bars plus order-book or top-of-book schema
   for later execution calibration.
5. No market records or returns are opened and no new return hypothesis is spent.

Failure is `DATA_GATED`; thresholds, archive windows, weather initialization, and file endpoints are
not revised after aggregate coverage is observed. A source pass would still require a separate
machine-readable return preregistration locking forecast-field extraction, model training,
preholdout/holdout dates, NG contract rolls, calendar spreads, release latency, bid/ask, slippage,
limit moves, partial fills, capacity, DSR/PBO treatment, perturbations, and book-level gates.

## Locked result

The audit enumerated 469 official weekly periods and hash-bound all source workbooks. The frozen
Wayback route recovered 93 valid WNGSR snapshots representing only 84 unique first-release weeks,
or 17.91% coverage versus the locked 90% gate. That gate fails.

The other infrastructure passed:

- 938 NOAA endpoint probes bound both hour-24 control and hour-168 final-member objects for 468 of
  469 weeks (99.79%); only the 2016-12-31 initialization preceding the formal period was absent.
- Databento `GLBX.MDP3` metadata begins in 2010 and exposes daily, MBP-1, TBBO, BBO, trades, status,
  and definition schemas. Zero market records were requested.
- EIA's official `revisions.xls` `original_data` sheet independently covers all 469 weeks. It
  differs from current history in 53 rows, proving why revised history is not an acceptable silent
  substitute. This file was not the preregistered first-release source, so it cannot rescue the
  failed Wayback identity.

**Decision:** `DATA_GATED`. A new source protocol may use EIA's official `original_data` sheet and
must separately bind conservative historical availability/release timing before returns. The prior
petroleum trial remains in the family count; no new return hypothesis was spent here.
