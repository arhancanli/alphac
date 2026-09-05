# Sharadar HDB zero-dividend quarantine

**Short title:** HDB dividend quarantine  
**Author:** Arhan Canli  
**Decision:** `VERSIONED_ZERO_MARKER_QUARANTINE_AUTHORIZED`

## Finding

The frozen Sharadar `ACTIONS` archive contains 11 dividends whose values are not positive. One
survived the common-stock and liquidity filters and entered the executable lake: HDFC Bank ADR
(`HDB`) on 2025-06-26 with value `0.0`. The loader propagated that row unchanged. The event
engine correctly rejects it, so fundamental-single exact replays that encounter the row fail
closed before producing a replacement curve.

This is a vendor-originated source defect, not a backtest result. The raw archive, lake partition,
loader, engine, and failed replay are all bound by SHA-256 in the machine-readable audit.

## Primary-source cross-check

HDFC Bank's [June 2025 Form 6-K exhibit](https://www.sec.gov/Archives/edgar/data/1144967/000119312525146102/d60580dex99.htm)
states that the board recommended a ₹22 dividend per underlying equity share, with a 2025-06-27
record date and payment on or after 2025-08-11. Its
[2025 Form 20-F](https://www.sec.gov/Archives/edgar/data/1144967/000119312525158722/d854075d20f.htm)
states that one ADS represents three underlying shares. Sharadar's
[ACTIONS documentation](https://sharadar.com/docs/actions) defines the action value as numeric,
but does not resolve the required ADS net-cash or date semantics for this anomalous row.

The issuer filing therefore contradicts `0.0` as the declared underlying dividend amount. It does
not by itself prove the net USD cash an ADS holder should receive after FX, withholding, and
depositary handling.

## Vendor semantic resolution

A read-only Alpaca corporate-actions query returned a separate positive HDB cash-dividend record
whose `due_bill_on_date` is 2025-06-26, `due_bill_off_date` and `ex_date` are 2025-08-11, and net
rate is USD 0.641432 per ADS. Sharadar's same instrument-year partition separately preserves a
positive 2025-08-11 dividend. The exact zero row therefore matches a due-bill administrative date,
not the actual cash event.

The machine-readable resolution is
`artifacts/audit/hdb_dividend_vendor_resolution.json`, content hash
`sha256:c30b02bf34aa40b2974c5b1c3623363a601e826b866c335714c8b5b909247775`.
Alpaca warns that corporate-action creation times are not guaranteed, so the retrieval timestamp
is used as the conservative knowable-at bound. The Alpaca cash amount is not injected into the
Sharadar series and no event is moved backward.

## Quarantine contract

Future Sharadar loads reject any split or dividend with a non-finite or non-positive value
before it reaches the executable lake. The existing raw archive and contaminated partition remain
preserved by hash. No process may silently drop, move, or replace this row inside an
identity-bound replay.

The authorized repair creates a new physical lake version and removes only the exact HDB
2025-06-26 zero-cash marker. It preserves every other row, including Sharadar's positive
2025-08-11 event, and imputes no amount. The materialized lake manifest is
`artifacts/audit/sharadar_hdb_corrected_lake.json`, content hash
`sha256:8dec4dac90c0f2646ac09f2dfcbb26f5bd500c8fcb8c2bcda795113f7a46f9a8`.

An initial corrected-lake layout used top-level symlinked dataset directories. The universe loader
could not traverse that layout, so the attempt failed before signal or return computation. That
infrastructure failure remains preserved in
`artifacts/probe/fundamental_single_replays/e5f48adc25065ce9/replay_infrastructure_failure.json`.
The replacement lake uses real directories with hard-linked immutable leaves and passed a
non-empty-universe smoke test. A replay on that version must still independently prove exact
reproduction; the data repair itself supplies no performance evidence.

## Claim boundary

The vendor audit and lake construction opened no return series and spent no hypothesis. They
validate neither the historical curve nor any Sharpe, drawdown, capacity, diversification, or
sleeve claim. The immutable historical operating-margin verdict remains `KILL`; a separately
bound replay can reproduce or fail to reproduce that record, but data correction is never
permission to reinterpret a failed strategy.
