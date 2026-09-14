# Historical extension input inventory

Current-lake timestamp metadata exists for370of375 configured AlphaMax names;294begin by2019 and326by2021. Missing exact identifiers:ABC,FI,FRC,MMC,SQ. They must be resolved through historical identity lineage rather than dropped or guessed from current tickers. Some configured instruments start after the original backtest's June2026end, confirming why the complete configured list cannot be treated as a fixed historical membership set.

All58configured crypto instruments have price and funding files;37have both beginning by2021. The inspected hourly and funding corpora begin January1,2020. The frozen carry run uses6048training bars(252calendar days), so the inspected corpus cannot support that warmup for a Q12020 evaluation. Changing the warmup or treating missing history as flat would define a different experiment. An extension to2022 may be feasible subject to internal-grid, funding availability and causal membership checks.

The original configurations deliberately begin later: AlphaMax startJuly1,2022 with252training bars,274embargo and21purge; crypto startJune1,2021 with6048training bars,168embargo and72purge. Saved output start dates therefore reflect both selected windows and walk-forward scheduling, not simply the earliest raw price. No settings were changed and no new returns evaluated.

Membership files were inspected rather than assumed absent:433rows for AlphaMax and117for crypto, with effective intervals and rank-related reasons. Four fixed historical checkpoints are retained separately. Effective intervals alone do not establish contemporaneous availability or rule out survivorship from the configured name list. The inventory reads timestamp footer bounds and membership values only; it does not certify internal gaps, prices, corporate actions, data publication time or lineage to the original runs. Raw market payloads have not been frozen for a prospective experiment.

## Decision

Do not launch a naive backdated reproduction. Prioritize the narrower actionable2022crypto extension feasibility: inspect the eligible membership/funding/hourly grid over the full fixed training window and evaluation year. Q12020 requires additional pre2020data or an explicitly different preregistered design; do not shorten warmup to manufacture coverage. AlphaMax additionally needs five identity routes and the already-documented original-input reproduction issue addressed before a broader claim. Full combined crisis qualification remains incomplete.

No new identity, qualified sleeve or production change; union273. Inventory artifacts and configuration/membership hashes are retained. No full market-file byte-reproducibility claim is made from metadata bounds.
