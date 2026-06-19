"""Unit tests for the F2 fundamental-factor reduction kernels (TTM + carry-forward shares).

These pure kernels are the PIT/parity-critical core: the TTM sum must be prefix-independent
(atol=0), require all 4 trailing quarters, and propagate NaN; the share carry-forward must
forward-fill the last POSITIVE value per instrument. Their correctness plus the as-of join's
truncation/parity sweep (test_factor_invariants) is the full PIT guarantee.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaforge.features.library.equity_fundamental import (
    _ffill_positive_by_instrument,
    _trailing_sum_by_instrument,
)

A = "XUSE:CASH:AAA"
B = "XUSE:CASH:BBB"


def _frame(rows: list[tuple[str, float | None]]) -> pd.DataFrame:
    """(instrument_id, value) rows -> frame sorted as the kernels require."""
    return pd.DataFrame(
        {
            "instrument_id": [r[0] for r in rows],
            "revenues": [np.nan if r[1] is None else float(r[1]) for r in rows],
            "diluted_shares": [np.nan if r[1] is None else float(r[1]) for r in rows],
        }
    )


class TestTrailingSum:
    def test_nan_until_k_quarters(self) -> None:
        f = _frame([(A, 10), (A, 20), (A, 30), (A, 40), (A, 50)])
        out = _trailing_sum_by_instrument(f, "revenues", 4).to_numpy()
        # first 3 NaN (fewer than 4 quarters), then rolling-4 sums
        assert np.isnan(out[:3]).all()
        assert out[3] == 100.0  # 10+20+30+40
        assert out[4] == 140.0  # 20+30+40+50

    def test_nan_propagates_if_any_quarter_null(self) -> None:
        f = _frame([(A, 10), (A, None), (A, 30), (A, 40), (A, 50)])
        out = _trailing_sum_by_instrument(f, "revenues", 4).to_numpy()
        assert np.isnan(out[3])  # window [10, NaN, 30, 40] -> NaN (all-4-required)
        assert np.isnan(out[4])  # window [NaN, 30, 40, 50] -> NaN (the null is still in range)
        f2 = _frame([(A, 10), (A, 20), (A, 30), (A, 40), (A, 50), (A, 60)])
        out2 = _trailing_sum_by_instrument(f2, "revenues", 4).to_numpy()
        assert out2[5] == 180.0  # window [30,40,50,60] -> 180 once the null has aged out

    def test_per_instrument_isolation(self) -> None:
        # B's window must never borrow A's rows (prefix-independence across instruments)
        f = _frame([(A, 10), (A, 20), (A, 30), (A, 40), (B, 1), (B, 2), (B, 3), (B, 4)])
        out = _trailing_sum_by_instrument(f, "revenues", 4).to_numpy()
        assert out[3] == 100.0  # A: 10+20+30+40
        assert np.isnan(out[4:7]).all()  # B: first 3 NaN
        assert out[7] == 10.0  # B: 1+2+3+4

    def test_prefix_independence_atol0(self) -> None:
        # The TTM at a row must equal the same TTM computed on a SUFFIX slice (the live
        # minimal-window parity contract): summing only the window's own k rows.
        full = _frame([(A, x) for x in (5, 10, 15, 20, 25, 30)])
        out_full = _trailing_sum_by_instrument(full, "revenues", 4).to_numpy()
        suffix = _frame([(A, x) for x in (15, 20, 25, 30)])  # last 4 rows only
        out_suffix = _trailing_sum_by_instrument(suffix, "revenues", 4).to_numpy()
        assert out_full[-1] == out_suffix[-1]  # 15+20+25+30 == 90, bit-identical


class TestFfillPositiveShares:
    def test_carry_forward_last_positive(self) -> None:
        # null (derived-Q4) and a stray non-positive must be skipped; last positive carries
        f = _frame([(A, 100), (A, None), (A, 110), (A, None)])
        out = _ffill_positive_by_instrument(f, "diluted_shares").to_numpy()
        assert out[0] == 100.0
        assert out[1] == 100.0  # carried over the null
        assert out[2] == 110.0
        assert out[3] == 110.0  # carried over the trailing null

    def test_nan_until_first_positive(self) -> None:
        f = _frame([(A, None), (A, None), (A, 50)])
        out = _ffill_positive_by_instrument(f, "diluted_shares").to_numpy()
        assert np.isnan(out[0]) and np.isnan(out[1])
        assert out[2] == 50.0

    def test_per_instrument_isolation(self) -> None:
        f = _frame([(A, 100), (B, None), (B, 7)])
        out = _ffill_positive_by_instrument(f, "diluted_shares").to_numpy()
        assert out[0] == 100.0
        assert np.isnan(out[1])  # B does NOT inherit A's 100
        assert out[2] == 7.0
