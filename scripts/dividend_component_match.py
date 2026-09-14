"""Conservative same-date component reconciliation, never source certification."""
from datetime import date
from decimal import Decimal

def reconcile(symbol, ex_date, amount, records):
    expected=Decimal(str(amount))
    if not expected.is_finite() or expected<=0 or len(records)<2:
        return None
    identifiers=set();terms=set();payments=set();total=Decimal(0)
    for row in records:
        identifier=row.get('id');pay=row.get('pay_date')
        try:
            valid_date=date.fromisoformat(pay)>=date.fromisoformat(ex_date)
            cash=Decimal(str(row['cash_amount']))
        except (TypeError,ValueError,KeyError):
            return None
        term=(row.get('dividend_type'),str(cash),row.get('record_date'),pay)
        if (not identifier or identifier in identifiers or term in terms
            or row.get('ticker')!=symbol or row.get('ex_dividend_date')!=ex_date
            or row.get('currency')!='USD' or not valid_date
            or not cash.is_finite() or cash<=0):return None
        identifiers.add(identifier);terms.add(term);payments.add(pay);total+=cash
    if len(payments)!=1 or abs(total-expected)>Decimal('0.00000001'):return None
    return {'pay_date':next(iter(payments)),'component_total':str(total),'vendor_ids':sorted(identifiers),
            'status':'COMPONENT_SUM_MATCH_NOT_SOURCE_OR_SECURITY_CERTIFICATION'}
