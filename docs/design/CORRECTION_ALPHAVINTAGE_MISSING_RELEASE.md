# AlphaVintage missing-release correction protocol

**Declared:** 2026-08-16  
**Status:** REVISED RETURNS SEALED / VERDICT KILLED  
**Hypothesis-ledger impact:** zero new hypotheses; this repairs an existing identity.

## Confirmed defect

The point-in-time RTDSM lake has no October 2025 headline or core CPI level.  The December 15,
2025 vintage contains November, but its immediately preceding October level is null.  The locked
signal function computed monthly log differences, dropped null differences, and selected the last
remaining difference as the newly released surprise.  Consequently an older computable change
could be repeated under a later vintage date even though no new month-over-month CPI change was
computable.  This is fail-open behavior and can splice a stale signal into a new holding period.

## Correction locked before revised performance

For every monthly vintage dated `V`:

1. The newly released observation must be the calendar month immediately preceding `V`.
2. That observation and its immediately preceding calendar month must both exist and be finite.
3. If either check fails, the vintage emits no signal.  No fill, interpolation, carry-forward, or
   substitution is permitted.
4. Interior gaps remain missing; only adjacent finite monthly changes enter the AR history.
5. The signal may resume only when two adjacent latest monthly levels exist again.

The live writer imports the research signal function directly, so this one correction governs
both paths.  Regression tests must pin the exact November-present/October-missing shape before any
revised curve is generated.

## Re-evaluation rule

After code and tests pass, regenerate the existing AlphaVintage result once under the corrected
data rule.  Do not tune AR lags, sign, clip, costs, entry timing, instruments, scale, or gates.  The
revised result replaces the invalid result whether it improves or worsens.  Publish the before/after
metrics, changed vintage count, curve hash, code hash, and unchanged hypothesis count.  If any
admission gate no longer clears, remove the sleeve from research-validated/book arithmetic; do not
respecify it.

## Calendar-integrity defect found during re-evaluation

The prior curve persisted only `net[w.abs() > 0]`. That deleted zero-exposure trading sessions
inside the first-to-last activity window, including the monthly transition dates. An active-day
sample is not a portfolio return calendar and inflates annualization. The corrected curve retains
every trading session between first and last exposure and records an explicit zero when the sleeve
has no position. No return-bearing observation was added, removed, or tuned.

## Sealed outcome

The unchanged identity was regenerated once after both corrections. Calendar-correct net Sharpe is
`0.2298358829`, Newey-West t is `1.2673190577`, and maximum drawdown is approximately `-25.1%`
over 6,296 portfolio sessions (5,998 active sessions). The superseded active-day Sharpe was
`0.3382071994`. Gate `b_nw_t_ge_1p5` fails, so the final preregistered verdict is `KILLED` and
AlphaVintage is not research-admitted. This correction adds zero hypotheses.

- Curve SHA-256: `d277c63ddf2bed6e9314aa863dbbf6adf3f4adb55bd89e8166aee4a19aab415f`
- Result SHA-256: `686654b4617efb8322f6fda37f2e71a375423aecc6de03477a0186cf2844e509`
- Runner SHA-256: `80b55488c7caab97dcf121c7d0f744a05d80981f75aaa6529dc17613808c48ed`
