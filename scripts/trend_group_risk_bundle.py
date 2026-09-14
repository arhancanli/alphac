"""Hash-bound group-risk strategy factory and per-rebalance diagnostics."""
import copy
from alphaforge.data.store.reader import PITDataReader
from alphaforge.validation.trend_observation import ObservationError
from run_trend_extended_reference import ComparisonBundle
from trend_group_risk_strategy import GroupRiskConfirmedStrategy

class LoggedGroupRiskStrategy(GroupRiskConfirmedStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_risk_audit=[]
    def _rebalance(self,ctx,mu_map):
        targets=super()._rebalance(ctx,mu_map)
        if targets is not None:
            self.group_risk_audit.append({'ts':ctx.ts,**copy.deepcopy(self._group_allocator.last_diagnostics),'final_targets':dict(targets)})
        return targets

class GroupComparisonBundle(ComparisonBundle):
    def strategy(self, settings, signal_frame, **kwargs):
        self.verify()
        self._bind_settings(settings)
        if self._signals_digest is None or self._frame_digest(signal_frame)!=self._signals_digest:
            raise ObservationError('Signal frame is not the bound runner output')
        return LoggedGroupRiskStrategy(settings,signal_frame=signal_frame,allocator='trend',signal_reader=PITDataReader(self.signal_paths),input_digest=self.binding['paired_input_sha256'],**kwargs)
