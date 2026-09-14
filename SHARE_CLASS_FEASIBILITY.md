# Share-class feasibility: first two legal cases

Two fixed examples from the existing 186-pair metadata screen now have a legal
rights review and a link to local corporate-action evidence. These examples were
chosen for distinct legal structures, without ranking returns. They do not form
a historical universe or establish an investable sleeve.

| Case | Economic units from reviewed sources | Conversion | Consequence for research |
|---|---|---|---|
| Alphabet GOOG / GOOGL | One C share and one A share have equal dividend/liquidation rights | No ordinary A/C conversion; liquidation has separate provisions | A price gap alone does not establish mispricing or force convergence |
| Berkshire BRK.A / BRK.B | One A share has the economic rights of 1,500 B shares | Holder can convert A into B, not B into A | Hedge units and conversion direction matter; operational costs still apply |

Alphabet sources: [2024 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)
and [2021 securities description](https://www.sec.gov/Archives/edgar/data/1652044/000165204422000019/googexhibit420q42021.htm).
GOOGL carries voting rights; GOOG generally does not. The reviewed documents do
not establish an uninterrupted amendment history through every proposed test
date. Equal economic claims are not proof of equal market value.

Berkshire source: [2024 annual report, note 22](https://berkshirehathaway.com/2024ar/2024ar.pdf).
The B share also has a different voting entitlement. A hypothetical long A /
short 1,500 B conversion path requires borrow, settlement and conversion handling.
The reverse trade cannot rely on a reverse conversion. No execution recommendation
or guaranteed arbitrage is implied.

The local Sharadar ACTIONS archive independently records a 50-for-1 BRK.B split
on January 21, 2010, matching the [issuer's filed charter amendment](https://www.sec.gov/Archives/edgar/data/1067983/000119312510018135/dex992.htm).
Consequently, applying today's 1,500 ratio across the pair's entire 1996-onward
metadata history would be invalid. The local file also records both Alphabet
classes' 2022 splits and a 2014 GOOGL event; the latter needs explicit class-
distribution treatment before historical reconstruction, not a blind generic
split adjustment. No price returns were opened in this audit.

The audit script writes `evidence/share-class-rights/rights-audit.json`, including
permatickers, source URLs, economic units, conversion direction, split records,
input hashes and explicit unresolved gates. It ran successfully against the actual
local archives and passes Ruff. The Berkshire PDF and USDA policy bulletin were
saved and hash-verified; direct SEC and Alphabet PDF requests failed, with those
facts reviewed through the web tool. Receipts preserve the failed accesses.

The original Schultz/Shive paper remains a research lead: the publisher and
SSRN full-text routes were not recovered in this pass. We have not replicated
its methods. Do not count these two issuers as two independent sleeves.

Next, establish synchronized quote access for these two fixed pairs and a
versioned legal timeline. Then specify a single costed hypothesis, including
borrow and conversion constraints, before examining returns. A separate use
could be choosing between classes when an existing equity strategy already wants
issuer exposure; that would be an execution improvement requiring its own test,
not an additional independent source of alpha.

## Quote follow-up completed

Three small Databento samples and a fixed as-of coverage audit now exist.
`SHARE_CLASS_QUOTE_RESULTS.md` records the successful data route, NYSE Berkshire
symbol mapping, sparse/update-age limitations and pre-sample SEC filings.
This supersedes the earlier quote-access task; full trading feasibility remains
unproven and no return test has been run.
