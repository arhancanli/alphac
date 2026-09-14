"""Exact engine window and split dependency scope; no feature or return computation."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from alphaforge.core.calendar import XNYSCalendar
from alphaforge.core.time import Timeframe
from alphaforge.signals.service import _SIGMA_SPEC

ROOT=Path(__file__).resolve().parents[1]
COVER=ROOT/'evidence/core-2023-2026-coverage-20260913'
OUT=ROOT/'evidence/core-2023-2026-equity-dependencies-20260913'

def main():
    OUT.mkdir(exist_ok=False)
    refs={}
    def bind(p):
        refs[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return p
    protocol=json.loads(bind(COVER/'PROTOCOL.json').read_text())
    coverage=pd.read_csv(bind(COVER/'coverage.csv'))
    coverage=coverage[coverage.sleeve=='k30_dn_63'].set_index('instrument_id')
    manifest=json.loads(bind(COVER/'source_manifest.json').read_text())['sha256']
    metadata={x['instrument_id']:x for x in json.loads(bind(COVER/'instrument_versions.json').read_text())}
    train=protocol['equity_train_start_ms'];end=protocol['end_exclusive_ms'];cal=XNYSCalendar();tf=Timeframe.D1
    lookback=_SIGMA_SPEC.lookback_bars
    warm=cal.expected_bar_opens(train-(2*lookback+8)*tf.ms,train+tf.ms,tf)
    actual=warm[-(lookback+1)];old=protocol['equity_shared_context_start_ms']
    additional=cal.expected_bar_opens(actual,old,tf)
    checks=[]
    for iid in coverage.index:
        meta=metadata[iid]
        needed=[t for t in additional if t>=meta['listed_ts'] and t<(meta['delisted_ts'] or end)]
        if not needed:continue
        observed=set()
        for p,h in manifest.items():
            if '/ohlcv_1d/' in p and f'instrument_id={iid}/year=2011/' in p:
                path=Path(p);bind(path);assert refs[p]==h
                series=pd.read_parquet(path,columns=['ts_open']).ts_open
                observed.update(pd.to_datetime(series,utc=True).astype('datetime64[ms, UTC]').astype('int64'))
        missing=sorted(set(needed)-observed)
        checks.append({'instrument_id':iid,'additional_expected':len(needed),'missing':missing})
    assert not any(x['missing'] for x in checks)
    failures=pd.read_csv(bind(ROOT/'evidence/core-2023-2026-gap-preparation-20260913/expanded_split_failures.csv'))
    rows=[]
    for r in failures.itertuples():
        ts=int(pd.Timestamp(r.ex_date).timestamp()*1000)
        if ts<actual or ts>=end:continue
        first=int(coverage.loc[r.instrument_id,'first_observed_ms'])
        before=ts<first
        n=len(cal.expected_bar_opens(ts+tf.ms,train+tf.ms,tf)) if ts<train else 0
        rows.append({'instrument_id':r.instrument_id,'ex_date':r.ex_date,'classification':r.classification,'precedes_first_retained_observation':before,'first_retained_observation_ms':first,'sessions_after_event_to_training':n,'ewma_initial_variance_perturbation_decay_if_complete':(1-2/169)**n,'disposition':'No retained pre-event price; cannot form a two-sided observed split return' if before else 'Unresolved historical boundary in shared EWMA context; retain model limitation, not zero-effect clearance'})
    pd.DataFrame(rows).to_csv(OUT/'split_dependency_scope.csv',index=False)
    (OUT/'additional_session_checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    result={'engine_shared_context_start_ms':actual,'inventory_shared_context_start_ms':old,'additional_sessions':additional,'additional_listed_observations_checked':sum(x['additional_expected'] for x in checks),'missing_additional_observations':0,'warmup_shortened':False,'evaluation_horizon_changed':False,'split_failures_in_context':len(rows),'pre_observation_failures':sum(x['precedes_first_retained_observation'] for x in rows),'unresolved_two_sided_boundaries':[x['instrument_id'] for x in rows if not x['precedes_first_retained_observation']],'no_new_signals_or_returns':True,'qualification':False,'decision':'Use exact existing engine warmup; retain original action floor 2019-12-30 for comparable corrected reference. Earlier raw-price EWMA artifacts remain disclosed. Any full-history corporate-action revision is a separately registered variant, not a silent replacement.'}
    (OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    for p in [Path(__file__),ROOT/'src/alphaforge/features/engine.py',ROOT/'src/alphaforge/signals/service.py',ROOT/'scripts/alphamax_share_ratio_features.py',ROOT/'scripts/alphamax_session_price_basis.py']:bind(p)
    (OUT/'source_manifest.json').write_text(json.dumps({'sha256':refs},indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
