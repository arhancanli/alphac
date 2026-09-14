from test_factors_carry import env, BTC,ETH,DOGE,XRP,T0,HOUR
from alphaforge.features.parity import verify_truncation
from crypto_observed_carry_feature import carry_observed_21


def test_actual_engine_batch_asof_and_truncation(env):
    spec=carry_observed_21();ids=[BTC,ETH,DOGE,XRP]
    samples=[T0+400*HOUR+19*60000,T0+600*HOUR+19*60000,T0+795*HOUR]
    result=verify_truncation(env.engine,spec,ids,samples,history_start=T0).result(spec.name)
    assert result.passed and result.max_abs_diff==0 and result.n_points==12
    live=env.engine.compute_asof([spec],ids,as_of=samples[-1])[spec.name]
    assert live.xs(XRP,level='instrument_id').isna().all()
    assert live.drop(XRP,level='instrument_id').notna().all()
