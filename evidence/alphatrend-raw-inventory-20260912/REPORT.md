# AlphaTrend local historical input inventory

Read-only inventory of four explicit local roots for the 17 exact ETF symbols:

| Root | Matching ETF price rows | Matching ETF action rows | Limitation |
| --- | ---: | ---: | --- |
| Production data/lake | 986, all 17 ETFs | 6 rows across 6 ETFs | Prices span June 22–September 11, 2026 |
| Production data/lake_sharadar | 0 | 0 | No matching ETF partitions in this lake |
| Production data/lake_mf | 95,238, all 17 ETFs | 0 | Long adjusted history; not a raw replacement |
| Preserved AlphaMax Polygon snapshot | 20,366, all 17 ETFs | 0 | August 23, 2021–June 1, 2026 prices |

The inventory binds each matching parquet file and records its date bounds. It
is not a per-session gap audit or an independently certified price-convention or
action-completeness audit. Production files were read, not modified or imported
into the new candidate. The separate recent SIP and Polygon reference captures
remain the already verified diagnostics from prior phases.

No complete raw/action prefix for the proposed fixed 2004 IC anchor has been
established. ETF inception dates and pre-membership periods must be respected;
absence before inception must not be filled. The 2003 warmup setting also needs
its own explicit coverage/eligibility treatment. The Sharadar archive directory contains ACTIONS, SEP, SF1 and TICKERS ZIPs. The TICKERS archive was scanned: all 17 ETFs are assigned to SFP with historical price bounds back to their inception. SFP is absent from this archive directory. The 3.21 GB uncompressed SEP price file and ACTIONS/SF1 rows were not scanned. Archive member sizes and matching ETF metadata are retained in archive_metadata.json.

Three bounded Nasdaq SFP probes using the existing credential returned HTTP 200 and the expected price schema, but zero rows for SPY: January 2004, August 2021, and no date filter. All three empty response bytes matched. No conclusion about subscription entitlement is justified by these responses alone. Usable SFP data access remains unestablished; schemas and catalog metadata are not price records.

Required next data work: resolve the SFP empty-result behavior and inspect action
semantics, then use provider access to fill only proven gaps. An adjusted-history
inverse transformation is not automatically authentic raw-price reconstruction.
Full data and provenance must be sealed before registering or evaluating the
new candidate. No shortened-window substitution for the fixed candidate occurred.
