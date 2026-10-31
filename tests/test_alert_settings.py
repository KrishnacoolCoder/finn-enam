from datetime import datetime,timezone

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB',tmp_path/'settings.sqlite3');storage.init()
    return TestClient(app)


def test_event_settings_persist_and_legacy_updates_preserve_them(client):
    saved=client.put('/api/settings',json={'price_threshold':3.5,'volume_threshold':2.25,
        'min_priority':75,'event_types':['results','management_change','results']})
    assert saved.status_code==200
    assert saved.json()['event_types']==['results','management_change']
    assert saved.json()['revision']
    storage.init()
    assert client.get('/api/settings').json()==saved.json()
    old_client=client.put('/api/settings',json={'price_threshold':4,'volume_threshold':3,'min_priority':40})
    assert old_client.json()['event_types']==['results','management_change']
    assert old_client.json()['revision']!=saved.json()['revision']


def test_event_settings_validate_and_allow_no_filing_alerts(client):
    body={'price_threshold':5,'volume_threshold':2,'min_priority':40,'event_types':['not-an-event']}
    assert client.put('/api/settings',json=body).status_code==422
    body['event_types']=[]
    assert client.put('/api/settings',json=body).json()['event_types']==[]
    assert client.get('/api/alerts/filings').json()==[]
    body['volume_threshold']=0
    assert client.put('/api/settings',json=body).status_code==422


def test_filing_alerts_apply_type_priority_and_exclude_demos(client):
    with storage.connection() as db:
        for ticker,title,source in [('NTPC','Quarterly financial results','BSE'),
                                    ('ITC','Dividend record date','BSE'),
                                    ('TCS','Quarterly financial results','synthetic_demo')]:
            db.execute('''INSERT INTO filings(ticker,published,title,url,category,score,source)
                VALUES (?,?,?,?,?,?,?)''',(ticker,datetime.now(timezone.utc).isoformat(),title,
                'https://example.com/'+ticker+'.pdf','results',94,source))
    client.put('/api/settings',json={'price_threshold':5,'volume_threshold':2,'min_priority':75,'event_types':['results']})
    alerts=client.get('/api/alerts/filings').json()
    assert [g['ticker'] for g in alerts]==['NTPC']
    # Full feed remains available independently of alert preferences.
    assert len(client.get('/api/filings/grouped').json())==3
