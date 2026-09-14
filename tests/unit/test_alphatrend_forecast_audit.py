"""Guard forecast diagnostics against false precision and cross-date ranking leakage."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location(
    'forecast_audit', Path(__file__).resolve().parents[2] / 'scripts/audit_alphatrend_forecasts.py'
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_buckets_are_date_local_and_keep_ties():
    original = pd.DataFrame({'ts_open': [1] * 5, 'mu_ann': [-1., 2., 3., 4., 5.]})
    later = pd.DataFrame({'ts_open': [2] * 5, 'mu_ann': [100., 100., 300., 400., 500.]})
    combined = pd.concat([original, later], ignore_index=True)
    assert audit.strength_buckets(combined).iloc[:5].tolist() == [1, 2, 3, 4, 5]
    assert audit.strength_buckets(combined).iloc[5] == audit.strength_buckets(combined).iloc[6]


def test_rank_ic_rejects_tiny_or_constant_cross_sections():
    assert np.isnan(audit.correlation(pd.Series([1.] * 6), pd.Series(range(6))))
    assert np.isnan(audit.correlation(pd.Series(range(4)), pd.Series(range(4))))
    assert audit.correlation(pd.Series(range(6)), pd.Series(range(5, -1, -1))) == -1.


def test_bootstrap_is_reproducible_and_has_no_fake_small_sample_interval():
    assert audit.block_interval(pd.Series([1.] * 12)) == [None, None]
    assert np.allclose(audit.block_interval(pd.Series([.2] * 30)), [.2, .2])
    series = pd.Series(np.linspace(-1, 1, 100))
    assert audit.block_interval(series) == audit.block_interval(series)


def test_short_direction_and_annualization():
    frame = pd.DataFrame({'ts_open': [1, 1], 'mu_ann': [-.12, .24],
                          'forward_log_return': [-.03, -.02]})
    result = audit.summarize(frame)
    assert np.isclose(result['mean_abs_prediction_bps'], 150.)
    assert np.isclose(result['mean_signed_forward_log_bps'], 50.)
    assert result['direction_hit_rate'] == .5
