# AlphaTrend open/high/low continuation

Implemented `forward_wealth_ohlc_v1` separately from the frozen candidate. Each
raw price p in a session is mapped using the previous close state and effective
actions:

`X(p) = previous_index * (new_shares_per_old * p + cash_per_old) / previous_raw_close`

The close equals `forward_close_reinvestment_v1` exactly. The open, high and low
do not use the current session's close. This avoids a tempting but inappropriate
open mapping that would multiply today's open by a factor calculated from today's
closing price. These are synthetic wealth coordinates, not executable quotes or
Yahoo-adjusted bars. Ex-session cash is incorporated into the index; the broker
ledger's payment-date accounting is a separate concern.

On all 238 retained continuation bars (17 ETFs, 14 sessions), closes exactly match
the previous bridge and OHLC ordering holds. Replacing each current close with
its raw low and raw high leaves mapped open/high/low unchanged: 476 checks. These
checks show current-close independence, not full historical publication validity.
Reference snapshots were collected after the historical sessions, so all real-data
mapping is explicitly DIAGNOSTIC_CURRENT_VINTAGE, never prospective evidence.

62 tests passed across OHLC/close bridges, historical/daily capture, producer and
journal. The eight OHLC cases check cash and split mapping, current-close
independence, invalid bars and late snapshot rejection. Module and unit-test Ruff
checks pass. The diagnostic runner has one cosmetic I001 import-order warning;
its already evidence-bound source is preserved. No changes to production, frozen
candidate inputs, observation epochs or broker state. No new strategy returns,
new hypothesis or sleeve admission; union remains 238.

Next: verify the forward-return label convention using synthetic event paths and
raw holding-period wealth, retaining the causal exit-session release. Then define
a separately registered candidate for this price convention before measuring
strategy returns. This bridge does not establish exact Yahoo parity or repair the
historical prefix's point-in-time provenance. The verified-clock and real account
context requirements remain in force before prospective activation.
