from types import SimpleNamespace
import pytest
from test_backtest_engine import BTC,HOUR,T0,bar_row,build_engine,make_instrument
from continuous_crypto_runner import ScheduledSignalStrategy


class Persistent:
    def __init__(self,targets):self.targets=targets;self.loads=[];self.risk_calls=0
    def load_leg(self,frame):self.loads.append(frame)
    def on_bar_close(self,ctx):self.risk_calls+=1;return self.targets.get(ctx.ts,{})


def schedules():
    return [{'decision_start':T0+HOUR,'frame':'first'}, {'decision_start':T0+4*HOUR,'frame':'second'}]


def test_boundary_switch_preserves_context_and_persistent_strategy_state():
    base=Persistent({});wrapper=ScheduledSignalStrategy(base,schedules())
    for k in range(1,6):wrapper.on_bar_close(SimpleNamespace(ts=T0+k*HOUR,positions={BTC:7.},equity=995.))
    assert base.loads==['second'] and base.risk_calls==5
    assert wrapper.transitions[0]['positions_before_model_swap']=={BTC:7.}
    assert wrapper.transitions[0]['equity_before_model_swap']==995.


def test_real_engine_keeps_boundary_position_pending_order_and_funding(tmp_path):
    bars=[bar_row(BTC,T0+k*HOUR,open_=100,close=100) for k in range(7)]
    engine=build_engine(tmp_path,bars,[(BTC,T0+int(3.5*HOUR),.01),(BTC,T0+int(4.5*HOUR),.01)],[make_instrument(BTC)])
    # Decision at3h queues a fill at3h open, processed before the first new-frame decision at4h.
    base=Persistent({T0+3*HOUR:{BTC:.1}});wrapper=ScheduledSignalStrategy(base,schedules())
    result=engine.run(wrapper,[BTC],start=T0,end=T0+7*HOUR,initial_cash=100000.)
    assert len(result.fills)==1
    fill=result.fills.iloc[0];assert fill.ts==T0+3*HOUR and fill.qty>0
    assert wrapper.transitions[0]['positions_before_model_swap'][BTC]==fill.qty
    funding=result.funding_events;assert len(funding)==2
    assert (funding.position_qty==fill.qty).all()
    assert result.positions.groupby('ts').qty.last().iloc[-1]==fill.qty
    assert base.risk_calls==7 and len(base.loads)==1


def test_new_frame_decision_cannot_fill_before_activation(tmp_path):
    bars=[bar_row(BTC,T0+k*HOUR,open_=100,close=100) for k in range(7)]
    engine=build_engine(tmp_path,bars,[],[make_instrument(BTC)])
    base=Persistent({T0+4*HOUR:{BTC:.1}});wrapper=ScheduledSignalStrategy(base,schedules())
    result=engine.run(wrapper,[BTC],start=T0,end=T0+7*HOUR,initial_cash=100000.)
    assert result.fills.ts.min()>=wrapper.transitions[0]['actual_decision_ts']
    assert wrapper.transitions[0]['positions_before_model_swap']=={}


def test_invalid_clocks_and_schedule_rejected():
    with pytest.raises(ValueError):ScheduledSignalStrategy(Persistent({}),schedules()[::-1])
    wrapper=ScheduledSignalStrategy(Persistent({}),schedules());ctx=SimpleNamespace(ts=T0+HOUR,positions={},equity=100.)
    wrapper.on_bar_close(ctx)
    with pytest.raises(ValueError):wrapper.on_bar_close(ctx)
