from datetime import date
from decimal import Decimal as D
import pytest
from bil_cash_ledger import Price, Distribution, replay, combine_row


def dt(x):return date.fromisoformat(x)
def p(day, price='100'):return Price(dt(day), D(price), D(price))
def event(ex, pay, amount='1'):return Distribution(dt(ex), dt(pay), D(amount))
def run(prices, events=(), end=None, cost='0'):
    return replay(prices, events, [x.day for x in prices], prices[0].day,
                  dt(end) if end else prices[-1].day, D('1000'), D(cost))


def test_ex_date_new_shares_not_entitled():
    row=run([p('2023-01-03')],[event('2023-01-03','2023-01-06')])[0]
    assert row['quantity']==10 and row['accrued']==row['pending']==0


def test_pending_cannot_fund_monthly_buy_and_endpoint_retains_it():
    rows=run([p('2023-01-31'),p('2023-02-01','90')],
             [event('2023-02-01','2023-02-06','10')])
    row=rows[-1]
    assert row['pending']==100 and row['cash']==0 and row['bought']==0
    assert row['nav']==1000 and row['net_return']==0


def test_pay_date_not_available_at_same_open_but_next_month_is():
    rows=run([p('2023-01-30'),p('2023-01-31'),p('2023-02-01'),p('2023-03-01')],
             [event('2023-01-31','2023-02-01','10')])
    byday={x['day']:x for x in rows}
    pay=byday[dt('2023-02-01')]
    assert pay['available_at_open']==0 and pay['bought']==0
    assert pay['paid']==pay['cash']==100 and pay['pending']==0
    assert byday[dt('2023-02-02')]['available_at_open']==100
    assert rows[-1]['bought']==1 and rows[-1]['cash']==0


def test_costs_integer_cash_and_stress_multiplier():
    normal=run([p('2023-01-03')],cost='6')[0]
    stress=run([p('2023-01-03')],cost='12')[0]
    assert normal['quantity']==stress['quantity']==9
    assert normal['fee']==D('.54') and stress['fee']==D('1.08')
    assert normal['cash']==D('99.46') and stress['cash']==D('98.92')
    assert normal['nav']==D('999.46') and stress['nav']==D('998.92')


def test_future_prices_and_events_do_not_change_prefix():
    prices=[p('2023-01-03'),p('2023-01-04','99')]
    before=run(prices)
    after=run(prices+[p('2023-02-01','999')],
              [event('2023-02-01','2023-02-06','20')])
    assert after[:len(before)]==before


def test_closed_pay_day_changes_cash_not_nav():
    rows=run([p('2023-01-05'),p('2023-01-06','99')],
             [event('2023-01-06','2023-01-07')],end='2023-01-08')
    assert rows[1]['pending']==10
    assert rows[2]['paid']==10 and rows[2]['pending']==0
    assert rows[2]['nav']==rows[1]['nav']==1000
    assert rows[2]['net_return']==rows[3]['net_return']==0


def test_missing_session_rejected():
    with pytest.raises(ValueError,match='exactly verified'):
        replay([p('2023-01-03')],[],[dt('2023-01-03'),dt('2023-01-04')],
               dt('2023-01-03'),dt('2023-01-04'))


def test_combination_preserves_non_cash_and_benchmark():
    base=dict(day='2023-01-03',max=.01,trend=-.02,crypto=.03,benchmark=.0001,
              cash_contribution=0,total=.0045,excess=.0044)
    out=combine_row(base,D('.001'))
    assert all(out[k]==base[k] for k in ('day','max','trend','crypto','benchmark'))
    assert out['total']==pytest.approx(.004825)
    assert out['excess']==pytest.approx(.004725)
    assert base['cash_contribution']==0
