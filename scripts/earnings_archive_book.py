"""Frozen archive input book for the isolated earnings runner.

Construction prepares filing records only. Scoring remains disabled until the
runner has verified its reservation and explicitly enables it.
"""
from collections import defaultdict,Counter
import csv,io,zipfile,hashlib
from decimal import Decimal,InvalidOperation
from pathlib import Path
from earnings_filing_inputs import prepare
from earnings_change_candidate import score_at

class EarningsArchiveBook:
    def __init__(self, sf1_path, mapping_path, *, expected_sf1_sha256, expected_mapping_sha256, endpoint='2026-06-01'):
        self.enabled=False
        self.filings=defaultdict(list);self.fx={};self.invalid=Counter()
        p=Path(sf1_path);m=Path(mapping_path)
        for path,digest in [(p,expected_sf1_sha256),(m,expected_mapping_sha256)]:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError(f'Input changed: {path}')
        with m.open() as f: rows=list(csv.DictReader(f))
        if any(r['status']!='unique' for r in rows):raise ValueError('Ambiguous mapping')
        self.by_instrument={r['instrument_id']:r for r in rows}
        self.stable_ids={i:r['permatickers'] for i,r in self.by_instrument.items()}
        if len(self.by_instrument)!=len(rows) or len(set(self.stable_ids.values()))!=len(rows):
            raise ValueError('Duplicate instrument or stable ID')
        ticker_map={r['tickers']:r['permatickers'] for r in rows}
        if len(ticker_map)!=len(rows):raise ValueError('Duplicate raw ticker')
        with zipfile.ZipFile(p) as z:
            if len(z.namelist())!=1:raise ValueError('Expected one SF1 CSV')
            with z.open(z.namelist()[0]) as stream:
                for r in csv.DictReader(io.TextIOWrapper(stream)):
                    if r['ticker'] not in ticker_map or r['datekey']>endpoint:continue
                    try:
                        filing=prepare(r,ticker_map)
                        fx=Decimal(r['fxusd'])
                        if not fx.is_finite() or fx<=0:raise ValueError('Invalid currency ratio')
                    except (ValueError,InvalidOperation) as e:
                        self.invalid[type(e).__name__+': '+str(e)]+=1
                        continue
                    if filing in self.fx and self.fx[filing]!=fx:raise ValueError('Conflicting duplicate FX')
                    self.filings[filing.security_id].append(filing);self.fx[filing]=fx
        self.rows=sum(len(fs) for fs in self.filings.values())

    def enable_after_reservation(self, *, validated: bool):
        if validated is not True:raise ValueError('Validated reservation required')
        self.enabled=True

    def scores(self, decision):
        if not self.enabled:raise RuntimeError('Historical scoring disabled before reservation validation')
        result={}
        for iid,row in self.by_instrument.items():
            value=score_at(self.filings[row['permatickers']],row['permatickers'],decision,
                usd_metadata=row['currencies']=='USD',fx_by_filing=self.fx)
            if value is not None:result[iid]=value
        return result
