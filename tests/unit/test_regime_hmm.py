"""Unit tests for the hand-rolled HMM regime gate (alphaDesign.md §8, §9.2).

The headline test is synthetic regime-switch recovery: a known 2-/3-state Gaussian
generator is drawn from a seeded RNG (so the test is deterministic), the model is
fitted, and we assert it recovers the vol-sorted state identity, the hidden path, the
transition self-probabilities, and the state vol means. The remaining tests pin the
no-leak / no-flip / numerical-stability invariants the gate's correctness depends on:

* filtered != smoothed (truncation invariance) — the leak-regression guard,
* gate range ``[0.3, 1.0]`` and strict positivity — correctness rule 3,
* multi-seed determinism + best-seed selection + EM loglik monotonicity,
* vol-sort re-pinning regardless of EM's raw labeling,
* cov-floor stability on a near-collapsed cluster,
* every validation guard (``MIN_FIT_DAYS``, non-finite, ``n_states``, gate weights,
  unfitted ``params``, ``lag_days=0``).

All synthetic data is generated in-memory; this test never touches the live data lake.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaforge.regime.hmm import (
    GATE_WEIGHTS,
    MIN_FIT_DAYS,
    HMMParams,
    IdentityRegime,
    RegimeGate,
    RegimeHMM,
    build_observations,
)

# A day in epoch-ms; observations are spaced on the daily grid so available_at math is
# the real D1 contract, not an arbitrary integer index.
_DAY_MS = 86_400_000


def _switch_generator(
    *,
    means: np.ndarray,
    trans: np.ndarray,
    covs: np.ndarray,
    n_days: int,
    seed: int,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Draw ``n_days`` of ``[m, v]`` observations from a Gaussian HMM generator.

    Returns the observation frame (daily-grid ``available_at`` included) and the true
    hidden-state path. ``means``/``covs`` are already in vol-ascending order so the
    true path is directly comparable to the model's vol-sorted decode.
    """
    rng = np.random.default_rng(seed)
    k = means.shape[0]
    states = np.empty(n_days, dtype=int)
    states[0] = 0
    for t in range(1, n_days):
        states[t] = rng.choice(k, p=trans[states[t - 1]])
    x = np.array([rng.multivariate_normal(means[s], covs[s]) for s in states])
    ts = np.arange(n_days, dtype=np.int64) * _DAY_MS
    obs = pd.DataFrame(
        {"m": x[:, 0], "v": x[:, 1], "available_at": ts + _DAY_MS},
        index=pd.Index(ts, name="ts_open"),
    )
    return obs, states


_TWO_STATE = {
    "means": np.array([[0.001, np.log(0.4)], [-0.002, np.log(1.2)]]),
    "trans": np.array([[0.97, 0.03], [0.05, 0.95]]),
    "covs": np.array([[[2e-5, 0.0], [0.0, 0.02]], [[8e-5, 0.0], [0.0, 0.03]]]),
}

_THREE_STATE = {
    "means": np.array([[0.0015, np.log(0.3)], [0.0, np.log(0.7)], [-0.003, np.log(1.5)]]),
    "trans": np.array([[0.96, 0.03, 0.01], [0.04, 0.92, 0.04], [0.02, 0.05, 0.93]]),
    "covs": np.array(
        [
            [[1.5e-5, 0.0], [0.0, 0.015]],
            [[4e-5, 0.0], [0.0, 0.02]],
            [[1.2e-4, 0.0], [0.0, 0.03]],
        ]
    ),
}


# --------------------------------------------------- headline: regime-switch recovery


def test_two_state_recovery() -> None:
    obs, true_path = _switch_generator(**_TWO_STATE, n_days=1500, seed=11)
    hmm = RegimeHMM(n_states=2).fit(obs)
    params = hmm.params

    # (a) vol-sorted state identity: state 0 is the low-vol state.
    assert params.means[0, 1] < params.means[1, 1]

    # (b) hidden-state recovery via vol-sorted filtered argmax decode.
    decode = hmm.filtered_probs(obs).to_numpy().argmax(axis=1)
    assert (decode == true_path).mean() >= 0.90

    # (c) recovered transition self-probs within 0.05 of truth.
    assert np.allclose(np.diag(params.trans_mat), np.diag(_TWO_STATE["trans"]), atol=0.05)

    # (d) recovered state-vol means within a tolerance band of the generator's.
    assert np.allclose(params.means[:, 1], _TWO_STATE["means"][:, 1], atol=0.10)


def test_three_state_recovery() -> None:
    obs, true_path = _switch_generator(**_THREE_STATE, n_days=2200, seed=23)
    hmm = RegimeHMM(n_states=3).fit(obs)
    params = hmm.params

    # Vol-sorted, strictly ascending log-vol means.
    assert params.means[0, 1] < params.means[1, 1] < params.means[2, 1]

    decode = hmm.filtered_probs(obs).to_numpy().argmax(axis=1)
    assert (decode == true_path).mean() >= 0.80
    assert np.allclose(np.diag(params.trans_mat), np.diag(_THREE_STATE["trans"]), atol=0.07)


# ------------------------------------------------------- determinism & EM monotonicity


def test_fit_is_deterministic() -> None:
    obs, _ = _switch_generator(**_TWO_STATE, n_days=900, seed=3)
    a = RegimeHMM(n_states=2, random_state=42).fit(obs).params
    b = RegimeHMM(n_states=2, random_state=42).fit(obs).params
    assert a.seed == b.seed
    assert np.array_equal(a.start_prob, b.start_prob)
    assert np.array_equal(a.trans_mat, b.trans_mat)
    assert np.array_equal(a.means, b.means)
    assert np.array_equal(a.covs, b.covs)
    assert a.loglik == b.loglik


def test_winning_seed_has_max_loglik() -> None:
    obs, _ = _switch_generator(**_TWO_STATE, n_days=900, seed=5)
    # The internal helper reproduces every seed's loglik; the stored fit must be the max.
    from alphaforge.regime.hmm import _baum_welch_once

    n_seeds = 10
    seed_seq = np.random.SeedSequence(42)
    x = obs.loc[:, ["m", "v"]].to_numpy(dtype=np.float64)
    logliks = [
        _baum_welch_once(x, 2, np.random.default_rng(child), max_iter=300, tol=1e-4)[4]
        for child in seed_seq.spawn(n_seeds)
    ]
    fitted = RegimeHMM(n_states=2, n_seeds=n_seeds, random_state=42).fit(obs).params
    assert fitted.loglik == pytest.approx(max(logliks), abs=1e-9)
    assert logliks[fitted.seed] == pytest.approx(max(logliks), abs=1e-9)


def test_em_loglik_is_monotone() -> None:
    # Re-run a single seed manually, recording the loglik per iteration; EM is monotone.
    from alphaforge.regime.hmm import (
        _backward,
        _forward_filter,
        _init_params,
        _log_emissions,
    )

    obs, _ = _switch_generator(**_TWO_STATE, n_days=700, seed=8)
    x = obs.loc[:, ["m", "v"]].to_numpy(dtype=np.float64)
    rng = np.random.default_rng(99)
    pi, trans, means, covs = _init_params(x, 2, rng)
    logliks: list[float] = []
    for _ in range(30):
        log_b = _log_emissions(x, means, covs)
        with np.errstate(divide="ignore"):
            log_pi = np.log(pi)
        filt, log_c, ll = _forward_filter(log_b, log_pi, trans)
        logliks.append(ll)
        beta = _backward(log_b, trans, log_c)
        gamma = filt * beta
        gamma /= gamma.sum(axis=1, keepdims=True)
        n_obs = x.shape[0]
        trans_num = np.zeros((2, 2))
        for t in range(1, n_obs):
            b_beta = np.exp(log_b[t] - log_c[t]) * beta[t]
            xi = (filt[t - 1][:, None] * trans) * b_beta[None, :]
            xi /= xi.sum()
            trans_num += xi
        pi = gamma[0].copy()
        denom = gamma[:-1].sum(axis=0)
        trans = trans_num / denom[:, None]
        trans /= trans.sum(axis=1, keepdims=True)
        weights = gamma.sum(axis=0)
        means = (gamma.T @ x) / weights[:, None]
        covs = np.empty((2, 2, 2))
        for kk in range(2):
            centred = x - means[kk]
            covs[kk] = (gamma[:, kk][:, None] * centred).T @ centred / weights[kk] + 1e-6 * np.eye(
                2
            )
    diffs = np.diff(logliks)
    assert np.all(diffs >= -1e-9)  # non-decreasing up to numerical slack


# ------------------------------------------------------------------ vol-sort re-pinning


def test_vol_sort_repins_regardless_of_labels() -> None:
    # Swap the generator's two state labels: the LOW-vol state is now labeled 1.
    swapped = {
        "means": _TWO_STATE["means"][::-1].copy(),
        "trans": _TWO_STATE["trans"][::-1][:, ::-1].copy(),
        "covs": _TWO_STATE["covs"][::-1].copy(),
    }
    obs, _ = _switch_generator(**swapped, n_days=1400, seed=17)
    params = RegimeHMM(n_states=2).fit(obs).params
    # Regardless of which raw label the EM assigned, stored state 0 is the low-vol one.
    assert params.means[0, 1] < params.means[1, 1]
    assert params.means[0, 1] == pytest.approx(np.log(0.4), abs=0.10)


# --------------------------------------------------- filtered != smoothed (leak guard)


def test_filtered_is_truncation_invariant() -> None:
    obs, _ = _switch_generator(**_TWO_STATE, n_days=1000, seed=4)
    hmm = RegimeHMM(n_states=2).fit(obs)
    full = hmm.filtered_probs(obs)
    for d in (10, 250, 600, 998):
        truncated = hmm.filtered_probs(obs.iloc[: d + 1])
        np.testing.assert_allclose(
            full.iloc[d].to_numpy(), truncated.iloc[d].to_numpy(), atol=1e-12
        )


# ------------------------------------------------ gate range & sign preservation (R3)


def test_gross_multiplier_in_range_and_positive() -> None:
    hmm = RegimeHMM(n_states=3)
    # gross_multiplier is a pure blend of the posterior — no fit needed for the range.
    k = 3
    rng = np.random.default_rng(1)
    rows = rng.dirichlet(np.ones(k), size=500)
    probs = pd.DataFrame(rows, columns=[f"state_{i}" for i in range(k)])
    g = hmm.gross_multiplier(probs)
    assert g.min() >= 0.3 - 1e-12
    assert g.max() <= 1.0 + 1e-12
    assert (g > 0.0).all()  # correctness rule 3: never <= 0, never flips a sign


def test_degenerate_posteriors_hit_the_endpoints() -> None:
    hmm = RegimeHMM(n_states=3)
    cols = ["state_0", "state_1", "state_2"]
    all_low = pd.DataFrame([[1.0, 0.0, 0.0]], columns=cols)
    all_high = pd.DataFrame([[0.0, 0.0, 1.0]], columns=cols)
    assert hmm.gross_multiplier(all_low).iloc[0] == pytest.approx(1.0)
    assert hmm.gross_multiplier(all_high).iloc[0] == pytest.approx(0.3)


def test_gate_weights_match_spec() -> None:
    assert GATE_WEIGHTS[2] == (1.0, 0.3)
    assert GATE_WEIGHTS[3] == (1.0, 0.7, 0.3)
    assert tuple(RegimeHMM(n_states=2).gate_weights) == (1.0, 0.3)
    assert tuple(RegimeHMM(n_states=3).gate_weights) == (1.0, 0.7, 0.3)


# ------------------------------------------------------------------- cov-floor stability


def test_cov_floor_keeps_covs_spd_on_collapsed_cluster() -> None:
    rng = np.random.default_rng(2)
    # One tight cluster of near-identical rows + one diffuse cluster: the tight cluster
    # would collapse a Gaussian state without the COV_FLOOR.
    tight = np.tile([0.0, np.log(0.5)], (400, 1)) + rng.normal(0, 1e-9, size=(400, 2))
    diffuse = rng.normal([0.0, np.log(1.0)], [0.01, 0.2], size=(400, 2))
    x = np.vstack([tight, diffuse])
    rng.shuffle(x)
    # Pad to MIN_FIT_DAYS with more diffuse draws so fit() is allowed to run.
    pad = rng.normal([0.0, np.log(0.8)], [0.01, 0.3], size=(MIN_FIT_DAYS, 2))
    x = np.vstack([x, pad])
    ts = np.arange(len(x), dtype=np.int64) * _DAY_MS
    obs = pd.DataFrame(
        {"m": x[:, 0], "v": x[:, 1], "available_at": ts + _DAY_MS},
        index=pd.Index(ts, name="ts_open"),
    )
    params = RegimeHMM(n_states=2).fit(obs).params
    for cov in params.covs:
        np.linalg.cholesky(cov)  # raises LinAlgError if not SPD
    assert np.all(np.isfinite(params.loglik))


# ------------------------------------------------------------------------- guard rails


def _valid_obs(n: int = MIN_FIT_DAYS) -> pd.DataFrame:
    obs, _ = _switch_generator(**_TWO_STATE, n_days=n, seed=1)
    return obs


def test_fit_raises_below_min_fit_days() -> None:
    obs = _valid_obs(MIN_FIT_DAYS - 1)
    with pytest.raises(ValueError, match=r"MIN_FIT_DAYS|>= 730|observations to fit"):
        RegimeHMM(n_states=2).fit(obs)


def test_fit_raises_on_non_finite_rows() -> None:
    obs = _valid_obs().copy()
    obs.loc[obs.index[100], "v"] = np.inf
    with pytest.raises(ValueError, match="non-finite"):
        RegimeHMM(n_states=2).fit(obs)


def test_invalid_n_states_raises() -> None:
    with pytest.raises(ValueError, match="n_states"):
        RegimeHMM(n_states=4)
    with pytest.raises(ValueError, match="n_states"):
        RegimeHMM(n_states=1)


def test_gate_weights_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length n_states"):
        RegimeHMM(n_states=2, gate_weights=(1.0, 0.7, 0.3))


def test_gate_weights_must_be_descending() -> None:
    with pytest.raises(ValueError, match="DESCENDING"):
        RegimeHMM(n_states=2, gate_weights=(0.3, 1.0))


def test_gate_weights_must_be_in_unit_interval() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        RegimeHMM(n_states=2, gate_weights=(1.5, 0.3))


def test_params_before_fit_raises() -> None:
    with pytest.raises(RuntimeError, match="not fitted"):
        _ = RegimeHMM(n_states=2).params


def test_gross_multiplier_series_rejects_lag_zero() -> None:
    obs = _valid_obs()
    hmm = RegimeHMM(n_states=2).fit(obs)
    with pytest.raises(ValueError, match="lag_days must be >= 1"):
        hmm.gross_multiplier_series(obs, lag_days=0)


def test_extract_requires_observation_columns() -> None:
    obs = _valid_obs().drop(columns=["v"])
    with pytest.raises(ValueError, match="observation columns"):
        RegimeHMM(n_states=2).fit(obs)


# -------------------------------------------------------------- build_observations API


def test_build_observations_stamps_available_at_and_drops_warmup() -> None:
    n = MIN_FIT_DAYS + 40
    rng = np.random.default_rng(13)
    ts = np.arange(n, dtype=np.int64) * _DAY_MS
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    daily = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=pd.Index(ts, name="ts_open"),
    )
    obs = build_observations(daily)
    # available_at == day close == ts_open + one day, for every retained row.
    assert (obs["available_at"].to_numpy() == obs.index.to_numpy() + _DAY_MS).all()
    assert obs["available_at"].dtype == np.int64
    # Warm-up rows (14d YZ + 1-bar gap return) were dropped -> first ts_open advanced.
    assert obs.index.min() > ts[0]
    assert np.isfinite(obs[["m", "v"]].to_numpy()).all()


def test_build_observations_raises_when_too_short() -> None:
    n = 100
    ts = np.arange(n, dtype=np.int64) * _DAY_MS
    daily = pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0},
        index=pd.Index(ts, name="ts_open"),
    )
    with pytest.raises(ValueError, match=r"MIN_FIT_DAYS|>= 730|finite daily"):
        build_observations(daily)


# ----------------------------------------------------------------------- Protocol seam


def test_protocol_conformance() -> None:
    assert isinstance(RegimeHMM(n_states=2), RegimeGate)
    assert isinstance(IdentityRegime(), RegimeGate)


def test_identity_regime_is_constant_one() -> None:
    obs = _valid_obs(50)
    g = IdentityRegime().gross_multiplier_series(obs, lag_days=1)
    assert (g.to_numpy() == 1.0).all()
    assert g.index.equals(obs.index)


def test_hmm_params_is_frozen() -> None:
    params = HMMParams(
        n_states=2,
        start_prob=np.array([0.5, 0.5]),
        trans_mat=np.eye(2),
        means=np.zeros((2, 2)),
        covs=np.repeat(np.eye(2)[None], 2, axis=0),
        loglik=-1.0,
        n_obs=730,
        seed=0,
    )
    with pytest.raises((AttributeError, Exception)):
        params.loglik = 0.0  # type: ignore[misc]
