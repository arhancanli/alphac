# AlphaVintage publication bundle v1.0.0

This is a deterministic **incomplete preparation bundle** for Arhan Canli's AlphaVintage working
paper. It is not peer reviewed and has not been submitted to SSRN, Zenodo, arXiv, or OSF.

The historical result is KILLED. Alpaca evidence is paper-only and sanitized. Raw vendor market
data and the derived return curve are not redistributed pending a source-licence review.

The core calculation and all four locked decision gates now have author-run temporary-workspace
replays from freshly reacquired macro and market inputs. The attempt ledger preserves one numeric
tolerance failure followed by one pass; both attempts retained the same four gates and KILLED
verdict. All three upstream benchmark strategies now have completed author-run replays. AlphaTrend
has a pinned-source replay
from a sealed private ETF lake: the AlphaVintage-consumed equity parquet is byte-exact, as are 466
of 467 output files. The sole mismatch is the DSR-bearing JSON because the historical 228-identity
selection context is absent from the pinned commit; that discrepancy is published and the stored
DSR is not regraded. AlphaMax's fresh-vendor replay completed but did not reproduce the historical
curve; both the historical and replayed DSR gates fail, and the stored result is not regraded. The
historical, non-sleeve `prereg_investment` raw-loader, universe, and strategy replay is byte-exact
for all 779 output files. Its original run remains non-preregistered historical gate input, not
sleeve evidence. Remaining release blockers: data-licence resolution, exact AlphaMax historical-input recovery, full multi-sleeve end-to-end reproduction, and independent human reproduction. The bundle includes internally inspected archival PDF/HTML/LaTeX assets; `SHA256SUMS` binds every released file.
