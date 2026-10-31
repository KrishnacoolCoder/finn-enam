import json
import sqlite3
from contextlib import closing
from math import nan, inf

import pytest
from fastapi.testclient import TestClient
from app import financials as f, storage
from app.main import app
from scripts.seed_ntpc_financials import seed, MANIFEST

URL = 'https://example.com/primary-report.pdf'  # Synthetic unit-test fixture only.


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'finance.sqlite3'
    monkeypatch.setattr(storage, 'DB', path)
    storage.init()
    f.setup()
    return path


@pytest.mark.parametrize('current,base,pct,note', [
    (120,100,20,'Comparable positive base'), (100,0,None,'Zero base'),
    (-50,-100,None,'Loss narrowed'), (-150,-100,None,'Loss widened'),
    (20,-100,None,'Loss to profit'), (0,-100,None,'Loss to break-even'),
    (-20,100,-120,'Profit to loss')])
def test_growth_edge_cases(current,base,pct,note):
    assert f.growth(current,base) == pct
    assert note in f.growth_note(current,base)


@pytest.mark.parametrize('url', ['', 'http://example.com/report.pdf', 'https://', 'https://user:pass@example.com/report'])
def test_https_validation_still_enforced(database,url):
    with pytest.raises(ValueError,match='HTTPS'):
        f.save_quarter('TEST','2026-Q3',{'pat':100},url,'standalone')


@pytest.mark.parametrize('value', [nan,inf,-inf])
def test_nonfinite_rejected(database,value):
    with pytest.raises(ValueError,match='metric'):
        f.save_quarter('TEST','2026-Q3',{'pat':value},URL,'standalone')


def test_real_seed_idempotent_and_preserves_user_review(database):
    assert seed(database)['saved'] == 3
    rows = f.quarterly_snapshot('NTPC')
    assert len(rows) == 3 and all(not row['verified'] for row in rows)
    current = rows[0]
    assert current['period_label'] == 'Jul–Sep 2026'
    assert current['comparison']['revenue']['qoq_pct'] == 4.38
    assert current['comparison']['revenue']['yoy_pct'] == 16.82
    assert current['comparison']['pat']['qoq_pct'] == -0.42
    assert current['comparison']['pat']['yoy_pct'] == 14.33
    assert all(row['source_url'].startswith('https://www.bseindia.com/') for row in rows)
    assert 'DERIVED' in current['evidence_note']
    assert seed(database)['saved'] == 0
    f.save_quarter('NTPC','2026-Q3',current,current['source_url'],'standalone',2,True,current['evidence_note'])
    assert seed(database,replace_unverified=True)['skipped_existing'] == 1
    assert f.quarterly_snapshot('NTPC')[0]['verified'] is True


def test_seed_derivation_manifest():
    data=json.loads(MANIFEST.read_text())
    for row in data['quarters']:
        assert round(row['revenue']-sum(row['components'].values()),2) == row['ebitda']


def test_badges_reset_on_edit_and_comparison_needs_both_reviewed(database):
    for period,value in [('2026-Q1',100),('2025-Q4',80)]:
        f.save_quarter('TEST',period,{'pat':value},URL,'standalone',2,True)
    row=f.quarterly_snapshot('TEST')[0]
    assert row['comparison']['pat']['qoq_period']=='2025-Q4'
    assert row['comparison']['pat']['qoq_verified'] is True
    f.save_quarter('TEST','2026-Q1',{'pat':110},URL,'standalone',2)
    assert f.quarterly_snapshot('TEST')[0]['verified'] is False


@pytest.mark.parametrize('actual,expected',[(110,'delivered'),(90,'missed'),(100,'in line'),(101,'in line')])
def test_guidance_verdict_quote_and_tolerance(database,actual,expected):
    f.save_quarter('TEST','2026-Q3',{'revenue':actual},URL,'standalone',2)
    f.add_target('TEST','revenue','2026-Q3',100,'INR crore',URL,'Test-only fixture target',
        quote='Test-only quote: revenue target 100 crore.',basis='standalone',tolerance=1)
    result=f.guidance_comparison('TEST')[0]
    assert result['result']==expected and result['actual_verified'] is False
    assert result['quote'].startswith('Test-only quote')


def test_guidance_requires_quote_and_matching_basis(database):
    with pytest.raises(ValueError,match='quote'):
        f.add_target('TEST','pat','2026-Q3',10,'INR crore',URL,'Test target',basis='standalone')
    f.save_quarter('TEST','2026-Q3',{'pat':100},URL,'standalone',2)
    f.add_target('TEST','pat','2026-Q3',10,'INR crore',URL,'Test target',quote='Test-only exact quote',basis='consolidated')
    assert f.guidance_comparison('TEST')[0]['result']=='Insufficient comparable data'


def test_negative_base_guidance_has_no_false_verdict(database):
    f.save_quarter('TEST','2025-Q3',{'pat':-100},URL,'standalone')
    f.save_quarter('TEST','2026-Q3',{'pat':100},URL,'standalone')
    f.add_target('TEST','pat','2026-Q3',10,'percent',URL,'Test-only growth target',
        'yoy_growth_pct',quote='Test-only quoted growth target.',basis='standalone')
    assert f.guidance_comparison('TEST')[0]['actual'] is None


def test_browser_api_save_and_quote_validation(database):
    with TestClient(app) as client:
        body={'ticker':'TEST','period':'2026-Q3','pat':100,'basis':'standalone','source_url':URL}
        assert client.post('/api/financials/quarter',json=dict(body,source_url='')).status_code==400
        assert client.post('/api/financials/quarter',json=dict(body,verified=True)).status_code==400
        assert client.post('/api/financials/quarter',json=dict(body,evidence_page=2,verified=True)).status_code==200
        assert client.get('/api/financials/TEST').json()[0]['verification_label']=='Verified by user'
        target={'ticker':'TEST','period':'2026-Q3','metric':'pat','target':100,'unit':'INR crore',
                'source_url':URL,'statement':'Test-only target','basis':'standalone'}
        assert client.post('/api/financials/target',json=target).status_code==422
        assert client.post('/api/financials/target',json=dict(target,quote='Test-only exact target quote')).status_code==200
        assert client.get('/api/financials/targets/TEST').json()[0]['result']=='in line'


def test_old_schema_migrates_unverified(tmp_path,monkeypatch):
    path=tmp_path/'legacy.sqlite3'
    monkeypatch.setattr(storage,'DB',path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE quarterly_financials(id INTEGER PRIMARY KEY,ticker TEXT,period TEXT,
            revenue REAL,ebitda REAL,pbt REAL,pat REAL,unit TEXT,source_url TEXT,UNIQUE(ticker,period))''')
        db.execute("INSERT INTO quarterly_financials VALUES(1,'TEST','2026-Q3',1,1,1,1,'INR crore',?)",(URL,))
    f.setup(); f.setup()
    assert f.quarterly_snapshot('TEST')[0]['verified'] is False
