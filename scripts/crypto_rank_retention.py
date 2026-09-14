"""Research-only rank-boundary retention; original sizing and risk engine preserved."""
from dataclasses import replace
import numpy as np
from alphaforge.portfolio.optimizer import RankEqualVolFallback, _validate_inputs

class RankRetentionAllocator(RankEqualVolFallback):
    def __init__(self, constraints=None, *, buffer_ranks=1):
        super().__init__(constraints)
        if buffer_ranks not in (0,1):
            raise ValueError('Only disabled control or one-rank candidate supported')
        if self.constraints.long_only:
            raise ValueError('Long/short crypto research only')
        self.buffer_ranks=buffer_ranks

    def solve(self, mu_ann, cov_ann, w_prev, cost_frac_oneway, shortable):
        mu,cov,prev,cost,short=_validate_inputs(mu_ann,cov_ann,w_prev,cost_frac_oneway,shortable)
        n=len(mu);c=self.constraints
        k=max(1,min(c.rank_top_k,n//2)) if c.rank_top_k is not None and n>=2 else max(1,min(10,n//4)) if n>=2 else 0
        if not self.buffer_ranks or not np.any(prev) or k==0 or 2*(k+1)>n:
            return super().solve(mu,cov,prev,cost,short)
        order=np.argsort(-mu,kind='stable')
        def select(ranking, incumbents):
            eligible=ranking[:k+1]
            kept=[int(i) for i in eligible if incumbents[i]][:k]
            for i in ranking:
                if len(kept)==k:break
                if int(i) not in kept:kept.append(int(i))
            return kept
        longs=select(order,prev>0)
        shorts=select(order[::-1],(prev<0)&(short==1))
        assert not set(longs)&set(shorts)
        # Only ordering is substituted; delegate every sizing/cap rule unchanged.
        proxy=np.zeros(n,dtype=float)
        proxy[longs]=np.arange(k,0,-1,dtype=float)/k
        proxy[shorts]=-np.arange(k,0,-1,dtype=float)/k
        result=super().solve(proxy,cov,prev,cost,short)
        return replace(result,objective=float(mu@result.weights))
