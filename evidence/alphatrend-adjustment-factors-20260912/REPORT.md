# AlphaTrend expanded adjustment-factor audit

One bounded raw SIP GET returned 234 validated bars: 78 sessions each for IEF,
SHY and TLT, May 1–August 21, 2026. Each is paired one-to-one with the frozen
Yahoo-adjusted history. No missing rows, pagination or duplicate keys.

| ETF | Minimum adjusted/raw close ratio | Maximum absolute daily-return difference |
| --- | ---: | ---: |
| IEF | 0.989975 | 34.28 bp |
| SHY | 0.991114 | 30.62 bp |
| TLT | 0.988435 | 40.25 bp |

All three exhibit factor changes exceeding one basis point on June 1, July 1
and August 3. The pattern is consistent with the historical loader's declared
adjustment convention. It is not an authenticated corporate-action record or
proof of the exact adjustment calculation. Other small provider differences
remain, including a maximum SHY ratio slightly above one.

A constant scale factor or simply appending raw prices would not preserve the
historical total-return convention across these transitions. This audit therefore
leaves the splice blocked. It measures underlying price-series differences, not
portfolio returns or candidate performance. No new hypothesis; union 238.

Exact response bytes, local receipt metadata, normalized bars, paired overlap,
source/input hashes and descriptive statistics are retained in this directory.
Local capture timing is not historical publication timing. See the
[continuation requirements](../alphatrend-history-bridge-20260912/REPORT.md).
