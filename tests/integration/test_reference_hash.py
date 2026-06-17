"""Reference-hash regression: a frozen numeric fingerprint of the engine (A5-2).

This is a tripwire, not a unit test. It recomputes one tiny, fully
deterministic artifact end to end through the public portfolio API and asserts
its SHA-256 equals a value pinned in source. If a refactor, a dependency bump,
or a platform change perturbs the production math by even one bit, the digest
flips and CI goes red — long before the drift reaches a backtest or live
capital.

Why this artifact: :class:`~alphaforge.portfolio.RankEqualVolFallback` is the
v1 primary allocator and is pure NumPy — no cvxpy solver, no RNG, no clock, no
I/O (the package docstring: "arrays/mappings in, arrays/orders out"). With a
diagonal covariance the inverse-vol weights collapse to exact IEEE-754 values
(``0.15`` = the ``w_max`` clip; ``-1/7`` = the normalized short leg), which are
bit-identical on every conforming platform. That makes the digest a meaningful
*production-math* fingerprint while staying immune to the cross-solver,
cross-BLAS float wobble that would make an MVO or HMM fit a poor hash target.

Determinism preconditions (asserted below): the BLAS/OpenMP thread limits set
in ``tests/conftest.py`` before NumPy import, plus the absence of any RNG in
this path, are what let the pinned hash hold run to run and machine to machine.
"""

from __future__ import annotations

import hashlib
import os

import numpy as np
import threadpoolctl

from alphaforge.portfolio import PortfolioConstraints, RankEqualVolFallback

#: SHA-256 of the canonical float64 bytes of the reference weight vector below.
#: Obtained by RUNNING the computation once (never hand-authored). Regenerate
#: only on an intentional, reviewed change to the allocator math:
#:     w = compute_reference_weights()
#:     print(hashlib.sha256(np.ascontiguousarray(w, np.float64).tobytes()).hexdigest())
REFERENCE_WEIGHTS_SHA256 = "007339e78a151de78f3c771f08210a253764805ffe26f03e1c10023f3c93cff6"

#: Frozen inputs — hand-coded, no RNG. A 6-name cross-section so the rank
#: allocator's long/short legs both engage (k = max(1, min(10, 6 // 4)) = 1);
#: a DIAGONAL covariance so the inverse-vol weights are exact rationals.
_MU_ANN = np.array([0.30, -0.20, 0.10, 0.05, -0.40, 0.25], dtype=np.float64)
_VARIANCES = np.array([0.04, 0.09, 0.16, 0.01, 0.25, 0.0625], dtype=np.float64)


def compute_reference_weights() -> np.ndarray:
    """Solve the frozen rank/inverse-vol book; pure, deterministic, allocation-only."""
    n = _MU_ANN.shape[0]
    res = RankEqualVolFallback(PortfolioConstraints()).solve(
        _MU_ANN,
        np.diag(_VARIANCES),
        np.zeros(n, dtype=np.float64),  # w_prev
        np.zeros(n, dtype=np.float64),  # cost_frac_oneway
        np.ones(n, dtype=np.float64),  # shortable (perps: all 1)
    )
    return np.ascontiguousarray(res.weights, dtype=np.float64)


def _sha256(weights: np.ndarray) -> str:
    """SHA-256 over canonical bytes: C-contiguous float64, fixed shape/dtype."""
    return hashlib.sha256(weights.tobytes()).hexdigest()


def test_reference_weights_hash_is_pinned() -> None:
    """The frozen allocator artifact still hashes to its pinned digest."""
    weights = compute_reference_weights()
    # Guard the shape/dtype the digest assumes, so a structural change surfaces
    # as a clear failure rather than an opaque hash mismatch.
    assert weights.dtype == np.float64
    assert weights.shape == (6,)
    assert _sha256(weights) == REFERENCE_WEIGHTS_SHA256


def test_reference_hash_is_recompute_stable() -> None:
    """Two independent recomputations agree bit-for-bit (no hidden state/RNG)."""
    assert _sha256(compute_reference_weights()) == _sha256(compute_reference_weights())


def test_blas_thread_limits_are_pinned_to_one() -> None:
    """conftest pinned every BLAS/OpenMP backend to a single thread.

    These limits (set before NumPy import) are the determinism precondition the
    pinned hash relies on. The env vars are the contract conftest guarantees;
    threadpoolctl is queried as a best-effort cross-check on whatever native
    pool is actually loaded (it reports an empty list on some NumPy/Accelerate
    builds, which is not a failure — only an over-1 limit is).
    """
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "MKL_NUM_THREADS",
    ):
        assert os.environ.get(var) == "1", f"{var} must be '1' (set in tests/conftest.py)"

    for pool in threadpoolctl.threadpool_info():
        assert pool["num_threads"] == 1, f"{pool.get('prefix', pool)} not pinned to 1 thread"
