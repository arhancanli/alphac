from datetime import datetime,date,timedelta,timezone
from decimal import Decimal
import pytest
from earnings_filing_inputs import prepare
from earnings_change_candidate import score_at,target_weights,month_routes


def filing(dk,rp,fp,income,assets='100'):
 return prepare(dict(ticker='NA',dimension='ARQ',datekey=dk,reportperiod=rp,fiscalperiod=fp,netinccmn=income,assets=assets),{'NA':'s'})

def pair():
 p=filing('2023-07-31','2023-07-01','2023-Q3','10')
 c=filing('2024-07-31','2024-06-29','2024-Q3','30','200')
 return c,p


def test_formula_uses_prior_assets_and_known_versions():
 c,p=pair();future=filing('2024-08-10','2024-06-29','2024-Q3','999')
 fx={f:Decimal(1) for f in [c,p,future]}
 assert score_at([c,p,future],'s',c.available_at,usd_metadata=True,fx_by_filing=fx)==.2
 assert score_at([c,p],'s',c.available_at,usd_metadata=True,fx_by_filing=fx)==.2
 assert score_at([c,p],'s',c.available_at-timedelta(seconds=1),usd_metadata=True,fx_by_filing=fx) is None


def test_currency_missingness_and_exact_freshness():
 c,p=pair();fx={c:Decimal(1),p:Decimal(1)}
 def score(at,usd=True, rates=fx):return score_at([c,p],'s',at,usd_metadata=usd,fx_by_filing=rates)
 assert score(c.available_at+timedelta(days=180))==.2
 assert score(c.available_at+timedelta(days=180,seconds=1)) is None
 assert score(c.available_at,False) is None
 assert score(c.available_at,rates={c:Decimal(1)}) is None
 assert score(c.available_at,rates={c:Decimal(1),p:Decimal('.9')}) is None


def inputs(n=60):
 scores={str(i):float(i) for i in range(n)}
 ids={i:f's{int(i):03d}' for i in scores};shorts={i:True for i in scores}
 return scores,ids,shorts


def test_rank_and_explicit_exit_gross_net():
 s,ids,b=inputs();original=s.copy()
 w=target_weights(s,stable_ids=ids,shortable=b,held_ids=['old'])
 assert {i for i,v in w.items() if v>0}=={str(i) for i in range(40,60)}
 assert {i for i,v in w.items() if v<0}=={str(i) for i in range(20)}
 assert sum(w.values())==pytest.approx(0)
 assert sum(abs(v) for v in w.values())==pytest.approx(1)
 assert w['old']==0 and s==original


def test_borrow_restrictions_and_insufficient_flat():
 s,ids,b=inputs()
 for i in range(10):b[str(i)]=False
 w=target_weights(s,stable_ids=ids,shortable=b)
 assert {i for i,v in w.items() if v<0}=={str(i) for i in range(10,30)}
 b={i:False for i in b}
 assert not any(target_weights(s,stable_ids=ids,shortable=b,held_ids=['old']).values())
 s,ids,b=inputs(39)
 assert not any(target_weights(s,stable_ids=ids,shortable=b).values())


def test_ties_input_order_and_identity_collision():
 s,ids,b=inputs();s={i:1.0 for i in s}
 w=target_weights(s,stable_ids=ids,shortable=b)
 assert w==target_weights(dict(reversed(list(s.items()))),stable_ids=ids,shortable=b)
 assert {i for i,v in w.items() if v>0}=={str(i) for i in range(20)}
 ids['1']=ids['0']
 with pytest.raises(ValueError):target_weights(s,stable_ids=ids,shortable=b)


def test_real_calendar_holiday_and_early_close_routes():
 import exchange_calendars as xc
 cal=xc.get_calendar('XNYS',start='2024-11-25',end='2025-01-10')
 schedule=[(s.date(),cal.session_open(s).to_pydatetime(),cal.session_close(s).to_pydatetime()) for s in cal.sessions]
 routes=month_routes(schedule)
 assert routes[datetime(2024,11,29,18,tzinfo=timezone.utc)]==datetime(2024,12,2,14,30,tzinfo=timezone.utc)
 assert routes[datetime(2024,12,31,21,tzinfo=timezone.utc)]==datetime(2025,1,2,14,30,tzinfo=timezone.utc)
 assert len(routes)==2
 with pytest.raises(ValueError):month_routes(list(reversed(schedule)))
