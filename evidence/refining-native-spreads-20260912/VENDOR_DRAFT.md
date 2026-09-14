# Draft only — not sent

Subject: Legacy GLBX crack-spread leg-side normalization and regeneration status

Our downloaded 2015-01-15 GLBX.MDP3 definitions show both legs as A for the two same-month crack instruments in vendor_reproduction.json. The attached reproduction identifies publisher/instrument IDs, leg identities, ratios, timestamps and the original file SHA-256. Equivalent 2020 and 2025 crack definitions have product B and crude A.

Your MDP2 multi-leg issue describes an always-A leg_side defect, reversed leg ordering and negative-price parsing concerns. Can you confirm whether these records are affected, which historical intervals/products require regeneration, and how clients can identify corrected files? Please also confirm the normalized crack quote multiplier and any related MBP-1 price corrections required before cost reconstruction.

We have preserved the originals and blocked the legacy route rather than changing sides from the symbol name.
