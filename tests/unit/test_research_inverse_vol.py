import numpy as np

from alphaforge.portfolio.research_inverse_vol import allocate, bounded_weights


def test_limits_and_zero_vol_fallback():
    w = bounded_weights([0.001, 1, 2, 3])
    assert np.isclose(w.sum(), 1)
    assert (w >= 0.1).all() and (w <= 0.4).all()
    np.testing.assert_array_equal(bounded_weights([0, 1, 2, 3]), [0.25] * 4)


def test_future_perturbation_and_weekly_schedule():
    c = np.random.default_rng(41).normal(0, 0.002, (280, 5))
    days = np.arange(280) % 7
    net, weights, _ = allocate(c, days, 0.0001)
    changed = c.copy()
    changed[175:] *= 12
    alt, alt_weights, _ = allocate(changed, days, 0.0001)
    np.testing.assert_array_equal(weights[:176], alt_weights[:176])
    np.testing.assert_array_equal(net[:175], alt[:175])
    np.testing.assert_array_equal(weights[:126], np.full((126, 4), 0.25))
    for t in range(1, len(c)):
        if days[t] != 0:
            np.testing.assert_array_equal(weights[t], weights[t - 1])


def test_cost_stress_preserves_positions_and_overlay():
    c = np.random.default_rng(3).normal(0, 0.002, (280, 5))
    c[:, 0] *= 10
    days = np.arange(280) % 7
    net, w, cost = allocate(c, days, 0.0001)
    stressed, sw, sc = allocate(c, days, 0.0005)
    np.testing.assert_array_equal(w, sw)
    np.testing.assert_allclose(sc, 5 * cost)
    np.testing.assert_allclose(net - stressed, sc - cost, atol=1e-17)
    np.testing.assert_allclose(net + cost, (w * c[:, :4] * 4).sum(axis=1) + c[:, 4])
    np.testing.assert_allclose(cost[1:], abs(np.diff(w, axis=0)).sum(axis=1) * 0.0001)
