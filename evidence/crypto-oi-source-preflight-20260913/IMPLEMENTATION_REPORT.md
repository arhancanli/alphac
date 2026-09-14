# OI source preflight implementation — 2026-09-13

Source-only implementation completed while the existing fixed archive acquisition runs. No historical targets, features or forecasts calculated.

scripts/crypto_oi_source_preflight.py maps observed funding settlements only within one second AFTER the modeled00/08/16UTC slots. Original settlement and availability timestamps remain in the normalized result; rates are unchanged. Wrong symbols, offsets, duplicate mapped slots, nonfinite rates and premature availability fail. The fixed tolerance is inherited from the existing source cadence audit, not estimated from prospective performance or used to infer missing settlements. The expected schedule remains modeled rather than independently proven historical publication metadata.

The calendar gate uses the frozen2022–June2026 daily grid,29-day common source windows and D+3decision mapping. Omitted days become false, not interpolated. It measures each symbol's coverage over the entire fixed2023Jan1–2026May25 decision period, requires95%, and checks252 paired training dates after seven-day label maturity and a further seven-day purge. Label endpoint and actual input availability checks remain necessary; this gate alone does not produce training labels or establish execution.

Ten synthetic tests pass. They cover retained actual timestamps, all slot-rejection conditions, exact first training cutoff,29-window loss from one absent day, and failure despite >99% raw-day completeness. This prevents a high file count from being mistaken for enough evaluable observations.

run_coverage.py is prepared for a single run AFTER terminal archive audit. It binds the archive receipts and local source files, validates actual funding-slot completeness/availability, applies the frozen mask and reports source alignment against retained hourly prices. Endpoint discrepancies require resolution before canonical preparation; they are not silently omitted to improve coverage. Script has not yet been run on the complete archive.

NEXT poll acquisition session39494, inspect terminal failures, run evidence/crypto-oi-full-source-20260913/audit_archives.py once, then PYTHONPATH=src:scripts python evidence/crypto-oi-source-preflight-20260913/run_coverage.py. Preserve all gaps and any failed coverage gate. Reserve the paired historical diagnostic identities only after source coverage and bindings are ready. No real forecasts or labels before reservation.

Previous goal turn was progress (acquisition launch/local-source audit); this turn adds a tested preflight and verified polling of the same live process. No combined performance change or new qualified sleeve. Goal remains active.
