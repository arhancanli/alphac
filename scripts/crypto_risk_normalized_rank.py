"""Research selection by expected return per covariance volatility; legacy sizing."""
from dataclasses import replace
import numpy as np
from alphaforge.portfolio.optimizer import RankEqualVolFallback,_validate_inputs


class RiskNormalizedRankAllocator(RankEqualVolFallback):
    def solve(self,mu_ann,cov_ann,w_prev,cost_frac_oneway,shortable):
        mu,cov,prev,cost,short=_validate_inputs(mu_ann,cov_ann,w_prev,cost_frac_oneway,shortable)
        if self.constraints.long_only:raise ValueError('Long/short crypto experiment only')
        n=len(mu)
        if n<2:return super().solve(mu,cov,prev,cost,short)
        sigma=np.sqrt(np.clip(np.diag(cov),0,None))
        if not np.all(sigma>0):raise ValueError('Positive covariance volatility required for every ranked asset')
        scores=mu/sigma
        if not np.isfinite(scores).all():raise ValueError('Nonfinite risk-normalized score')
        order=np.argsort(-scores,kind='stable')
        proxy=np.empty(n);proxy[order]=np.linspace(1,-1,n)
        result=super().solve(proxy,cov,prev,cost,short)
        return replace(result,objective=float(mu@result.weights))


def install_risk_normalized_rank(strategy):
    if isinstance(strategy._allocator,RiskNormalizedRankAllocator):return
    if type(strategy._allocator) is not RankEqualVolFallback:raise ValueError('Original rank allocator required')
    strategy._allocator=RiskNormalizedRankAllocator(strategy._allocator.constraints)
