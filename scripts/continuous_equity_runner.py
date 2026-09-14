"""Unintegrated funded equity runner; requires separately bound payable engine factory."""
from alphaforge.analytics.walkforward import WalkForwardRunner,LegResult
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.core.types import AssetClass
from continuous_crypto_runner import ScheduledSignalStrategy
from continuous_equity_schedule import equity_schedule
from alphamax_covariance_engine import install_covariance_basis

class ContinuousEquityRunner(WalkForwardRunner):
    def _run_leg_set(self,splitter,grid,ids,full_frame,full_ts,*,train_bars,allocator,band,
                     rebalance_bars,cov_window_bars,cov_halflife_days,cov_min_periods,
                     initial_cash,ml,regime,daily_btc):
        if ml or regime:raise ValueError('This version excludes fitted ML/regime gates')
        if self._sleeve.asset_class is not AssetClass.EQUITY or self._sleeve.anchor_tf.ms!=86400000:
            raise ValueError('Continuous equity runner requires daily equities')
        tf=self._sleeve.anchor_tf
        schedules=equity_schedule(splitter,grid,full_frame,full_ts,train_bars)
        strategy=BlendStrategy(self._settings,signal_frame=schedules[0]['frame'],allocator=allocator,
            rebalance_bars=rebalance_bars,cov_window_bars=cov_window_bars,
            cov_halflife_days=cov_halflife_days,cov_min_periods=cov_min_periods)
        install_covariance_basis(strategy,self._reader,'sessions_splits')
        scheduled=ScheduledSignalStrategy(strategy,schedules)
        schedule_metadata=[{k:v for k,v in s.items() if k!='frame'} for s in schedules]
        engine=self._engine_factory(self._reader,self._instruments,self._cost_model,
            tf=tf,asset_class=self._sleeve.asset_class,cost_inputs=self._cost_inputs,
            no_trade_band_frac=band,clamp_reduce_only_adv=self._settings.risk.clamp_reduce_only_adv,
            fill_model=self._fill_model_factory(self._cost_model) if self._fill_model_factory is not None else None,
            config_echo={'walkforward_leg':0,'train_start':schedules[0]['train_start'],'allocator':allocator,
                         'physical_account_segments':1,'model_schedule':schedule_metadata},
            verified_split_events=self._verified_split_events)
        from alphaforge.backtest.payable_engine import PayableEquityBacktester
        if not isinstance(engine,PayableEquityBacktester):
            raise ValueError("Funded equity requires explicit payable cash engine")
        result=engine.run(scheduled,ids,start=schedules[0]['test_start'],end=schedules[-1]['test_end'],initial_cash=initial_cash)
        if len(scheduled.transitions)!=len(schedules)-1:raise ValueError('Unobserved model boundary')
        # The durable engine factory stores transitions before saving its result.
        assert result.config['model_boundary_transitions']==scheduled.transitions
        return [LegResult(leg=0,train_start=schedules[0]['train_start'],test_start=schedules[0]['test_start'],
            test_end=schedules[-1]['test_end'],result=result,risk_counters=strategy.counters)],strategy,0


def continuous_payable_factory(directory,*,payments,retrospective_vintage_ms,retrospective_actions):
    """Bind complete action/payment schedule and save once after model transitions."""
    from pathlib import Path
    from alphaforge.backtest.payable_engine import PayableEquityBacktester
    directory=Path(directory)
    class DurablePayable(PayableEquityBacktester):
        def __init__(self,*args,**kwargs):
            self.destination=directory/'000'
            self.destination.mkdir(parents=True,exist_ok=False)
            super().__init__(*args,payments=payments,retrospective_vintage_ms=retrospective_vintage_ms,
                             retrospective_actions=retrospective_actions,**kwargs)
        def run(self,strategy,*args,**kwargs):
            if not isinstance(strategy,ScheduledSignalStrategy):raise ValueError('Scheduled strategy required')
            result=super().run(strategy,*args,**kwargs)
            result.config['model_boundary_transitions']=strategy.transitions
            result.config['continuous_accounting']=True
            result.save(self.destination)
            (self.destination/'SAVE_COMPLETE').write_text('continuous payable account saved\n')
            return result
    return DurablePayable
