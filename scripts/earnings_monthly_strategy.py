"""Isolated monthly rank Strategy with explicit source-session clocks."""
from datetime import datetime,time,timezone
from alphaforge.risk.monitors import DrawdownLadder
from earnings_change_candidate import target_weights


def callback_routes(schedule):
    rows=list(schedule);routes={}
    for prior,current in zip(rows,rows[1:]):
        day,op,cl=current
        if prior[0]>=day or prior[2]>=op:
            raise ValueError('Unordered sessions')
        label=int(datetime.combine(day,time(),timezone.utc).timestamp()*1000)
        routes[label]=(prior[2],op,(prior[0].year,prior[0].month)!=(day.year,day.month))
    return routes


class EarningsMonthlyStrategy:
    def __init__(self, *, routes, score_provider, stable_ids, eligible_provider):
        self.routes=dict(routes)
        self.score_provider=score_provider
        self.stable_ids=dict(stable_ids)
        self.eligible_provider=eligible_provider
        self.ladder=DrawdownLadder(dd_half_frac=.10,dd_flat_frac=.15,flat_cooldown_bars=10)
        self.base={};self.multiplier=1.;self.last_ts=None;self.audit=[]

    def on_bar_close(self,ctx):
        if self.last_ts is not None and ctx.ts<=self.last_ts:
            raise ValueError('Strategy requires increasing callbacks')
        self.last_ts=ctx.ts
        if ctx.ts not in self.routes:
            raise ValueError('Callback has no verified source session')
        decision,execution,monthly=self.routes[ctx.ts]
        self.ladder.update(ctx.equity)
        scale=self.ladder.gross_multiplier()
        # Membership/borrow restrictions are refreshed even between monthly ranks.
        eligible=set(self.eligible_provider(decision)) & set(ctx.instruments)
        held=set(ctx.positions)
        banned={i for i in held|set(self.base) if i not in eligible or (
            self.base.get(i,0)<0 and not ctx.instruments[i].can_short)}
        for i in banned:self.base[i]=0.
        if monthly:
            values=self.score_provider(decision)
            scores={i:v for i,v in values.items() if i in eligible}
            self.base=target_weights(scores,stable_ids=self.stable_ids,
                shortable={i:ctx.instruments[i].can_short for i in scores},held_ids=held|set(self.base))
        # Risk may reduce immediately; recovery waits for a monthly rebalance.
        rescale=monthly or scale<self.multiplier
        emit=rescale or bool(banned)
        effective=scale if monthly else min(scale,self.multiplier)
        self.multiplier=effective
        targets={i:w*effective for i,w in self.base.items()} if rescale else {i:0. for i in banned}
        if emit:
            targets.update({i:0. for i in banned})
            self.audit.append({'callback':ctx.ts,'physical_decision':decision.isoformat(),
                'physical_execution':execution.isoformat(),'monthly':monthly,'scale':effective,'targets':targets.copy()})
        return targets
