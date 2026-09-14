from dividend_component_match import reconcile

def rows():
 return [dict(id=str(i),ticker='X',ex_dividend_date='2024-01-02',pay_date='2024-01-10',record_date='2024-01-03',currency='USD',cash_amount=a,dividend_type=t) for i,a,t in [(1,.2,'CD'),(2,.3,'SC')]]

def test_exact_components_share_payment():
 assert reconcile('X','2024-01-02',.5,rows())['component_total']=='0.5'

def test_different_paydates_cannot_collapse():
 r=rows();r[1]['pay_date']='2024-01-11';assert reconcile('X','2024-01-02',.5,r) is None

def test_duplicates_rejected_even_with_distinct_ids():
 r=rows();r[1]={**r[0],'id':'different'};assert reconcile('X','2024-01-02',.4,r) is None

def test_amount_mismatch_preserved():
 assert reconcile('X','2024-01-02',.49,rows()) is None

def test_currency_identity_and_dates_required():
 for key,value in [('currency','EUR'),('ticker','Y'),('pay_date','2023-01-01'),('pay_date','invalid')]:
  r=rows();r[0][key]=value;assert reconcile('X','2024-01-02',.5,r) is None
