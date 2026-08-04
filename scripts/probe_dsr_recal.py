"""PROBE — DSR recalibration under realistic (non-IID) return dynamics.

READ-ONLY probe. Creates NEW artifacts only under ``artifacts/sweep/dsr_recal/``.
Does NOT import-and-mutate anything in ``src`` (it *reads* the deployed
``dsr.py`` / ``metrics`` functions to reproduce the live numbers byte-for-byte,
which is exactly what a golden-master-respecting probe should do).

What the deployed DSR does (src/alphaforge/validation/dsr.py, dsr_from_returns)
------------------------------------------------------------------------------
It uses the Bailey-Lopez-de-Prado / Mertens Sharpe standard error:

    Var_hat(SR) = (1 - g3*SR + ((g4-1)/4)*SR^2) / (T-1)          [g4 non-excess]

    PSR(SR*) = Phi( (SR - SR*) * sqrt(T-1)
                    / sqrt(1 - g3*SR + ((g4-1)/4)*SR^2) )

so it ALREADY corrects for skew (g3) and heavy tails (g4) via the realized 3rd
and 4th sample moments (the Mertens 2002 term). What it does NOT do: it assumes
the T daily observations are serially INDEPENDENT. It plugs the raw sample size
T into sqrt(T-1). For trend / momentum / carry sleeves the daily returns are
serially correlated (AR-type persistence) and volatility-clustered (GARCH), so
the effective number of independent observations is < T (or, if mean-reverting,
> T). The IID assumption therefore mis-sizes the standard error, and hence the
PSR / DSR gate, in EITHER direction.

The recalibration (this probe)
------------------------------
Heavy tails: kept exactly as deployed, via the realized 3rd/4th moments (the
Mertens term is left untouched — this probe does not re-derive it).

Serial correlation + vol clustering: I use an HONEST Newey-West / HAC
effective-sample-size correction rather than a claimed "Lopez-de-Prado 2025/26
closed form". Reason: I will only ship maths I can verify end-to-end here; the
HAC/GMM Sharpe standard error (Lo 2002, "The Statistics of Sharpe Ratios") is
the canonical, checkable estimator and it captures BOTH level autocorrelation
AND volatility clustering in a single long-run-covariance object. I do not
fabricate a citation I cannot reproduce.

Mechanics (Lo 2002 delta-method GMM Sharpe variance):
  Parameters theta = (mu, gamma), mu=E[r], gamma=E[r^2]; sigma^2 = gamma - mu^2,
  SR = mu / sqrt(gamma - mu^2). Per-observation moment vector:

      g_t = ( r_t - mu ,  r_t^2 - gamma )

  Gradient of SR wrt theta:
      d SR/d mu    = (1 + SR^2) / sigma
      d SR/d gamma = -SR / (2 * sigma^2)

  Contemporaneous variance (IID):  V0 = grad' Sigma0 grad   (Sigma0 = Cov(g_t))
  Long-run HAC variance (non-IID): Vhac = grad' S grad,
      S = Sigma0 + sum_{k>=1} w_k (Sigma_k + Sigma_k'),  Bartlett weights
      w_k = 1 - k/(L+1)  (Newey-West), automatic bandwidth L* per NW(1994).

  Serial-dependence inflation factor:  lambda = Vhac / V0.
  V0 reproduces the deployed Mertens term to sampling precision (verified in the
  output), so lambda is a clean MULTIPLICATIVE serial-dependence correction on
  the honest heavy-tail term:

      variance_term_recal = lambda * (1 - g3*SR + ((g4-1)/4)*SR^2)
      DSR_recal = Phi( (SR - SR*) * sqrt(T-1) / sqrt(variance_term_recal) )

  Effective sample size:  T_eff = T / lambda.  lambda>1 (persistent) shrinks the
  effective sample and LOWERS DSR; lambda<1 (mean-reverting) RAISES it.

The deflation benchmark SR* (n_trials, sr_trials_variance) is held FIXED at each
sleeve's deployed value (read from its walkforward.json validation block), so the
only thing that moves between "current" and "recalibrated" is the non-IID
standard error — which is the entire point of the probe.

Run:  uv run python scripts/probe_dsr_recal.py
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

# Read (not mutate) the deployed functions so "current" is byte-identical to live.
from alphaforge.analytics.metrics import daily_returns
from alphaforge.validation.dsr import (
    dsr_from_returns,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
)

REPO = Path(__file__).resolve().parent.parent
WF = REPO / "artifacts" / "walkforward"
OUT = REPO / "artifacts" / "sweep" / "dsr_recal"

# (label, walkforward run dir). The deployed (n_trials, sr_trials_variance) is read
# from each run's own walkforward.json validation block -> SR* held fixed.
SLEEVES: list[tuple[str, str]] = [
    ("crypto_carry (Crypto Funding Carry)", "crypto_carry_wk"),
    ("AlphaMax (US Equity Momentum k30_dn_63)", "k30_dn_63"),
    ("AlphaTrend (Managed-Futures Trend, mf_live_fwd)", "mf_live_fwd"),
]


def load_daily_returns(run: str) -> pd.Series:
    """Reproduce the EXACT daily return series the deployed DSR consumed."""
    frame = pd.read_parquet(WF / run / "equity.parquet")
    equity = pd.Series(
        frame["equity"].to_numpy(dtype="float64"),
        index=pd.Index(frame["ts"].to_numpy(dtype="int64"), name="ts"),
        name="equity",
    )
    return daily_returns(equity)


def load_deployed_validation(run: str) -> dict[str, Any]:
    j = json.loads((WF / run / "walkforward.json").read_text())
    return dict(j["validation"])


def nw_bandwidth(t: int) -> int:
    """Newey-West (1994) automatic Bartlett bandwidth  L* = floor(4 (T/100)^(2/9))."""
    return int(np.floor(4.0 * (t / 100.0) ** (2.0 / 9.0)))


def hac_long_run_cov(g: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West (Bartlett) long-run covariance of a (T, k) mean-zero moment matrix."""
    t = g.shape[0]
    s = g.T @ g / t  # Sigma0 (contemporaneous)
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        gk = g[k:].T @ g[:-k] / t  # Sigma_k
        s = s + w * (gk + gk.T)
    return s


def sharpe_variance_terms(r: np.ndarray, lag: int) -> dict[str, float]:
    """V0 (contemporaneous) and Vhac (Newey-West) for the delta-method Sharpe variance.

    Returns per-observation variance TERMS (i.e. T * Var(SR_hat)), directly
    comparable to the deployed Mertens term ``1 - g3*SR + ((g4-1)/4)*SR^2``.
    """
    mu = float(np.mean(r))
    gamma = float(np.mean(r * r))
    sigma2 = gamma - mu * mu
    sigma = float(np.sqrt(sigma2))
    sr = mu / sigma
    grad = np.array([(1.0 + sr * sr) / sigma, -sr / (2.0 * sigma2)])
    g = np.column_stack([r - mu, r * r - gamma])  # (T, 2) mean-zero moment matrix
    sigma0 = g.T @ g / g.shape[0]
    s_hac = hac_long_run_cov(g, lag)
    v0 = float(grad @ sigma0 @ grad)
    vhac = float(grad @ s_hac @ grad)
    return {"sr_per_period": sr, "v0": v0, "vhac": vhac, "lambda": vhac / v0}


def excess_kurtosis(r: np.ndarray) -> float:
    m = r - r.mean()
    return float((m**4).mean() / (m**2).mean() ** 2 - 3.0)


def autocorr(r: np.ndarray, k: int = 1) -> float:
    m = r - r.mean()
    denom = float((m * m).sum())
    return float((m[k:] * m[:-k]).sum() / denom) if denom > 0 else float("nan")


@dataclass(frozen=True)
class SleeveResult:
    label: str
    run: str
    n_obs: int
    sr_per_period: float
    sr_ann_deployed: float
    skew: float
    kurtosis_nonexcess: float
    excess_kurtosis: float
    acf1_returns: float
    acf1_abs_returns: float
    acf1_sq_returns: float
    n_trials: int
    sr_trials_variance: float
    expected_max_sr: float
    psr_current: float
    dsr_current: float
    dsr_current_reproduced: float
    nw_lag: int
    mertens_term: float
    v0_delta: float
    vhac_delta: float
    lam: float
    t_eff: float
    variance_term_recal: float
    psr_recal: float
    dsr_recal: float
    dsr_delta: float
    crosses_gate_current: bool
    crosses_gate_recal: bool
    lam_sensitivity: dict[str, float]


def analyse(label: str, run: str) -> SleeveResult:
    rets = load_daily_returns(run)
    r = np.asarray(rets.to_numpy(), dtype=np.float64)
    r = r[np.isfinite(r)]
    t = int(r.size)

    val = load_deployed_validation(run)
    n_trials = int(val["n_trials_used"])
    var_sr = float(val["sr_trials_variance"])

    # --- Reproduce the deployed DSR exactly (same series, same fixed SR*). ---
    rep = dsr_from_returns(rets, n_trials, var_sr)
    sr = rep.sr_per_period
    g3 = rep.skew
    g4 = rep.kurtosis  # non-excess
    sr_star = expected_max_sharpe(n_trials, var_sr)
    mertens = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr

    # --- Non-IID HAC recalibration (SR* held fixed). ---
    lag = nw_bandwidth(t)
    terms = sharpe_variance_terms(r, lag)
    lam = terms["lambda"]
    var_term_recal = lam * mertens
    z_recal = (sr - sr_star) * np.sqrt(t - 1.0) / np.sqrt(var_term_recal)
    dsr_recal = float(norm.cdf(z_recal))
    z_psr_recal = sr * np.sqrt(t - 1.0) / np.sqrt(var_term_recal)
    psr_recal = float(norm.cdf(z_psr_recal))

    # Bandwidth sensitivity for lambda (transparency on the HAC knob).
    sens = {}
    for name, lg in [("L0", 0), ("L5", 5), ("L10", 10), ("L21", 21), (f"Lauto={lag}", lag)]:
        sens[name] = round(sharpe_variance_terms(r, lg)["lambda"], 4)

    return SleeveResult(
        label=label,
        run=run,
        n_obs=t,
        sr_per_period=sr,
        sr_ann_deployed=float(val["sr_ann"]),
        skew=g3,
        kurtosis_nonexcess=g4,
        excess_kurtosis=excess_kurtosis(r),
        acf1_returns=autocorr(r, 1),
        acf1_abs_returns=autocorr(np.abs(r), 1),
        acf1_sq_returns=autocorr(r * r, 1),
        n_trials=n_trials,
        sr_trials_variance=var_sr,
        expected_max_sr=sr_star,
        psr_current=rep.psr,
        dsr_current=float(val["dsr"]),
        dsr_current_reproduced=rep.dsr,
        nw_lag=lag,
        mertens_term=mertens,
        v0_delta=terms["v0"],
        vhac_delta=terms["vhac"],
        lam=lam,
        t_eff=t / lam,
        variance_term_recal=var_term_recal,
        psr_recal=psr_recal,
        dsr_recal=dsr_recal,
        dsr_delta=dsr_recal - float(val["dsr"]),
        crosses_gate_current=float(val["dsr"]) >= 0.95,
        crosses_gate_recal=dsr_recal >= 0.95,
        lam_sensitivity=sens,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = [analyse(label, run) for label, run in SLEEVES]

    payload = {
        "probe": "dsr_recalibration_non_iid",
        "method": {
            "heavy_tails": "deployed Mertens skew/kurtosis term, UNCHANGED (realized 3rd/4th moments)",
            "serial_correlation": "Newey-West (Bartlett) HAC on the Lo-2002 delta-method Sharpe "
            "moment vector g_t=(r-mu, r^2-gamma); lambda = Vhac/V0 is a multiplicative "
            "serial-dependence inflation on the heavy-tail term.",
            "bandwidth": "Newey-West (1994) automatic L*=floor(4*(T/100)^(2/9)); "
            "L in {0,5,10,21} reported as sensitivity.",
            "sr_star_held_fixed": "n_trials and sr_trials_variance are each sleeve's DEPLOYED "
            "walkforward.json values; only the non-IID SE moves.",
            "gate": "DSR >= 0.95",
        },
        "sleeves": [asdict(x) for x in results],
    }
    (OUT / "dsr_recal.json").write_text(json.dumps(payload, indent=2) + "\n")

    # Human-readable table.
    lines: list[str] = []
    lines.append("DSR RECALIBRATION UNDER NON-IID RETURN DYNAMICS")
    lines.append("=" * 78)
    for x in results:
        lines.append("")
        lines.append(f"{x.label}   [{x.run}]")
        lines.append(f"  n_obs (daily)         {x.n_obs}")
        lines.append(f"  SR per-period         {x.sr_per_period:+.5f}   (ann {x.sr_ann_deployed:+.4f})")
        lines.append(f"  skew                  {x.skew:+.4f}")
        lines.append(f"  excess kurtosis       {x.excess_kurtosis:+.4f}")
        lines.append(f"  acf1 returns          {x.acf1_returns:+.4f}")
        lines.append(f"  acf1 |returns|        {x.acf1_abs_returns:+.4f}   (vol clustering)")
        lines.append(f"  acf1 returns^2        {x.acf1_sq_returns:+.4f}   (vol clustering)")
        lines.append(f"  n_trials / V[SR]      {x.n_trials} / {x.sr_trials_variance:.3e}   SR*={x.expected_max_sr:.5f}")
        lines.append(f"  Mertens term (V0alg)  {x.mertens_term:.5f}")
        lines.append(f"  delta V0 (HAC L=0-ish){x.v0_delta:.5f}   [should ~= Mertens term -> machinery check]")
        lines.append(f"  delta Vhac (NW L={x.nw_lag})   {x.vhac_delta:.5f}")
        lines.append(f"  lambda = Vhac/V0      {x.lam:.4f}   -> T_eff = {x.t_eff:.0f} (of {x.n_obs})")
        lines.append(f"  lambda sensitivity    {x.lam_sensitivity}")
        lines.append(f"  PSR(0)  current->recal {x.psr_current:.4f} -> {x.psr_recal:.4f}")
        lines.append(f"  DSR current (deployed) {x.dsr_current:.4f}   (reproduced {x.dsr_current_reproduced:.4f})")
        lines.append(f"  DSR recalibrated       {x.dsr_recal:.4f}   (delta {x.dsr_delta:+.4f})")
        lines.append(f"  crosses 0.95 gate      current={x.crosses_gate_current}  recal={x.crosses_gate_recal}")
    (OUT / "dsr_recal.txt").write_text("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"\nwrote {OUT/'dsr_recal.json'}")
    print(f"wrote {OUT/'dsr_recal.txt'}")


if __name__ == "__main__":
    main()
