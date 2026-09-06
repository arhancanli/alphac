# Reconstructing corporate-action basis without opening strategy returns

**Short title:** Corporate-action basis reconstruction  
**Author:** Arhan Canli  
**Project:** AlphaC Algorithms / Canli Capital  
**Research status:** Corrected reproduction complete; factor remains killed; global split gate failed

## Abstract

An immutable operating-margin replay exposed a corporate-action data defect: dividend values from
the frozen Sharadar ACTIONS archive were being treated as raw cash amounts even when they were
expressed on a later split-adjusted basis. This note records the diagnosis, issuer-anchored repair
contract, versioned materialization, full-lake validation, external cross-check, path-exposure
audit, exact issuer verification, and one fail-closed corrected reproduction. The dividend gate
passes after repair, while the global split-boundary gate remains failed. The corrected
operating-margin result improves materially but remains negative and **KILLED**; it does not earn
sleeve admission or production promotion.

## Trigger and preserved result

The valid historical operating-margin result remains **KILLED**: Sharpe
`-0.4173809362582861`, maximum drawdown `0.39623483315571484`, and final equity
`63911.64507926929`. A later apparent Sharpe of `0.2595404513705637` is rejected because its replay
was contaminated by unverified corporate-action units. The first divergence was a legitimate
RGLD dividend; the largest distortion was a CMCT cashflow produced by interpreting a split-adjusted
dividend as raw cash. Historical results are not rewritten by this investigation.

## Diagnosis and repair contract

Across 167,120 positive dividend rows, 422 exceeded the full pre-ex-date raw close. Applying the
product of same-ticker raw `action='split'` values on or after each dividend date reconciled 421 of
those 422 rows. Raw `adrratiosplit` rows were treated as metadata, not as a second executable share
mutation.

Apple provides the ordinary-event anchor. The frozen source contains a dividend value of `0.205`
on 2020-05-08 and a later four-for-one split. Their product, `0.82`, exactly equals Apple's
issuer-declared cash dividend. This supports—but does not elevate beyond inference—the following
normalization:

`raw cash amount = source dividend value × product of later same-ticker market split ratios`

The sole unresolved impossible row, VATE on 2020-05-14, was quarantined exactly after issuer and
independent-provider evidence failed to support it. A zero-value HDB marker was also quarantined
exactly. No amount was imputed. The source archive and original lake remain immutable. The sealed
repair receipt has content hash
`sha256:48fcfde04e3c7f7d28bc349c93b55911f97514317e74bac67fca80980b621e47`.

## Versioned materialization

The corrected corporate-action lake is a new physical version, not an in-place edit. It maps
171,924 base rows to 171,780 normalized rows: 167,118 dividends were normalized, 31,807 dividend
amounts changed, 142 ADR-ratio metadata rows were removed from execution, 4,662 market-split rows
were preserved, and exactly two source rows were quarantined. Non-corporate-action datasets are
hard-linked and the original lake is preserved by hash. The materialization receipt has content
hash `sha256:178c4564f9c5e0b917db752879c08a2f25c3133e614f92f0ecec6af3c33ef1c0`.

## Full-lake validation

The dividend gate passes: all 167,118 dividend rows were checked; zero exceed the full pre-ex-date
close; the maximum observed multiple is `0.9836065573770493`; and 259 rows lack a two-sided price
boundary and remain explicitly counted.

The split gate fails. Of 4,662 market-split groups, 4,189 are consistent, three would verify under
the reciprocal ratio, 109 have unexplained price boundaries, and 361 lack a two-sided price
boundary. In total, 473 failed or unverifiable events affect 401 instruments. The validation
receipt therefore records `CORPORATE_ACTION_VALIDATION_FAILED_SPLIT_BOUNDARIES`, content hash
`sha256:6ed09e42b6e6a744df4dfb3c9bbd927b58ac70a813c9c819a1592daa8afae583`.

The engine now fails closed when an exposed position or order encounters a split that violates its
price-boundary sanity check. It may no longer log the defect and continue with unconverted
exposure, which could fabricate profit and loss.

## Independent split cross-check

A GET-only Polygon reference audit downloaded 28,079 split records from 1997-12-31 through
2026-08-23 and cross-checked all 473 local failed or unverifiable events by
date and ticker alias. The external provider confirms the stored ratio for 114 events, confirms the
reciprocal of the stored ratio for one event (BMNR on 2021-04-27), reports a materially different
event ratio for two events (ACHC on 2011-11-01 and JHG on 2017-05-30), and has no matching event for
356. Three initially apparent conflicts resolve at the source's recorded five-decimal precision.

These classifications narrow the next investigation; they do not close the gate. Stored-ratio
confirmation does not explain a disagreeing or absent local price boundary. BMNR is a candidate
for a separately sealed reciprocal-ratio repair, not an authorized mutation. Conflicting and
unmatched events remain closed. The external cross-check receipt has content hash
`sha256:b401c5260988ba900d0acac857bfeda28a3cb353d6a18db3b9ef55890dc67a32`.

## Lifecycle and sealed-path accounting

The 473 failed or unverifiable events were then classified against each instrument's frozen price
lifecycle. Of these, 332 precede the first price, 23 occur on the first-price boundary with no
pre-existing exposure, five follow the final price, 112 occur within a price lifecycle, and one
lacks a frozen lifecycle. This narrows the global unresolved set without deleting a source event
or declaring the lake valid. The lifecycle receipt has content hash
`sha256:deed344bd2823f820e326b69f510f704a11b3ba3d2621100594da2600f78cb2d`.

Within the operating-margin window, 71 in-lifecycle failed events were audited against the sealed
historical order and position path. Fifty-one had independent-provider support and 20 remained
unresolved. Sixty-nine had no observed pre-boundary position or queued order. Exactly two were
held: ADTX on 2022-09-14 and SPCE on 2024-06-17. This is historical-path evidence, not an assumption
about an unseen counterfactual path. The exposure receipt has content hash
`sha256:c9d379d6a7bd9a7991f561e84162ba1f8c78715b32d540b7b56b6d179eaf6dfd`.

Issuer filings independently confirm ADTX's one-for-50 reverse split and SPCE's one-for-20 reverse
split on the exact stored dates. The corrected reproduction therefore accepted only two exact
`(instrument, ex-date, ratio)` tuples—ADTX at `0.02` and SPCE at `0.05`—as authorization to bypass
the price-gap heuristic. A wrong instrument, date, or ratio still failed closed. The exact-event
verification receipt used by that reproduction has content hash
`sha256:fa8595944365c27e6a8a49a490ccdafd7f37db31808e569da527c8926fb1b550`.

## Global fail-closed routing and subsequent issuer resolutions

Every one of the 473 failed events now has exactly one governance route. Three hundred sixty-six
are non-executable under frozen lifecycle evidence, 25 have exact issuer authorization, 12 are
issuer-verified composite actions that remain quarantined, 16 have issuer conflicts or date
mismatches, and 52 have provider corroboration but remain failed closed because their local price
boundary still disagrees. Two remain unresolved within a price lifecycle; the sole no-lifecycle
event is now an issuer-timeline conflict. The global gate therefore remains failed. The policy
receipt has content hash
`sha256:20dceb4995121d0895223f830d87e858c5f527e2936cadb5cdf3a98778ab2b28`.

The two additional exact authorizations are AMPE and EVHC. Ampio's filing establishes a
fifteen-to-one reverse split effective on 2022-11-09 and the first resumed NYSE American trading
date on 2022-11-22. The frozen five-decimal ratio `0.06667` is the rounded form of `1/15`; the
authorization binds that exact stored tuple and creates no general tolerance. Envision's filing
establishes a `0.334` merger exchange conversion and first Newco trading under `EVHC` on
2016-12-02. The batch receipt has content hash
`sha256:beceafdeb0917e77ccd2c30d2bd95fd39b18e7f55e115307a36d5cb13199567e`.

Ocean Rig is the fifth exact authorization. Its issuer release establishes a 1-for-9,200 reverse
split effective on 2017-09-21. The frozen `0.00011` ratio is the five-decimal representation of
`1/9,200`, and the 2017-09-22 event date is the first frozen price bar after the issuer-effective
date. Concurrent restructuring issuance explains why the local price gap cannot validate the
split mechanically; the authorization covers only the old-share mutation, not any entitlement to
new restructuring shares. The receipt has content hash
`sha256:d5b2e24b502dffc1c059e82525c30829a657a0add8354896ed57b60f474d06ea`.

ETS1 is the sixth exact authorization. The issuer filing establishes a one-for-eight reverse split
effective on Friday, 2005-10-28. The frozen event on Monday, 2005-10-31 is the first subsequent
price bar, and its stored ratio is exactly `0.125`. No nearby companion action is recorded, so the
authorization binds only that exact instrument, event date, and ratio. The receipt has content
hash `sha256:855fdfd19c27b5cdb0250bec08fa9d443acd966c3c3b08a912d5891a0b596ce1`.

Six further plain splits complete the 12 exact authorizations. Issuer filings bind BNI's
three-for-one distribution, EPAC's two-for-one distribution, GDW's three-for-one distribution,
HAFC's and JAKK's three-for-two distributions, and LNG's one-for-four reverse split to the frozen
event date or first frozen post-distribution bar. Each has an exact scalar shareholder mutation,
no nearby companion action, and no general ratio tolerance. The batch receipt has content hash
`sha256:6342504521c9d41ce2e22eb7fd54273ba7db85ca46a3ab00a24557c52fa400da`.

Four further events bring the exact authorization set to 16. CuraGen's filing binds its
two-for-one distribution on 2000-03-30 to the first subsequent frozen bar. Wild Oats' filings
bind its three-for-two splits effected on 1998-01-07 and 1999-12-01 to their respective first
subsequent frozen bars. Intermedia's filing similarly binds its two-for-one split paid on
1998-06-15 to the 1998-06-16 frozen event. All four lack nearby companion actions. Allaire remains
quarantined because its filing confirms the split and record date but does not establish the exact
distribution or trading-effective date needed to bind the frozen event. The batch receipt has
content hash `sha256:e6885c1f1b355f5fb71f030a0edb9d21baf3a5bacd07de0ce99f38f0ea435a1c`.

UTI Energy is the 17th exact authorization. Its filing states that the board authorized a
two-for-one stock split in the form of a stock dividend, paid on 2000-10-03 to holders of record
on 2000-09-25. The issuer payment date, frozen event date, and stored ratio `2.0` agree exactly,
and there is no nearby companion action. The receipt has content hash
`sha256:4fd9b0d804c589bbf619ab89ed1146a57d8a6448911cc847da1bcdead781533a`.

Three further events bring the exact authorization set to 20. McLeodUSA's filings bind its
two-for-one distribution on 1999-07-26 and three-for-one distribution effective 2000-04-24 to
their respective first subsequent frozen bars. Metzler's filing binds its three-for-two stock
dividend directly to 1998-04-01. The separate NCI1 event on 1998-04-02 is not authorized because
the issuer describes only the April 1 action. The exact batch receipt has content hash
`sha256:61f151501bd8c35b483517399632062aeea7e48938129ee6b91fbe373aa6bbf3`.

Five further plain events bring the exact authorization set to 25. Beyond.com and Network
Commerce each completed one-for-15 reverse splits on their frozen event dates. Worldwide Xceed
completed a one-for-10 reverse split on its frozen date. ACE Limited's three-for-one distribution
and Cellular Communications International's three-for-two distribution bind to their respective
first frozen post-distribution bars. Each stored ratio is the exact issuer ratio or its explicit
five-decimal representation, and none has nearby companion-action context. The batch receipt has
content hash `sha256:3fe329129db627a4fa26b3a6f51d75ddc70ac77d5857f788de68c399b08384ac`.

Twelve composite share mutations are issuer-verified but not executable. ITT completed a one-for-two
reverse split after distributing Exelis and Xylem; Sabra's REIT conversion delivered one Sabra
share for every three Old Sun shares; NorthStar completed a one-for-two reverse split alongside
its asset-management separation; IHG exchanged 11 new shares for every 15 old shares plus £1.65
cash per old share; and Tyco completed a one-for-four reverse split immediately after distributing
Tyco Electronics and Covidien. CMO paired its one-for-two reverse split with a $7.30 special cash
dividend on the same ex-date. ATNI's `0.4` share mutation accompanied one Emerging Communications
share per old share, while KSU's one-for-two reverse split accompanied two Stilwell shares per old
share. KMI1's three-for-two split was distributed concurrently with a cash dividend that is absent
from the frozen actions feed. AT&T's one-for-five reverse split followed its same-day Broadband
spin-off and Comcast-share distribution. Redback's approximate 73.39:1 reverse split accompanied
new creditor equity and stockholder warrants under its bankruptcy plan. Sodexho Marriott's
one-for-four reverse split was part of Marriott's spin-off and merger transaction: each old share
also received one share in each of two New Marriott classes, and the issuer completed the
transaction four days after the frozen event date. Applying only the share mutation would corrupt
shareholder value, so all 12 remain composite-action quarantines. The
receipt has content hash
`sha256:e1d1d9fb384877b52199e86d0924e126b4eb208a7a9382ef3c9fc2aa5e60334b`.

Sixteen records remain hard quarantined because primary issuer evidence conflicts with the frozen
event semantics. GEVA's one-for-five effective date differs from the stored event date; MHGVY's
filing says each ADS represented one ordinary share rather than the stored `0.1`; DIAL1's
200-for-one reverse split became effective before the frozen event date; and PRTK's one-for-five
mutation occurred inside a merger that also issued `0.14134` shares per target share, before the
frozen event date. IPAR, USB, and CDR have issuer distribution or occurrence dates that differ
from their frozen events. NVEC's stored one-for-five mutation occurred inside a merger that also
issued 3.5 surviving-company shares per acquired-company share, before the frozen event date.
NCI1's April 2 row duplicates the issuer's single April 1 stock dividend. Peregrine's issuer filing
binds its old-to-new equity conversion to the August 7 reorganization effective date and states
that new stock traded from August 8, not the frozen October 17 event date. Ambev's issuer filing
places its one-for-five share conversion and stock bonus on May 31, not the frozen June 9 event.
Eni's filing places its two-for-one reverse split and ADS-ratio change on June 18, not the frozen
June 22 event. EXMCQ's filing shows stable shares outstanding across the alleged split window and
identifies `0.05` as a rights-offering exercise price rather than a share mutation. None is
executable as a plain split. Atlas Air's issuer filing reports 19,815,338 shares at 2005 year-end
and 20,049,108 at 2006 Q2, contradicting the frozen six-for-one mutation. Alcon's filing reports
308,519,051 shares at 2003 year-end and 305,654,454 at 2004 year-end, contradicting the frozen
one-for-ten mutation. Arizona Aircraft Spares' filing states that the public company was
incorporated in December 2000 and that `AZAA` trading began on 2003-10-01; the frozen 2000-11-10
event predates both the issuer and ticker lifecycle. None of the three additions authorizes a
ratio repair. The conflict receipt has content hash
`sha256:fa5c744c0268e1c05c32d3fbfd286db01073a9e1a6367331ca908dae04145395`.

Six records are resolved in the opposite direction. BASXQ, TDW, CIVI, KEGX, EGLE2, and CQB all cross
bankruptcy or recapitalization boundaries where old equity was canceled and replacement value
included a new CUSIP, warrants, aggregate ownership allocations, new shares, or combinations of
those instruments. Chiquita's old preferred, preference, and common stock was exchanged for an
aggregate new-equity allocation plus seven-year warrants. A scalar stored ratio is not a complete
supported old-to-new shareholder conversion for any of the six. Each row is preserved in lineage and routed as a non-executable
lifecycle discontinuity; a simulated position crossing one must abort. The receipt has content
hash `sha256:af66b2190bc8aac83320d7ff7b8b540d57372698bd8a6d9cfde96f668d7f44dc`.

## Corrected zero-trial reproduction

A trial-specific authorization bound the corrected lake, failed global split status, lifecycle
accounting, sealed-path exposure, exact issuer events, and execution-code hashes before returns
were reopened. One reproduction of the immutable `single_operating_margin` identity then ran in a
new content-addressed directory. It spent zero hypotheses and left the historical result and
experiment ledger unchanged.

| Measurement | Immutable result | Corrected reproduction |
|---|---:|---:|
| Annualized Sharpe | -0.4173809363 | -0.1457641219 |
| Maximum drawdown | 39.62348332% | 24.46692315% |
| Final equity | $63,911.65 | $84,805.92 |
| Total return | Not separately sealed | -15.19408261% |

The correction removes a material distortion, but it does not rescue the factor: Sharpe, CAGR,
and total return remain negative. The verdict remains **KILL**. The sealed reproduction receipt
has content hash
`sha256:04c000216be3ba13f1ba3e196d8543e77ff1f18a876753005c6b13a7b856ed0f`.

## Claim boundary and next decision

This study reconstructs corporate-action data and reports one corrected reproduction of an
already-spent identity. It spends no new strategy hypothesis and establishes no sleeve,
live-performance, capacity, or forward-performance result. The global split gate remains failed;
future identities may not treat this lake as globally valid while two events remain genuinely
unresolved. A runner may bind only an explicitly sealed exact authorization and must abort on any
other exposed failed event. Unmatched records cannot be made green by deletion.

Primary issuer and schema references:

- [Apple dividend history](https://investor.apple.com/dividend-history/default.aspx)
- [Apple 2020 dividend filing](https://www.sec.gov/Archives/edgar/data/320193/000032019320000050/a8-kexhibit991q2202032.htm)
- [Sharadar equity-prices documentation](https://sharadar.com/docs/stocks)
- [Sharadar corporate-actions documentation](https://sharadar.com/docs/actions)
- [ADTX reverse-split filing](https://www.sec.gov/Archives/edgar/data/1726711/000121390022061276/ea166672-8k_aditxt.htm)
- [SPCE reverse-split filing](https://www.sec.gov/Archives/edgar/data/1706946/000119312524159991/d829568d8k.htm)
- [AMPE reverse-split and trading-resumption filing](https://www.sec.gov/Archives/edgar/data/1411906/000155837022018084/ampe-20221117xex99d1.htm)
- [EVHC merger conversion and first-trading-date filing](https://www.sec.gov/Archives/edgar/data/1678531/000167853117000044/evhc-2016123110k.htm)
- [Basic Energy Services emergence filing](https://www.sec.gov/Archives/edgar/data/1109189/000110918916000402/basic-form8xkforemergence.htm)
- [Basic Energy Services new-equity trading notice](https://www.sec.gov/Archives/edgar/data/1109189/000110918916000402/exh992201623pressrelease.htm)
- [Ocean Rig restructuring and reverse-split release](https://www.sec.gov/Archives/edgar/data/1447382/000091957417006882/d7659156_ex99-1.htm)
- [Tidewater emergence filing](https://www.sec.gov/Archives/edgar/data/98222/000119312517242513/d431632d8k.htm)
- [Tidewater new-equity trading notice](https://www.sec.gov/Archives/edgar/data/98222/000119312517242513/d431632dex992.htm)
- [Bonanza Creek emergence filing](https://www.sec.gov/Archives/edgar/data/1509589/000095010317004047/dp75602_8k.htm)
- [Key Energy emergence filing](https://www.sec.gov/Archives/edgar/data/318996/000119312516794624/d313262d8k.htm)
- [Key Energy restructuring allocation](https://www.sec.gov/Archives/edgar/data/318996/000119312516794624/d313262dex991.htm)
- [Eagle Bulk emergence filing](https://www.sec.gov/Archives/edgar/data/1322439/000143774914018448/egle20141015_8k.htm)
- [ITT spinoff and reverse-split filing](https://www.sec.gov/Archives/edgar/data/216228/000095012311095346/y93291e8vk.htm)
- [Sabra REIT conversion filing](https://www.sec.gov/Archives/edgar/data/1492298/000119312510261436/d8k.htm)
- [NorthStar reverse-split disclosure](https://www.sec.gov/Archives/edgar/data/1273801/000127380114000061/nrf0630201410-q.htm)
- [IHG scheme share exchange and cash consideration](https://www.sec.gov/Archives/edgar/data/858446/000115697305000999/u49002e6vk.htm)
- [Tyco distributions and reverse-split disclosure](https://www.sec.gov/Archives/edgar/data/833444/000110465907052190/a07-17393_3ex99d1.htm)
- [GEVA reverse-split filing](https://www.sec.gov/Archives/edgar/data/911326/000119312511294917/d251415d8k.htm)
- [MHGVY ADS-ratio filing](https://www.sec.gov/Archives/edgar/data/1578526/000110465914032214/a14-11076_120f.htm)
- [DIAL1 reverse-split filing](https://www.sec.gov/Archives/edgar/data/771950/000095012309035313/c89015e10vq.htm)
- [PRTK merger and reverse-split filing](https://www.sec.gov/Archives/edgar/data/1178711/000119312509020145/d8k.htm)
- [ETS1 reverse-split filing](https://www.sec.gov/Archives/edgar/data/846909/000095013505006345/b57408ene10vq.htm)
- [HAFC stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/1109242/000091205701539508/a2062901z10-q.htm)
- [JAKK stock-dividend filing](https://www.sec.gov/Archives/edgar/data/1009829/000095014899002339/0000950148-99-002339.txt)
- [LNG reverse-split filing](https://www.sec.gov/Archives/edgar/data/3570/000119312504049308/d10k.htm)
- [BNI stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/934612/000093461298000017/0000934612-98-000017.txt)
- [EPAC stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/6955/000095013198002327/0000950131-98-002327.txt)
- [GDW stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/42293/000004229300000009/0000042293-00-000009.txt)
- [CuraGen stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/1030653/000092701600001788/0000927016-00-001788.txt)
- [Wild Oats 1998 stock-split filing](https://www.sec.gov/Archives/edgar/data/909990/000092735698000444/0000927356-98-000444.txt)
- [Wild Oats 1999 stock-split filing](https://www.sec.gov/Archives/edgar/data/909990/000089973300000020/0000899733-00-000020.txt)
- [Intermedia stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/885067/000095014498009211/0000950144-98-009211.txt)
- [UTI Energy stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/912899/000095012900005078/0000950129-00-005078.txt)
- [ATNI split-off filing](https://www.sec.gov/Archives/edgar/data/879585/000095013098001580/0000950130-98-001580.txt)
- [K N Energy split and concurrent-dividend filing](https://www.sec.gov/Archives/edgar/data/54502/000095013499001524/0000950134-99-001524.txt)
- [KSU Stilwell distribution and reverse-split filing](https://www.sec.gov/Archives/edgar/data/54480/000005448000000020/0000054480-00-000020.txt)
- [McLeodUSA 1999 stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/919943/000092838599002618/0000928385-99-002618.txt)
- [McLeodUSA 2000 stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/919943/000092838500001564/0000928385-00-001564.txt)
- [Metzler three-for-two stock-dividend filing](https://www.sec.gov/Archives/edgar/data/1019737/000095013198002261/0000950131-98-002261.txt)
- [Beyond.com reverse-split filing](https://www.sec.gov/Archives/edgar/data/1060531/000109581101504316/f74865e10-q.htm)
- [Network Commerce reverse-split filing](https://www.sec.gov/Archives/edgar/data/1087879/000113724301500051/form10qnci.txt)
- [Worldwide Xceed reverse-split filing](https://www.sec.gov/Archives/edgar/data/721176/000091205701508952/a2045655z10-q.txt)
- [ACE three-for-one split filing](https://www.sec.gov/Archives/edgar/data/896159/000090256198000175/0000902561-98-000175.txt)
- [Cellular Communications International stock-dividend filing](https://www.sec.gov/Archives/edgar/data/870762/000087076298000021/0000870762-98-000021.txt)
- [CMO special-dividend and reverse-split filing](https://www.sec.gov/Archives/edgar/data/766701/000095013401503792/d88804e8-k.txt)
- [CDR stock-split filing](https://www.sec.gov/Archives/edgar/data/761648/000095012303009594/y88871sv11.htm)
- [IPAR stock-dividend split filing](https://www.sec.gov/Archives/edgar/data/822663/000093041301501460/c22238_10q.txt)
- [NVEC merger and reverse-split filing](https://www.sec.gov/Archives/edgar/data/724910/000091205700052325/a2032378z8-k.txt)
- [USB stock-split filing](https://www.sec.gov/Archives/edgar/data/36104/000104746999007568/0001047469-99-007568.txt)
- [AT&T Broadband spin-off and reverse-split filing](https://www.sec.gov/Archives/edgar/data/5907/000095012303003510/e84804e10vk.txt)
- [Redback bankruptcy securities and reverse-split filing](https://www.sec.gov/Archives/edgar/data/1081290/000119312504042090/d10k.htm)
- [Marriott spin-off, merger, and one-for-four reverse-split filing](https://www.sec.gov/Archives/edgar/data/1048286/000092838598000674/0000928385-98-000674.txt)
- [Peregrine reorganization conversion and trading-date filing](https://www.sec.gov/Archives/edgar/data/1031107/000104746904014838/a2134573z10-k.htm)
- [Ambev share conversion and stock-bonus filing](https://www.sec.gov/Archives/edgar/data/1113172/000114420407063976/v089496_20-f.htm)
- [Eni reverse-split and ADS-ratio filing](https://www.sec.gov/Archives/edgar/data/1002242/000131143505000018/sj0605en20f2.htm)
- [EXMCQ shares-outstanding and rights-offering filing](https://www.sec.gov/Archives/edgar/data/725282/000072528298000006/0000725282-98-000006.txt)
- [Atlas Air shares-outstanding filing](https://www.sec.gov/Archives/edgar/data/1135185/000093041306005893/c43889_10-q.htm)
- [Alcon shares-outstanding filing](https://www.sec.gov/Archives/edgar/data/1167379/000116737905000020/acl20f2004.htm)
- [Arizona Aircraft Spares formation and trading-history filing](https://www.sec.gov/Archives/edgar/data/1141880/000109432804000079/arizona10ksb041404woex.txt)
- [Chiquita reorganization equity-and-warrant filing](https://www.sec.gov/Archives/edgar/data/101063/000102140802003831/d10k.txt)
