"""Attribute the retained historical control; no new allocation variants."""

import glob
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from alphaforge.portfolio.book import SleeveCurve, combine_book
from alphaforge.portfolio.market_factor import DEFAULT_MIX, market_factor_by_epochday

ROOT = Path(__file__).resolve().parents[1]
PROD = Path("/Users/arhancanli/alphaforge")
OUT = ROOT / "evidence/alphac-algorithm-contributions-20260913"
FROZEN = ROOT / "evidence/combined-baseline-audit-20260912/sources"


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT / "result.json").exists():
        raise FileExistsError("preserve completed research packet")
    prior = json.loads(
        (FROZEN / "artifacts/analysis/current_book_diversification/result.json").read_text()
    )
    curves = []
    bindings = {}
    for relative, expected in prior["source_bindings"]["sleeve_equity_inputs"].items():
        path = FROZEN / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        name = "alphavintage_live" if "/probe/" in relative else Path(relative).parent.name
        frame = pd.read_parquet(path)
        curves.append(SleeveCurve(name, frame.ts.tolist(), frame.equity.tolist()))
        bindings[str(path)] = expected
    mix = [(name, weight, str(PROD / pattern)) for name, weight, pattern in DEFAULT_MIX]
    corpus = [
        {
            "path": str(Path(p).relative_to(PROD)),
            "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest(),
        }
        for p in sorted({p for _, _, pattern in mix for p in glob.glob(pattern, recursive=True)})
    ]
    corpus_hash = hashlib.sha256(
        json.dumps(corpus, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    book = combine_book(
        curves,
        scheme="fixed",
        fixed_weights=prior["configuration"]["weights"],
        trading_days=365,
        strategic_tilt_pct=0.1,
        strategic_tilt_market=market_factor_by_epochday(mix),
    )
    print("Rebuilt Sharpe:", book.sharpe, "days:", book.n_days, "corpus hash:", corpus_hash)
    prior_sharpe = prior["observed"]["full_book_sharpe_research_simulation_not_forward_evidence"]
    assert abs(book.sharpe - prior_sharpe) < 1e-5  # near-reproduction, not byte-identical overlay
    names = [*book.names, "strategic_overlay"]
    components = np.column_stack(
        [book.weights[n] * book.sleeve_returns[n] for n in book.names] + [book.overlay_returns]
    )
    assert np.max(np.abs(components.sum(axis=1) - book.book_returns)) < 1e-15
    wealth = np.r_[1.0, np.cumprod(1 + book.book_returns)]
    dd = wealth / np.maximum.accumulate(wealth) - 1
    trough = int(np.argmin(dd))
    peak = int(np.argmax(wealth[: trough + 1]))
    cov = np.cov(components, rowvar=False, ddof=1)
    risk_share = cov.sum(axis=1) / cov.sum()
    yearly = {}
    dates = pd.to_datetime(book.days, unit="D", origin="unix")
    for year in sorted(set(dates.year)):
        mask = dates.year == year
        yearly[str(year)] = {n: float(components[mask, i].sum()) for i, n in enumerate(names)}
    contributions = []
    for i, n in enumerate(names):
        contributions.append(
            {
                "component": n,
                "mean_contribution_ann": float(365 * components[:, i].mean()),
                "variance_share": float(risk_share[i]),
                "worst_drawdown_additive_return": float(components[peak:trough, i].sum()),
                "negative_book_days_sum": float(components[book.book_returns < 0, i].sum()),
            }
        )
    pd.DataFrame(components, index=dates, columns=names).to_csv(OUT / "baseline_components.csv")
    result = {
        "baseline_sharpe": book.sharpe,
        "prior_sharpe": prior_sharpe,
        "sharpe_reproduction_delta": book.sharpe - prior_sharpe,
        "baseline_cagr": book.cagr,
        "baseline_observed_maxdd": float(-dd.min()),
        "days": book.n_days,
        "start": str(dates[0].date()),
        "end": str(dates[-1].date()),
        "worst_drawdown_peak_boundary_index": peak,
        "worst_drawdown_trough_boundary_index": trough,
        "contributions": contributions,
        "yearly_additive_contributions": yearly,
        "source_bindings": bindings,
        "overlay_corpus": corpus,
        "overlay_corpus_matches_prior": corpus_hash
        == prior["source_bindings"]["market_factor_source_corpus"]["manifest_sha256"],
        "new_return_variants": 0,
        "qualification": False,
        "limits": "Historical known-data control; zero-gap convention, additive unfunded overlay, "
        "no cash benchmark, no COVID/2022, inherited sleeve evidence limitations. "
        "Contributions are additive simple returns, not compounded attribution.",
    }
    (OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "baseline_sharpe",
                    "baseline_cagr",
                    "baseline_observed_maxdd",
                    "days",
                    "contributions",
                    "overlay_corpus_matches_prior",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
