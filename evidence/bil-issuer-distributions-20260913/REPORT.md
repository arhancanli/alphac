# BIL issuer distribution reconciliation

The independent ZIP/XML extraction matches all 65 BIL records extracted with openpyxl for January 2021–June 1, 2026. Source workbook SHA-256 matches the download receipt. There are 49 positive distributions and 16 explicit zero ordinary dividends; zeros were not inferred from missing records.

The vendor omits 15 zero dates and reports $0.0215 on March 1, 2022 where the issuer reports zero. Other amount differences are retained in comparison.json. The candidate will use issuer amounts and ex/pay dates; vendor originals remain unchanged. Issuer payment lags range from 3 to 7 calendar days. The June 1, 2026 distribution pays June 4: it must remain a receivable at the evaluation endpoint, included in NAV but unavailable for purchases.

Sources: State Street BIL fund page → ETF dividend distributions page → historical distributions workbook; exact URL, receipt and original bytes retained locally. This current-hosted workbook establishes issuer-reported history, not historical publication vintages or actual broker settlement. Raw price coverage previously passed all 1,358 expected XNYS sessions. Adjusted prices are excluded from the cash-distribution ledger.

No portfolio returns computed and no trial reserved in this source phase. Next: freeze one cash-allocation experiment, implement its ledger and synthetic causal/accounting tests, then validate canonical reservations before measuring normal/stress returns. This is cash implementation, not a distinct alpha sleeve. Reference 316/317 and canonical measured union 330 remain unchanged.
