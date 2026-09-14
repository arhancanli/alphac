from alphamax_share_ratio_service import corrected_momentum, corrected_sigma, substituted_specs

from alphaforge.features.library.equity_price import eq_mom_252_21
from alphaforge.signals.service import _OPEN_SPEC, _SIGMA_SPEC


def test_substitution_preserves_metadata_and_isolates_changes():
    spec = eq_mom_252_21()
    original_fn = spec.fn
    a, s, o = substituted_specs([spec], "legacy")
    assert a is spec and s is _SIGMA_SPEC and o is _OPEN_SPEC
    a, s, o = substituted_specs([spec], "momentum")
    assert a.fn is corrected_momentum and s is _SIGMA_SPEC and o is _OPEN_SPEC
    assert a.params == spec.params and a.lookback_bars == spec.lookback_bars
    a, s, o = substituted_specs([spec], "momentum_sigma")
    assert s.fn is corrected_sigma and s.params == _SIGMA_SPEC.params
    assert s.lookback_bars == _SIGMA_SPEC.lookback_bars == 2520
    assert spec.fn is original_fn and _SIGMA_SPEC.fn is not corrected_sigma
