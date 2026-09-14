# Prospective AlphaForge pause, Alpaca compatibility and research continuation

11 September 2026. Branch: `codex/alphaforge-prospective-pause`.

## Allocation removal: prepared, not active

The user requested that AlphaForge's return stop contributing to ALPHAC. The new
`scripts/prepare_alphaforge_pause.py` prepares two prospective schedules, effective
September 12 (after all frozen September 11 marks):

- Cash: crypto 0%, AlphaMax 25%, AlphaTrend 25%, AlphaVintage 25%, cash 25%.
- Redistribution: crypto 0%, each remaining sleeve one third.

The allocation preference question remains unanswered. Neither option is activated.
`evidence/pause-options.json` preserves both proposals. The current 10% strategic
overlay is unchanged; because its mix includes BTC, excluding AlphaForge does not
mean removing all crypto exposure. Cash is modeled at zero return, not invented yield.
The standalone AlphaForge record and every earlier composite return remain visible.

13 focused tests passed in 1.36 seconds: seven proposal cases plus six existing
schedule tests. They verify historical invariance, prospective exclusion, exact cash
weight retention, refusal to backdate, and separate overlay behavior. Receipt:
`evidence/pause-tests.xml`.

This is a tested schedule proposal, not a completed production rollout. Once the
allocation is selected, the production integration must append the committed schedule,
update current composition/presentation and the live-change declaration, mark the new
forward specification, and refresh dependent artifacts. The existing research book
normalizes weights; its historical metrics must not silently be relabeled as evidence
for the new cash-bearing composition. No change was copied into the production repo.

## Alpaca: connectivity verified, strategy migration blocked

A bounded read-only probe authenticated with an existing PAPER credential context:

| Request | HTTP | Matching active tradable assets |
| --- | --- | --- |
| `/v2/assets?asset_class=crypto_perp&status=active` | 200 | 0 |
| `/v2/assets?asset_class=crypto&status=active` | 200 | 73 |

Evidence: `evidence/alpaca-capability.json`. The probe used two GETs, no retries,
five-second whole-request deadlines, a 1 MiB response cap, and no redirects. It did
not log credential values, response bodies or account identifiers. No account was
created, reset, repurposed or connected to the AlphaForge order path; no order was sent.
No dedicated AlphaForge paper credential file was found among the existing profiles.

The spot documentation disallows shorting and margin:
https://docs.alpaca.markets/us/docs/crypto-trading

A June 2026 changelog includes `crypto_perp` enum and swap-rate fields:
https://docs.alpaca.markets/us/v1.1/changelog/2026-06-24-trading-api-00bf221

Those newer fields do NOT establish tradable perpetuals, paper funding settlement,
or entitlement for this account. The direct probe returned none. Therefore a generic
claim that Alpaca can never offer perpetuals would overstate the evidence; equally,
claiming the current AlphaForge strategy is connected would be false.

Compatible paths: establish access to a paper perpetuals venue and verify its funding
and contract semantics, or separately design/test a spot-only strategy for Alpaca.
The latter is a NEW strategy identity, not a migration of long/short funding carry.
Do not discard short signals, substitute spot symbols for perpetual IDs, or attach it
to another sleeve's trading account to make the connection appear complete.

## Discovery continues

Reviewed all 13 current candidates in `config/sleeve_discovery.json`; none is currently
cleared for admission. Key priorities and concrete blockers:

1. Active ownership escalation: existing source pipeline; 48 independent blind labels
   remain required. Do not replace the independent review with this agent's judgments.
2. Repurchase/issuance flow: 60 frozen Item 703 labels remain required. This is already
   classified within an existing economic family, not a new distinct sleeve count.
3. Pre-FOMC drift: schedule lineage and return specification exist; historical quote
   entitlement and the bounded acquisition route remain blocked. Opening returns with
   a convenient substitute source would change the frozen research identity.

Additional lead screened at literature level: leverage-ETF closing rebalance pressure.
A 2013 Federal Reserve study finds concentrated rebalancing price effects:
https://www.federalreserve.gov/econres/feds/are-leveraged-and-inverse-etfs-the-new-portfolio-insurers.htm
A 2014 Federal Reserve study finds that capital flows offset much of the mechanical
rebalancing demand, so a naive leverage-times-return rule is not sufficient:
https://www.federalreserve.gov/econres/feds/are-concerns-about-leveraged-etfs-overblown.htm

This lead was not found by a focused text search of the current atlas/queue, but its
novelty is NOT established by that search. Next source-only gate: audit issuer AUM,
shares outstanding, creation/redemption timing, leverage mandates, and intraday closing
execution data known BEFORE the decision. Reject feasibility if contemporaneous fund
flows cannot be distinguished from mechanical rebalance estimates. No return trial,
Sharpe, candidate admission or funding purchase was made for this lead.

Improvement work remains focused on a repaired AlphaForge baseline and a narrowly
specified carry-risk challenger, alongside source feasibility for economically distinct
sleeves. Removing the losing sleeve from future allocation is a specification change,
not proof of predictive skill or permission to erase its losses.
