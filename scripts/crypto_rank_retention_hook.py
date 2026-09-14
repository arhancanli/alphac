"""Per-instance research allocator installation; strategy/risk methods unchanged."""
from crypto_rank_retention import RankRetentionAllocator
from alphaforge.portfolio.optimizer import RankEqualVolFallback

def install_rank_retention(strategy, *, buffer_ranks=1):
    previous=getattr(strategy,'_research_retention_width',None)
    if previous is not None:
        if previous!=buffer_ranks:raise ValueError('Cannot change persistent retention width')
        if not isinstance(strategy._allocator,RankRetentionAllocator):raise ValueError('Retention allocator replaced unexpectedly')
        return
    if type(strategy._allocator) is not RankEqualVolFallback:
        raise ValueError('Original rank allocator required')
    strategy._allocator=RankRetentionAllocator(strategy._allocator.constraints,buffer_ranks=buffer_ranks)
    strategy._research_retention_width=buffer_ranks
