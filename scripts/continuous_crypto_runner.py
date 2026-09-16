"""Research-only continuous crypto ledger with scheduled signal-frame changes."""
from bisect import bisect_right
from alphaforge.analytics.walkforward import WalkForwardRunner,LegResult
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.core.types import AssetClass
from funded_inception_runner import InceptionSplitter
from alphamax_replay_support_v2 import MergeSingletonTail


class ScheduledSignalStrategy:
    """Swap only signal frames; the engine owns one ledger and order queue."""
    def __init__(self,strategy,schedules):
        if not schedules:raise ValueError('At least one signal interval required')
        self.strategy=strategy;self.schedules=schedules
        self.starts=[int(s['decision_start']) for s in schedules]
        if self.starts!=sorted(set(self.starts)):raise ValueError('Unique increasing switches required')
        self.current=0;self.last_ts=None;self.transitions=[]

    def on_bar_close(self,ctx):
        t=int(ctx.ts)
        if self.last_ts is not None and t<=self.last_ts:raise ValueError('Nonmonotonic decision clock')
        index=bisect_right(self.starts,t)-1
        if index<0:raise ValueError('Decision before first signal interval')
        if index!=self.current:
            before=dict(ctx.positions);equity=float(ctx.equity)
            self.strategy.load_leg(self.schedules[index]['frame'])
            assert dict(ctx.positions)==before and float(ctx.equity)==equity
            self.transitions.append({'model_interval':index,'scheduled_decision_start':self.starts[index],
                'actual_decision_ts':t,'equity_before_model_swap':equity,'positions_before_model_swap':before})
            self.current=index
        self.last_ts=t
        return self.strategy.on_bar_close(ctx)


class ContinuousCryptoRunner(WalkForwardRunner):
    def _run_leg_set(self,splitter,grid,ids,full_frame,full_ts,*,train_bars,allocator,band,
                     rebalance_bars,cov_window_bars,cov_halflife_days,cov_min_periods,
                     initial_cash,ml,regime,daily_btc):
        if ml or regime:raise ValueError('This version excludes fitted ML/regime gates')
        if self._sleeve.asset_class is not AssetClass.CRYPTO_PERP or self._sleeve.anchor_tf.ms!=3600000:
            raise ValueError('Continuous runner currently supports hourly crypto only')
        tf=self._sleeve.anchor_tf;schedules=[];previous_end=None
        for k,(_,test) in enumerate(InceptionSplitter(MergeSingletonTail(splitter)).split(grid)):
            start=int(test[0]);end=int(test[-1])+tf.ms
            if previous_end is not None and start!=previous_end:raise ValueError('Noncontiguous model intervals')
            train_start=max(int(full_ts.min()),start-train_bars*tf.ms) if full_ts.size else start-train_bars*tf.ms
            frame=full_frame.iloc[(full_ts>=train_start)&(full_ts<end)]
            schedules.append({'model_interval':k,'test_start':start,'test_end':end,'train_start':train_start,
                              'decision_start':start+tf.ms,'frame':frame})
            previous_end=end
        if not schedules:raise ValueError('No funded test intervals')
        strategy=BlendStrategy(self._settings,signal_frame=schedules[0]['frame'],allocator=allocator,
            rebalance_bars=rebalance_bars,cov_window_bars=cov_window_bars,
            cov_halflife_days=cov_halflife_days,cov_min_periods=cov_min_periods)
        scheduled=ScheduledSignalStrategy(strategy,schedules)
        schedule_metadata=[{k:v for k,v in s.items() if k!='frame'} for s in schedules]
        engine=self._engine_factory(self._reader,self._instruments,self._cost_model,
            tf=tf,asset_class=self._sleeve.asset_class,cost_inputs=self._cost_inputs,
            no_trade_band_frac=band,clamp_reduce_only_adv=self._settings.risk.clamp_reduce_only_adv,
            fill_model=self._fill_model_factory(self._cost_model) if self._fill_model_factory is not None else None,
            config_echo={'walkforward_leg':0,'train_start':schedules[0]['train_start'],'allocator':allocator,
                         'physical_account_segments':1,'model_schedule':schedule_metadata},
            verified_split_events=self._verified_split_events)
        result=engine.run(scheduled,ids,start=schedules[0]['test_start'],end=schedules[-1]['test_end'],initial_cash=initial_cash)
        if len(scheduled.transitions)!=len(schedules)-1:raise ValueError('Unobserved model boundary')
        # The durable engine factory stores transitions before saving its result.
        assert result.config['model_boundary_transitions']==scheduled.transitions
        return [LegResult(leg=0,train_start=schedules[0]['train_start'],test_start=schedules[0]['test_start'],
            test_end=schedules[-1]['test_end'],result=result,risk_counters=strategy.counters)],strategy,0
