"""Durable funding monitoring under the production one-process-per-cycle pattern."""
from types import SimpleNamespace
import sqlite3

import pytest

from alphaforge.live.loop import LiveLoop
from alphaforge.live.store import TradingStore
from alphaforge.live.alerts import AlertLevel

IID='BINANCE:PERP:BTCUSDT'


def loop(store, held=True):
    instance=LiveLoop.__new__(LiveLoop)
    instance._store=store
    instance._funding_dry_cycles=0
    instance._bar_ms=3600000
    instance._funding_source=None
    positions=[SimpleNamespace(instrument_id=IID,qty=1.)] if held else []
    instance._broker=SimpleNamespace(account_at=lambda ts:SimpleNamespace(positions=positions),
                                     apply_funding=lambda *args:0.)
    instance.alerts=[]
    instance._alerter=SimpleNamespace(alert=lambda level,message:instance.alerts.append((level,message)))
    instance._book_mid=lambda *args:100.
    return instance


def test_missing_source_alerts_across_fresh_process_objects(tmp_path):
    path=tmp_path/'health.sqlite'
    threshold=LiveLoop._FUNDING_DRY_LIMIT
    for i in range(1,threshold+2):
        with TradingStore(path) as store:
            instance=loop(store)
            instance._settle_funding(i*3600000,{})
            assert instance._funding_dry_cycles==i
            assert bool(instance.alerts)==(i>=threshold)
            if i>=threshold: assert instance.alerts[0][0]==AlertLevel.CRITICAL


def test_flat_account_does_not_count_universe_members(tmp_path):
    with TradingStore(tmp_path/'health.sqlite') as store:
        instance=loop(store,held=False)
        for i in range(20):
            instance._note_funding_dry(i, {IID:SimpleNamespace(market_type=SimpleNamespace(name='PERP'))},reason='fixture')
        assert instance._funding_dry_cycles==0 and not instance.alerts


def test_zero_rate_held_settlement_resets_streak(tmp_path):
    with TradingStore(tmp_path/'health.sqlite') as store:
        instance=loop(store)
        instance._settle_funding(3600000,{})
        instance._funding_source=lambda *args,**kwargs:[(IID,7200000,0.)]
        instance._settle_funding(7200000,{})
        assert instance._funding_dry_cycles==0


def test_unheld_event_does_not_reset_streak(tmp_path):
    with TradingStore(tmp_path/'health.sqlite') as store:
        instance=loop(store)
        instance._settle_funding(3600000,{})
        instance._funding_source=lambda *args,**kwargs:[('BINANCE:PERP:ETHUSDT',7200000,0.)]
        instance._settle_funding(7200000,{})
        assert instance._funding_dry_cycles==2


def test_reader_error_persists_dry_observation(tmp_path):
    def fail(*args,**kwargs): raise ValueError('fixture')
    with TradingStore(tmp_path/'health.sqlite') as store:
        instance=loop(store);instance._funding_source=fail
        instance._settle_funding(3600000,{})
        assert instance._funding_dry_cycles==1


def test_replay_conflict_and_out_of_order_are_atomic(tmp_path):
    with TradingStore(tmp_path/'health.sqlite') as store:
        assert store.record_funding_health(1,dry=True)==1
        assert store.record_funding_health(1,dry=True)==1
        with pytest.raises(ValueError,match='Conflicting'): store.record_funding_health(1,dry=False)
        assert store.record_funding_health(2,dry=True)==2
        with pytest.raises(ValueError,match='Out-of-order'): store.record_funding_health(0,dry=True)
        assert store.record_funding_health(3,dry=False)==0
        assert store.record_funding_health(4,dry=True)==1


def test_existing_database_upgrade_does_not_invent_past_health(tmp_path):
    path=tmp_path/'old.sqlite'
    with TradingStore(path) as store:
        store._conn.execute('DROP TABLE funding_health')
        store._conn.commit()
    with TradingStore(path) as store:
        assert store._conn.execute('SELECT COUNT(*) FROM funding_health').fetchone()[0]==0
        assert store.record_funding_health(100,dry=True)==1


def test_failed_health_write_does_not_claim_progress(tmp_path):
    with TradingStore(tmp_path/'health.sqlite') as store:
        store._conn.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_INSERT else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError): store.record_funding_health(1,dry=True)
        store._conn.set_authorizer(None)
        assert store.record_funding_health(2,dry=True)==1
