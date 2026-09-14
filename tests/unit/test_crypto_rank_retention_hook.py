from types import SimpleNamespace
import pytest
from crypto_rank_retention_hook import install_rank_retention
from crypto_rank_retention import RankRetentionAllocator
from alphaforge.portfolio.optimizer import RankEqualVolFallback
from alphaforge.portfolio.strategy import BlendStrategy
from alphaforge.risk.monitors import DrawdownLadder

def strategy():
    ladder=DrawdownLadder();ladder.update(100.)
    return SimpleNamespace(_allocator=RankEqualVolFallback(),_ladder=ladder,_equity_hist=[],_scale_hist=[],_last_scale=1.,_n_bars_halted_flat=0,_n_bars_half_gross=0,_n_hold_between_rebalance=0,_rebalance_anchor='run',_next_rebalance_ts=1000,_last_targets={'A':.2,'B':-.2})

def test_instance_isolation_and_idempotence():
    a,b=strategy(),strategy();ladder=a._ladder;constraints=a._allocator.constraints
    install_rank_retention(a);installed=a._allocator;install_rank_retention(a)
    assert a._allocator is installed and isinstance(installed,RankRetentionAllocator)
    assert type(b._allocator) is RankEqualVolFallback and a._ladder is ladder and installed.constraints is constraints
    with pytest.raises(ValueError):install_rank_retention(a,buffer_ranks=0)

def test_immediate_half_and_flat_exit_unchanged():
    for equity,expected in [(89.,{'A':.1,'B':-.1}),(84.,{'A':0.,'B':0.})]:
        a,b=strategy(),strategy();install_rank_retention(a)
        ctx=SimpleNamespace(equity=equity,ts=1,instruments={'A':object(),'B':object()})
        assert BlendStrategy.on_bar_close(a,ctx)==BlendStrategy.on_bar_close(b,ctx)==expected
        assert a._ladder.state==b._ladder.state

def test_normal_between_rebalances_is_hold():
    a=strategy();install_rank_retention(a)
    assert BlendStrategy.on_bar_close(a,SimpleNamespace(equity=100.,ts=1,instruments={}))=={}
