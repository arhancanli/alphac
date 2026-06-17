"""Session-wide determinism shims (test-infra A4-3).

This module is imported by pytest *before any test module*, which makes it the
one place where we can pin the BLAS/OpenMP thread counts **before NumPy (and
thus its backing BLAS) is first imported**. Every numeric backend — OpenBLAS,
MKL, Apple Accelerate/vecLib — reads its thread-count environment variable
exactly once, at import time; setting it afterwards is a no-op. Pytest imports
``conftest.py`` ahead of the test tree and ahead of ``alphaforge`` (which pulls
in NumPy), so these assignments win the race.

Why single-threaded matters for a quant repo: a multi-threaded BLAS sums
reductions (dot products, ``A @ B``, Cholesky) in a nondeterministic order, so
the last bits of a covariance, an MVO solve, or an HMM fit can differ run to
run and machine to machine. Pinning every backend to one thread removes that
source of non-reproducibility, which is what the reference-hash regression in
``tests/integration/test_reference_hash.py`` relies on.

``PYTHONHASHSEED``: not set here. ``conftest.py`` runs inside an
already-started interpreter, and ``PYTHONHASHSEED`` is consumed at *interpreter
startup* — assigning it now would be silently ignored. It is pinned at the
process boundary instead (``.github/workflows/ci.yml`` exports
``PYTHONHASHSEED=0``); set it the same way locally if a hash-ordering bug is
ever suspected (``PYTHONHASHSEED=0 uv run pytest``).
"""

from __future__ import annotations

import os

# Pin every BLAS/OpenMP backend to a single thread BEFORE NumPy is imported.
# Each variable is read once at backend import; setdefault leaves an explicit
# operator override (e.g. a CI matrix entry) untouched.
for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "MKL_NUM_THREADS",
):
    os.environ.setdefault(_var, "1")
