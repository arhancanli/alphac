"""Fixed-group research allocator. No production defaults or forecast changes."""
import numpy as np
from alphaforge.portfolio.optimizer import OptResult, PortfolioConstraints, _validate_inputs

GROUPS = {
    'equity': ('SPY', 'QQQ', 'IWM', 'EFA', 'EEM'),
    'rates': ('SHY', 'IEF', 'TLT'),
    'currency': ('FXE', 'FXY', 'UUP'),
    'commodity': ('DBA', 'DBC', 'GLD', 'SLV', 'UNG', 'USO'),
}
ID_GROUP = {f'XUSE:CASH:{symbol}USD': group for group, symbols in GROUPS.items() for symbol in symbols}


class GroupRiskAllocator:
    def __init__(self, constraints=None):
        self.constraints = constraints if constraints is not None else PortfolioConstraints()
        self.last_diagnostics = None

    def solve_for_ids(self, ids, mu_ann, cov_ann, w_prev, cost_frac_oneway, shortable):
        self.last_diagnostics = None
        ids = tuple(ids)
        if len(set(ids)) != len(ids) or any(i not in ID_GROUP for i in ids):
            raise ValueError('duplicate or unclassified instrument')
        mu, cov, _, _, short = _validate_inputs(mu_ann, cov_ann, w_prev, cost_frac_oneway, shortable)
        if len(ids) != len(mu):
            raise ValueError('instrument order/shape mismatch')
        if not np.allclose(cov, cov.T, atol=1e-12, rtol=1e-10):
            raise ValueError('group covariance must be symmetric')
        sign = np.sign(mu)
        sign = np.where((sign < 0) & (short != 1), 0., sign)
        active = sign != 0
        sigma = np.sqrt(np.clip(np.diag(cov), 0, None))
        if np.any(active & ~(sigma > 0)):
            raise ValueError('nonpositive active variance')
        base = np.zeros(len(ids))
        base[active] = sign[active] / sigma[active]
        weights = np.zeros(len(ids))
        group_indices = {}
        before = {}
        for group in GROUPS:
            idx = np.array([i for i, iid in enumerate(ids) if ID_GROUP[iid] == group], dtype=int)
            group_indices[group] = idx
            if not idx.size or not active[idx].any():
                before[group] = 0.
                continue
            vector = base[idx]
            variance = float(vector @ cov[np.ix_(idx, idx)] @ vector)
            if not np.isfinite(variance) or variance <= 0:
                raise ValueError('nonpositive active group variance')
            weights[idx] = vector / np.sqrt(variance)
            before[group] = float(np.sqrt(weights[idx] @ cov[np.ix_(idx, idx)] @ weights[idx]))
        # Exact existing TrendVolTarget gross, clip and capped-renormalization operations.
        c = self.constraints
        gross = float(np.abs(weights).sum())
        if gross > 0:
            weights *= c.gross_max / gross
            weights = np.clip(weights, -c.w_max, c.w_max)
            gross_clipped = float(np.abs(weights).sum())
            max_abs = float(np.abs(weights).max())
            if gross_clipped > 0 and max_abs > 0:
                weights *= min(c.gross_max / gross_clipped, c.w_max / max_abs)
        after = {group: float(np.sqrt(max(float(weights[idx] @ cov[np.ix_(idx,idx)] @ weights[idx]), 0))) if idx.size else 0. for group, idx in group_indices.items()}
        self.last_diagnostics = {'ids': ids, 'group_vol_before_limits': before, 'group_vol_after_limits': after,
                                 'gross_after_limits': float(np.abs(weights).sum()),
                                 'claim': 'Stand-alone group risk before limits; not final equal portfolio risk.'}
        return OptResult(weights=weights, status='fallback_used', ex_ante_vol_ann=float(np.sqrt(max(float(weights @ cov @ weights), 0))), objective=float(mu @ weights))
