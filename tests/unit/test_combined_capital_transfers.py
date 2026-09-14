from decimal import Decimal as D
import pytest
from combined_capital_transfers import implied_transfers,WEIGHTS


def test_equal_returns_need_no_transfer():
    x=implied_transfers(dict.fromkeys(WEIGHTS,D('.01')),100000)
    assert x['next_nav']==101000 and x['one_way_redistribution']==0


def test_crypto_gain_requires_other_subbook_nav_increases():
    r=dict.fromkeys(WEIGHTS,D(0));r['crypto']=D('.10')
    x=implied_transfers(r,100000)
    assert x['next_nav']==102250
    assert x['transfers']['crypto']==D('-1743.75000')
    assert x['one_way_redistribution']==D('1743.75000')
    assert sum(x['transfers'].values())==0


def test_exact_capital_scaling_and_immutability():
    r={'max':'.01','trend':'-.005','crypto':'.03','bil':'.0001'};before=r.copy()
    a=implied_transfers(r,100000);b=implied_transfers(r,200000)
    assert b['one_way_redistribution']==2*a['one_way_redistribution']
    assert r==before


@pytest.mark.parametrize('value',['NaN','Infinity','-1','-1.01'])
def test_invalid_return_rejected(value):
    r=dict.fromkeys(WEIGHTS,'0');r['crypto']=value
    with pytest.raises(ValueError):implied_transfers(r,100000)
