# Crypto carry cadence: candidate rationale and synthetic validation

The baseline has one factor,carry_fund_21. Its trailing21settlement mean is annualized using funding_interval_hours from metadata modeled as applicable across all history. Blend-label changes alone cannot alter single-factor blend weights.

The frozen source diagnostic inspected230,505retained funding rows for51identities, including context outside evaluation. During2023–June1 2026, observed adjacent settlement gaps differ materially from metadata for three instruments: AXS3,547/4,306gaps (metadata4h), BLZ2,776/3,556(metadata8h), REEF588/2,552(metadata8h). The other48identities have no gap mismatch above1second in this screen. This is a sourcecadence diagnostic, not evidence of complete exchange schedules or actualhistorical metadata.

An isolated helper computes trailing carry per observed elapsed hour from21payments and22publishedsettlements, with a1–8hour gap screen. Eight synthetic tests passed: exactfixed1/4/8hour equivalence, mixedcadence arithmetic, futurepublication exclusion, insufficienthistory, duplicate andlargegap handling. Original feature, settings, sourcefiles and historicalreturns remain unchanged. No candidatehistoricalfeatures or returntrial was computed.

First diagnostic attempt assumed integer timestamps and failed on pandasTimedelta arithmetic; source/error retained in the originaldirectory. Version2 explicitly converts datetimeUTC to millisecondintegers. No originalrun or failedattempt was overwritten. Allv2sourcebindings verify.

Next integrate the helper as an isolatedfeature with sufficientcontext and asofpublication parity tests; then reserve normal/stress returnidentities beforehistoricalcandidatecomputation. Combinedgates and stoprule are frozen inEXPERIMENT_SPEC.json. No window orcadenceparameter sweep. Existingcombinedexcess.406954normal/.079523stress remains unchanged. This is a corecorrectionhypothesis, not anewdistinctsleeve;15+qualifiedsleeves stillrequired. Mergerexpansion remainsparked.
