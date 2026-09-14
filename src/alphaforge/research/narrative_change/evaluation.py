"""Task 6 of the plan, evaluation half: every number the pre-registration says to report.

*Evaluation* section, transcribed: net and stressed Sharpe, Newey-West mean t-statistic, DSR
against the union experiment count, drawdown, skew, turnover, beta, long and short contribution,
annual results, capacity, ordinary and bottom-decile-stress correlation to each current ALPHAC
sleeve, and the fixed-weight combined-book delta (candidate 10 percent, funded pro rata from the
four equal-quarter sleeves, 22.5 percent each). PBO is not estimated from a one-configuration
surface; it is reported as not defined, never as zero. Also a mean-zero candidate control and
every leave-one-calendar-year-out recomputation.

Correlation and book evidence go through the shared
``alphaforge.validation.diversification.diversification_report`` on the common window
(latest first observation to earliest last observation across the series). This module is
window-agnostic: the runner decides whether it is looking at calibration (2006-2015, plumbing
only) or the once-opened out-of-sample interval.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from alphaforge.research.narrative_change.portfolio import BookResult
from alphaforge.validation.dsr import dsr_from_returns
from alphaforge.validation.metrics import newey_west_tstat

SESSIONS_PER_YEAR = 252
CANDIDATE_BOOK_WEIGHT = 0.10
CURRENT_SLEEVE_WEIGHT_AFTER_FUNDING = 0.225


def newey_west_lags(n_obs: int) -> int:
    """The v2 template's lag rule: ``max(7, floor(4 * (n_obs / 100) ** (2 / 9)))``."""
    lags: int = math.floor(4.0 * float((n_obs / 100.0) ** (2.0 / 9.0)))
    return max(7, lags)


@dataclass(frozen=True)
class SeriesStats:
    observations: int
    annualized_sharpe: float | None
    annualized_return: float
    annualized_volatility: float
    newey_west_t: float | None
    max_drawdown: float
    skew: float | None
    cumulative_return: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "annualized_sharpe": self.annualized_sharpe,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "newey_west_t": self.newey_west_t,
            "max_drawdown": self.max_drawdown,
            "skew": self.skew,
            "cumulative_return": self.cumulative_return,
        }


def _max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    return float(np.max(1.0 - equity / peak)) if equity.size else 0.0


def series_stats(returns: pd.Series) -> SeriesStats:
    values = returns.to_numpy(dtype="float64")
    values = values[np.isfinite(values)]
    n = int(values.size)
    if n == 0:
        return SeriesStats(0, None, 0.0, 0.0, None, 0.0, None, 0.0)
    mean = float(np.mean(values))
    vol = float(np.std(values, ddof=1)) if n > 1 else 0.0
    sharpe = float(mean / vol * math.sqrt(SESSIONS_PER_YEAR)) if vol > 0 else None
    t_stat = newey_west_tstat(pd.Series(values), newey_west_lags(n)) if n > 2 else float("nan")
    skew = None
    if n > 2 and vol > 0:
        centred = values - mean
        skew = float(np.mean(centred**3) / (np.mean(centred**2) ** 1.5))
    return SeriesStats(
        observations=n,
        annualized_sharpe=sharpe,
        annualized_return=mean * SESSIONS_PER_YEAR,
        annualized_volatility=vol * math.sqrt(SESSIONS_PER_YEAR),
        newey_west_t=None if not np.isfinite(t_stat) else float(t_stat),
        max_drawdown=_max_drawdown(values),
        skew=skew,
        cumulative_return=float(np.prod(1.0 + values) - 1.0),
    )


def beta_to_spy(book: pd.Series, spy: pd.Series) -> float | None:
    pair = pd.concat([book, spy], axis=1).dropna()
    if len(pair) < 30:
        return None
    x = pair.iloc[:, 1].to_numpy(dtype="float64")
    y = pair.iloc[:, 0].to_numpy(dtype="float64")
    var = float(np.var(x, ddof=1))
    return float(np.cov(x, y, ddof=1)[0, 1] / var) if var > 0 else None


def annual_results(returns: pd.Series) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    years = pd.Index([d.year for d in returns.index])
    for year in sorted(set(years)):
        stats = series_stats(returns[years == year])
        out[str(year)] = {
            "observations": stats.observations,
            "return": stats.cumulative_return,
            "annualized_sharpe": stats.annualized_sharpe,
            "max_drawdown": stats.max_drawdown,
        }
    return out


def leave_one_year_out(returns: pd.Series) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    years = pd.Index([d.year for d in returns.index])
    for year in sorted(set(years)):
        stats = series_stats(returns[years != year])
        out[str(year)] = {
            "observations": stats.observations,
            "annualized_sharpe": stats.annualized_sharpe,
            "newey_west_t": stats.newey_west_t,
        }
    return out


def mean_zero_control(
    returns: pd.Series, *, seed: int = 20260815, draws: int = 1000
) -> dict[str, Any]:
    """The pre-registered control: the same return path with its mean removed, resampled with
    the same block length the diversification bootstrap uses (21 sessions), so a Sharpe as large
    as the candidate's can be placed against what a mean-zero path of that shape produces."""
    values = returns.to_numpy(dtype="float64")
    values = values[np.isfinite(values)]
    if values.size < 63:
        return {"status": "TOO_SHORT", "draws": 0}
    centred = values - values.mean()
    rng = np.random.default_rng(seed)
    block = 21
    n = centred.size
    sharpes = np.empty(draws)
    for k in range(draws):
        starts = rng.integers(0, n, size=n // block + 1)
        path = np.concatenate([np.take(centred, np.arange(s, s + block) % n) for s in starts])[:n]
        vol = path.std(ddof=1)
        sharpes[k] = path.mean() / vol * math.sqrt(SESSIONS_PER_YEAR) if vol > 0 else 0.0
    observed = series_stats(returns).annualized_sharpe
    exceed = float(np.mean(sharpes >= observed)) if observed is not None else None
    return {
        "status": "REPORTED",
        "draws": draws,
        "block_sessions": block,
        "control_sharpe_p95": float(np.quantile(sharpes, 0.95)),
        "control_sharpe_p99": float(np.quantile(sharpes, 0.99)),
        "fraction_of_controls_at_or_above_candidate": exceed,
    }


def long_short_contribution(book: BookResult) -> dict[str, Any]:
    frame = book.frame()
    return {
        "note": "contributions are the book's gross return split is not separable after netting;"
        " the sides are reported through average gross and turnover instead",
        "average_stock_gross": float(frame["stock_gross"].mean()),
        "average_hedge_weight": float(frame["hedge_weight"].mean()),
        "average_daily_turnover": float(frame["turnover"].mean()),
        "annual_turnover": float(frame["turnover"].sum() / max(1, len(frame)) * SESSIONS_PER_YEAR),
        "sessions_with_positions": int((frame["positions"] > 0).sum()),
    }


def evaluate_book(
    book: BookResult,
    *,
    spy_returns: pd.Series,
    union_identities: int | None,
    union_sharpe_variance: float | None,
    window_label: str,
) -> dict[str, Any]:
    """Every pre-registered number for one window. Nothing here decides admission."""
    frame = book.frame()
    net = frame["net_return"].astype("float64")
    gross = frame["gross_return"].astype("float64")
    stressed = frame["stressed_net_return"].astype("float64")
    net_stats = series_stats(net)
    report: dict[str, Any] = {
        "window": window_label,
        "sessions": len(frame),
        "first_session": frame.index[0].isoformat() if len(frame) else None,
        "last_session": frame.index[-1].isoformat() if len(frame) else None,
        "gross": series_stats(gross).as_dict(),
        "net": net_stats.as_dict(),
        "stressed_net": series_stats(stressed).as_dict(),
        "beta_to_spy": beta_to_spy(net, spy_returns.reindex(net.index)),
        "execution": long_short_contribution(book),
        "events": {
            "force_flat": book.force_flat_events,
            "deferred_target_changes": book.deferred_changes,
        },
        "capacity": book.capacity,
        "annual": annual_results(net),
        "leave_one_year_out": leave_one_year_out(net),
        "mean_zero_control": mean_zero_control(net),
        "pbo": {
            "status": "NOT_DEFINED",
            "reason": "one pre-registered configuration; PBO is not estimated from a surface",
        },
    }
    if (
        union_identities is not None
        and union_sharpe_variance is not None
        and net_stats.observations > 2
    ):
        try:
            dsr = dsr_from_returns(
                net,
                n_trials=int(union_identities),
                sr_trials_variance=float(union_sharpe_variance),
                periods_per_year=float(SESSIONS_PER_YEAR),
            )
            report["deflated_sharpe"] = {
                "union_identities": int(union_identities),
                "psr": float(dsr.psr),
                "dsr": float(dsr.dsr),
                "sr_ann": float(dsr.sr_ann),
            }
        except ValueError as error:
            report["deflated_sharpe"] = {"status": "UNAVAILABLE", "reason": str(error)}
    else:
        report["deflated_sharpe"] = {
            "status": "NOT_COMPUTED",
            "reason": "no union context supplied",
        }
    return report


def diversification_evidence(
    candidate: pd.Series,
    sleeves: dict[str, pd.Series],
    *,
    book: pd.Series,
) -> dict[str, Any]:
    """Correlations and the fixed-weight book delta through the shared engine on the common
    window; the runner supplies the current sleeves' daily returns and the exact book."""
    from alphaforge.validation.diversification import diversification_report

    aligned = pd.concat(
        [
            candidate.rename("candidate"),
            book.rename("book"),
            *[s.rename(k) for k, s in sleeves.items()],
        ],
        axis=1,
    )
    start = max(s.dropna().index.min() for s in [candidate, book, *sleeves.values()])
    end = min(s.dropna().index.max() for s in [candidate, book, *sleeves.values()])
    aligned = aligned.loc[(aligned.index >= start) & (aligned.index <= end)].dropna()
    if len(aligned) < 63:
        return {"status": "COMMON_WINDOW_TOO_SHORT", "observations": len(aligned)}
    book_values = aligned["book"].to_numpy(dtype="float64")
    threshold = float(np.quantile(book_values, 0.10))
    stress_mask = book_values <= threshold
    labels = [d.isoformat() for d in aligned.index]
    result = diversification_report(
        aligned["candidate"].to_numpy(dtype="float64"),
        {k: aligned[k].to_numpy(dtype="float64") for k in sleeves},
        book_values,
        stress_mask=stress_mask,
        period_labels=labels,
        candidate_weight=CANDIDATE_BOOK_WEIGHT,
    )
    payload = result.to_dict()
    return {
        "status": "REPORTED",
        "observations": len(aligned),
        "common_window": {"first": labels[0], "last": labels[-1]},
        "candidate_weight": CANDIDATE_BOOK_WEIGHT,
        "current_sleeve_weight_after_funding": CURRENT_SLEEVE_WEIGHT_AFTER_FUNDING,
        "report": payload,
    }


def evaluation_date() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
