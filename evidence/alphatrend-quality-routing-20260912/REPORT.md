# AlphaTrend quality-aware routing — September 12, 2026

Implemented a separate v2 diagnostic input boundary. It keeps zero-volume sessions in the calendar and retains recorded signal observations, while marking those sessions ineligible for execution. Labels requiring entry or exit on a zero-volume session fail without moving the date. Price-dispute flags must be explicit booleans; disputed rows block feature histories and intersecting label intervals. Execution views retain every row with an eligibility flag that an engine adapter must enforce before activation.

All 93,444 full-panel rows are retained. Raw OHLC and volume match exactly. Four rows are execution-ineligible: the three unresolved DBA/UUP/USO cross-source discrepancies and the zero-volume UUP observation. Full feature-history access correctly fails. For symbols without these price disputes, 78,439 feature rows match the synthetic panel exactly. That subset is a routing check, not a revised strategy universe.

70 targeted tests pass, covering original/v2 routes, raw labels and existing fill behavior, including rejection of absent or zero quote volume. Ruff passes for the new module, tests and checker. The eight new tests cover calendar preservation, future-dispute isolation, label rejection, valid raw-label accounting, copy isolation and invalid quality inputs.

The one previously timed-out USO 2020-04-09 Polygon query was retried once and returned HTTP 403. The earlier three 2007 queries likewise lacked timeframe access. No source replacement, subscription change, vendor message or order occurred. A vendor clarification draft is retained separately and has not been sent.

The zero-volume handling policy is now implemented at the diagnostic boundary; the observation itself is not independently verified. The three price discrepancies still need source adjudication. The full engine is not integrated: it must enforce eligibility, separate signal and raw label inputs, and handle payment-date cash. Historical action availability and lifecycle continuity remain prerequisites. No strategy returns were tested and no new hypothesis was added; union remains 238.
