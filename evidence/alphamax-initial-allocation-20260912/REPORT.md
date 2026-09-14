# AlphaMax initial allocation trace

The pinned reproduction selects CVS at rank 173 of 202 and excludes TEAM at rank
172. The bottom 30 names start at rank 173. Their annual forecast difference is
0.0000118624 (0.118624 basis points), a near tie rather than an exact floating-point
tie. Both names are shortable in this historical context. Annual estimated
volatility is 24.889% for CVS and 68.556% for TEAM; inverse-volatility sizing means
a boundary substitution also changes the normalization of the short book.

Captured target weights, using the preserved $100,000 initial equity and decision
prices with integer share flooring, reconstruct all 202 replay quantities exactly.
All nonzero order sides match. The volatility overlay scale is 1.5. This localizes
the fresh replay's TEAM/CVS substitution to forecast ranking before execution.
It does not prove why the original run had another ranking: its complete original
raw data, forecasts, covariance and dirty source state remain unavailable.

The harness uses the retained pinned source in an isolated workspace with a copied
operations store and read-only use of sealed data. It intercepts the first normal
allocation, records its locals, and exits before the engine generates orders. The
full forecast cross-section, covariance and trailing closes are retained. No new
return trial, parameter variant, orders or promotion; hypothesis union remains 238.

`allocation_verification.json` binds the diagnostic scripts, all pinned Python
sources, captured numerical inputs and retained replay orders. `inventory.json`
binds the first trace outputs. The verification script has one cosmetic Ruff
RUF005 list-concatenation warning; its evidence-bound source is left intact.

Next: reconcile the actual momentum feature inputs and historical source
reconstruction where records exist. Do not change ranking rules to force a match
or treat this reproduction diagnosis as evidence of improved performance.
